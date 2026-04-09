import os
from openai import OpenAI

from adapters.base import BaseAdapter


class OpenAIAdapter(BaseAdapter):
    def __init__(self, model: str = "gpt-4o-mini", system_prompt: str = None):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment.")

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt

    @property
    def name(self) -> str:
        return f"openai:{self.model}"

    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        messages = []

        # Optional system prompt (ONLY if you want benchmark mode)
        if self.system_prompt:
            messages.append({
                "role": "system",
                "content": self.system_prompt
            })

        messages.append({
            "role": "user",
            "content": prompt
        })

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=messages,
        )

        return (response.choices[0].message.content or "").strip()