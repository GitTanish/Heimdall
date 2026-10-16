import logging
import requests
from .config import GITHUB_API_TIMEOUT, GITHUB_TOKEN

logger = logging.getLogger(__name__)

NULL_SHA = "0" * 40


class GitHubService:
    def __init__(self):
        """Initializes the GitHub service with authentication headers."""
        if not GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN not found. Set it in your .env file or environment.")

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {GITHUB_TOKEN}",
            # FIX: Correct the typo from 'vэ' to 'v3'.
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self.base_url = "https://api.github.com"

    def get_commit_diff(self, owner: str, repo: str, commit_sha: str) -> str | None:
        """Fetches the diff for a specific commit."""
        if not commit_sha or set(commit_sha) == {"0"}:
            logger.info("Skipping diff fetch for null commit sha %s", commit_sha)
            return None

        url = f"{self.base_url}/repos/{owner}/{repo}/commits/{commit_sha}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        try:
            response = self.session.get(url, headers=headers, timeout=GITHUB_API_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error('Error occurred while fetching the commit diff: %s', e)
            return None

    def post_comment_on_commit(self, owner: str, repo: str, commit_sha: str, comment_body: str) -> bool:
        """Posts a comment on a specific commit."""
        if not commit_sha or set(commit_sha) == {"0"}:
            logger.info("Skipping comment for null commit sha %s", commit_sha)
            return False

        url = f"{self.base_url}/repos/{owner}/{repo}/commits/{commit_sha}/comments"
        payload = {'body': comment_body}

        response = None
        try:
            response = self.session.post(url, json=payload, timeout=GITHUB_API_TIMEOUT)
            response.raise_for_status()
            logger.info("Posted review on %s/%s@%s", owner, repo, commit_sha)
            return True
        except requests.exceptions.RequestException as e:
            logger.error('Error occurred while posting comment : %s', e)
            if response is not None:
                logger.error("Response body: %s", response.text[:500])
            return False