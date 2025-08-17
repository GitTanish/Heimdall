import os
from groq import Groq, APIError
import json

class LLMService: # this will interact with Groq API
    def __init__(self):
        try:
            self.client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
            if not os.environ.get("GROQ_API_KEY"):
                raise ValueError("API KEY not found in .env")
        except Exception as e:
            print(f"Error intitializing Client:{e}")
            self.client =None
    
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
        
        try: 
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": f"Here is the git diff to analyze:\n\n'''diff\n{code_diff}\n'''",
                    }
                ],
                model="llama3-70b-8192",
                temperature=0.2,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )

            response_content = chat_completion.choices[0].message.content
            return json.loads(response_content)
        except APIError as e:
            print(f"An error occurred with the API:{e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON from LLM response:{e}")
            # response_content is only defined if chat_completion succeeds
            # So, print a placeholder if it's not defined
            print("Received content: Unable to retrieve due to decoding error.")
            return None