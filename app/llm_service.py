import os
from groq import Groq, APIError
import json
from .config import MAX_DIFF_CHARS

class LLMService: # this will interact with Groq API
    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        # Validate before constructing: Groq() raises its own opaque error first,
        # which made the intended "check your .env" message unreachable.
        if not api_key:
            raise ValueError("GROQ_API_KEY not found. Set it in your .env file or environment.")
        self.client = Groq(api_key=api_key)
    
    # basically prompt template
    def _get_system_prompt(self) -> str:
        """
        Defines the master system prompt for the code analysis agent.
        """
        return """ 
You are "Heimdall", an expert Software Engineer and code reviewer. Your purpose is to analyze code changes and provide a concise, helpful review.
Analyze the provided `git diff` output. Based on the changes, you must provide the following:
1.  **summary**: A brief, one-sentence executive summary of the changes.
2.  **review**: A bulleted list of potential issues, including bugs, style violations, performance concerns, or missing tests. If there are no issues, return an empty list.
3.  **documentation**: A draft of Markdown documentation for any new functions or classes. If no new items require docs, provide an empty string.
4.  **tests**: A bulleted list of suggested unit test cases to validate the new code.

You MUST respond with a valid JSON object, and nothing else. The JSON object should have the keys "summary", "review", "documentation", and "tests".
        """
    
    def analyze_code_changes(self, code_diff: str)-> dict | None:
        """
        Analyzes a git diff using the Llama 3 70B model on Groq.

        Args:
            code_diff: A string containing the output of a `git diff`.

        Returns:
            A dictionary containing the structured analysis from the LLM,
            or None if an API error occurs.     
        """

        if not self.client:
            print("LLMService client is not initialized")
            return None

        truncated_diff = self._truncate_diff(code_diff or "")

        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": f"Here is the git diff to analyze:\n\n'''diff\n{truncated_diff}\n'''",
                    }
                ],
                model="llama3-70b-8192",
                temperature=0.2,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
        except APIError as e:
            print(f"An error occurred with the API:{e}")
            return None

        response_content = self._extract_content(chat_completion)
        if not response_content:
            print("Received content: Unable to retrieve due to empty completion.")
            return None

        try:
            review = json.loads(response_content)
        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON from LLM response:{e}")
            return None

        if not isinstance(review, dict):
            print(f"LLM returned {type(review).__name__}, expected a JSON object.")
            return None

        return review

    def _truncate_diff(self, code_diff: str) -> str:
        """
        Keeps the diff inside the model context window, preserving both the
        start (file headers) and the tail (final hunks) of an oversized diff.
        """
        if len(code_diff) <= MAX_DIFF_CHARS:
            return code_diff

        head = (MAX_DIFF_CHARS * 3) // 4
        tail = MAX_DIFF_CHARS - head
        omitted = len(code_diff) - MAX_DIFF_CHARS
        print(f"Diff of {len(code_diff)} chars truncated to {MAX_DIFF_CHARS} ({omitted} omitted)")
        return (
            f"{code_diff[:head]}\n"
            f"\n... [diff truncated, {omitted} characters omitted] ...\n\n"
            f"{code_diff[-tail:]}"
        )

    @staticmethod
    def _extract_content(chat_completion) -> str | None:
        """Pulls the message text out of a Groq completion, if there is one."""
        choices = getattr(chat_completion, "choices", None)
        if not choices:
            return None

        content = getattr(choices[0].message, "content", None)
        return content if isinstance(content, str) and content.strip() else None