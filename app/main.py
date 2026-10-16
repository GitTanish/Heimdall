import hashlib
import hmac
import json
import logging
from fastapi import FastAPI, Request, HTTPException
from .config import GITHUB_WEBHOOK_SECRET
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

    if "commits" not in payload or not payload.get('commits'):
        return {'status':'skipped', 'message':'Payload is not a push event with commits'}

    try:
        repo_info = payload['repository']
        # FIX: Use 'login' instead of 'name' for the owner.
        owner = repo_info['owner']['login']
        repo = repo_info['name']
        commit_sha = payload['after']

        print(f"Received push event for {owner}/{repo} on commit {commit_sha}")

        diff = github_service.get_commit_diff(owner, repo, commit_sha)
        if not diff:
            raise HTTPException(status_code=400, detail="Could not retrieve diff from GitHub.")
        
        review_json = llm_service.analyze_code_changes(diff)
        if not review_json:
            raise HTTPException(status_code=500, detail="Failed to get analysis from LLM service")
        
        comment_body = format_review_comment(review_json)
        success = github_service.post_comment_on_commit(owner, repo, commit_sha, comment_body)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to post comment to GitHub.")

        print(f"Successfully processed and posted review for commit {commit_sha}")
        return {"status": "success", "message": f"Review posted for commit {commit_sha}"}

    except HTTPException:
        raise
    except KeyError as e:
        print(f"An error occurred: missing payload field {e}")
        raise HTTPException(status_code=400, detail=f"Payload is missing required field: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
        raise HTTPException(status_code=500, detail="An internal server error occurred.") from e