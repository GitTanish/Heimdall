import hashlib
import hmac
import json
import logging
from fastapi import FastAPI, Request, HTTPException
from starlette.concurrency import run_in_threadpool
from .config import GITHUB_WEBHOOK_SECRET, MAX_COMMITS_PER_PUSH
from .github_service import GitHubService
from .llm_service import LLMService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("heimdall")

NULL_SHA = "0" * 40


def verify_webhook_signature(body: bytes, signature: str | None) -> None:
    """
    Validates GitHub's `X-Hub-Signature-256` HMAC so forged payloads cannot
    spend the LLM quota or post comments with the stored token.
    """
    if not GITHUB_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=503, detail="Webhook secret is not configured on the server."
        )

    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header.")

    digest = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(f"sha256={digest}", signature):
        print("Rejected webhook delivery with an invalid signature")
        raise HTTPException(status_code=401, detail="Webhook signature is invalid.")


app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Heimdall AI Agent is running!"}

github_service = GitHubService()
llm_service = LLMService()

if not GITHUB_WEBHOOK_SECRET:
    logger.error(
        "GITHUB_WEBHOOK_SECRET is not set: webhook requests will be rejected. "
        "Set it in .env to the secret configured on the GitHub webhook."
    )

def _as_text(value, default: str = "") -> str:
    """Coerces a model-supplied field into a printable string."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _as_list(value) -> list:
    """Coerces a model-supplied field into a list of printable strings."""
    if isinstance(value, list):
        return [text for text in (_as_text(item) for item in value) if text]
    single = _as_text(value)
    return [single] if single else []


def format_review_comment(review_json: dict) -> str:
    """Formats the JSON review from the LLM into a Markdown comment."""
    summary = _as_text(review_json.get("summary"), "No summary provided.")
    review_points = _as_list(review_json.get("review"))
    documentation = _as_text(review_json.get("documentation"))
    tests = _as_list(review_json.get("tests"))

    comment = f"### 🤖 Heimdall AI Code Review\n\n"
    comment += f"**Summary:** {summary}\n\n"

    if review_points:
        comment += "**Potential Issues & Suggestions:**\n"
        for point in review_points:
            comment += f"- {point}\n"
        comment += "\n"

    if documentation:
        comment += "**Documentation Draft:**\n"
        comment += f"```markdown\n{documentation}\n```\n\n"

    if tests:
        comment += "**Suggested Test Cases:**\n"
        for test in tests:
            comment += f"- {test}\n"
        comment += "\n"
        
    return comment

def _process_commit(owner: str, repo: str, commit_sha: str) -> dict:
    """
    Reviews a single commit and posts the result. Blocking (network + LLM), so
    it is only ever called from a worker thread.
    """
    result: dict = {"commit": commit_sha, "status": "failed"}

    try:
        diff = github_service.get_commit_diff(owner, repo, commit_sha)
        if not diff or not diff.strip():
            result.update(status="skipped", reason="no diff available")
            return result

        review_json = llm_service.analyze_code_changes(diff)
        if not review_json:
            result["reason"] = "LLM analysis unavailable"
            return result

        comment_body = format_review_comment(review_json)
        if github_service.post_comment_on_commit(owner, repo, commit_sha, comment_body):
            result["status"] = "reviewed"
        else:
            result["reason"] = "failed to post comment"
    except Exception:
        # One bad commit must not abort the rest of the push or leak internals.
        logger.exception("Unexpected error while reviewing %s", commit_sha)
        result["reason"] = "unexpected internal error"

    return result


def _extract_commits(payload: dict) -> list:
    """Collects the commit SHAs carried by a push payload, oldest first."""
    shas: list = []
    for entry in payload.get('commits') or []:
        sha = entry.get('id') or entry.get('sha') if isinstance(entry, dict) else None
        if sha and sha != NULL_SHA and sha not in shas:
            shas.append(sha)

    # A push of more than MAX_COMMITS_PER_PUSH commits carries no commits[] at
    # all, so fall back to the new head: it is present and always the last one.
    head = payload.get('after')
    if head and head != NULL_SHA and head not in shas:
        shas.append(head)

    return shas


@app.post("/webhook/github")
async def github_webhook(request: Request):
    body = await request.body()
    verify_webhook_signature(body, request.headers.get("X-Hub-Signature-256"))

    event = request.headers.get("X-GitHub-Event", "push")
    if event != "push":
        return {'status': 'skipped', 'message': f"Ignoring '{event}' event"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    if payload.get('deleted') or payload.get('after') == NULL_SHA:
        return {'status': 'skipped', 'message': 'Branch deletion is not reviewable'}

    commit_shas = _extract_commits(payload)
    if not commit_shas:
        return {'status': 'skipped', 'message': 'Payload is not a push event with commits'}

    repo_info = payload.get('repository') or {}
    # FIX: Use 'login' instead of 'name' for the owner.
    owner = (repo_info.get('owner') or {}).get('login')
    repo = repo_info.get('name')
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="Payload is missing repository owner/name.")

    reviewable = commit_shas[:MAX_COMMITS_PER_PUSH]
    if len(reviewable) < len(commit_shas):
        logger.warning(
            "Push has %d commits; only the first %d will be reviewed",
            len(commit_shas), len(reviewable),
        )

    logger.info(
        "Received push event for %s/%s on %s: %d commit(s)",
        owner, repo, payload.get('ref', 'unknown'), len(reviewable),
    )

    # The diff fetch and the LLM call are blocking; offloading keeps a slow
    # review from stalling the event loop for every other request.
    results = [
        await run_in_threadpool(_process_commit, owner, repo, sha)
        for sha in reviewable
    ]

    summary = {
        "reviewed": sum(1 for r in results if r["status"] == "reviewed"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
    }
    logger.info("Finished push for %s/%s: %s", owner, repo, summary)

    return {
        "status": "success" if not summary["failed"] else "partial",
        "message": (
            f"Reviewed {summary['reviewed']} of {len(results)} commit(s) "
            f"in {owner}/{repo}"
        ),
        "summary": summary,
        "results": results,
    }