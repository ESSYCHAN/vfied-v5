import os

from adapters.base import BaseAdapter


class AnthropicAdapter(BaseAdapter):
    def __init__(self, model: str = "claude-3-5-sonnet-20240620", system_prompt: str = None, api_key: str = None):
        # Per-run credential injection (MIGRATION.md Step 1): an explicit api_key
        # is the SaaS path (decrypted just-in-time, scoped to one run). Falling back
        # to the environment keeps local/CLI runs working.
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("No Anthropic credential: pass api_key or set ANTHROPIC_API_KEY.")

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
        kwargs = {
            "model": self.model,
            "max_tokens": 1024,
            "system": self.system_prompt if self.system_prompt else "",
            "messages": [{"role": "user", "content": prompt}],
        }
        if not self.model.startswith("claude-opus-4-7"):
            kwargs["temperature"] = temperature
        message = self.client.messages.create(**kwargs)

        return message.content[0].text.strip() if message.content else ""