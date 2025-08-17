import requests 
from .config import GITHUB_TOKEN

class GitHubService:
    def __init__(self):
        """Initializes the GitHub service with authentication headers."""
        if not GITHUB_TOKEN:
            raise ValueError("GitHub token not found. Please check your .env file.")
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {GITHUB_TOKEN}",
            # FIX: Correct the typo from 'vэ' to 'v3'.
            "Accept": "application/vnd.github.v3+json",
        })
        self.base_url = "https://api.github.com"

    def get_commit_diff(self, owner: str, repo: str, commit_sha: str) -> str | None:
        """Fetches the diff for a specific commit."""
        url = f"{self.base_url}/repos/{owner}/{repo}/commits/{commit_sha}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        try: 
            response = self.session.get(url, headers=headers)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f'Error occurred while fetching the commit diff: {e}')
            return None

    def post_comment_on_commit(self, owner: str, repo: str, commit_sha: str, comment_body: str) -> bool:
        """Posts a comment on a specific commit."""
        url = f"{self.base_url}/repos/{owner}/{repo}/commits/{commit_sha}/comments"
        payload = {'body': comment_body}
        
        response = None
        try:
            response = self.session.post(url, json=payload)
            # You can keep these debug lines for now to confirm the fix
            print(f"GitHub API Response Status: {response.status_code}")
            print(f"GitHub API Response Body: {response.text}")
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f'Error occurred while posting comment : {e}')
            if response is not None:
                print(f"Response body: {response.text}")
            return False