import os 
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")

# Bound every outbound GitHub call so a stalled socket cannot pin a worker.
GITHUB_API_TIMEOUT = 30

# Keep prompts inside the model context window.
MAX_DIFF_CHARS = 60000

# Cap LLM spend for a single large push.
MAX_COMMITS_PER_PUSH = 20