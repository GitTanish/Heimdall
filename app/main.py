from fastapi import FastAPI, Request, HTTPException
from .github_service import GitHubService
from .llm_service import LLMService

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Heimdall AI Agent is running!"}

github_service = GitHubService()
llm_service = LLMService()

def format_review_comment(review_json: dict) -> str:
    """Formats the JSON review from the LLM into a Markdown comment."""
    summary = review_json.get("summary", "No summary provided.")
    review_points = review_json.get("review", [])
    documentation = review_json.get("documentation", "")
    tests = review_json.get("tests", [])

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
    payload = await request.json()

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

    except Exception as e:
        print(f"An error occurred: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")