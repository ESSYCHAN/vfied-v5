import os

from adapters.base import BaseAdapter


class AnthropicAdapter(BaseAdapter):
    def __init__(self, model: str = "claude-3-5-sonnet-20240620", system_prompt: str = None):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found.")

        try:
            import anthropic
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt

    @property
    def name(self) -> str:
        return f"anthropic:{self.model}"

    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=temperature,
            system=self.system_prompt if self.system_prompt else "",
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        return message.content[0].text.strip() if message.content else ""