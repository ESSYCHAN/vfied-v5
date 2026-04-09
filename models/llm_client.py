import os

from adapters.openai_adapter import OpenAIAdapter
from adapters.anthropic_adapter import AnthropicAdapter
from adapters.http_adapter import HttpAdapter


def build_adapter(config: dict):
    provider = config.get("provider", "").lower()

    if provider == "openai":
        return OpenAIAdapter(
            model=config.get("model", "gpt-4o-mini"),
            system_prompt=config.get("system_prompt"),
        )

    if provider == "anthropic":
        return AnthropicAdapter(
            model=config.get("model", "claude-3-5-sonnet-20240620"),
            system_prompt=config.get("system_prompt"),
        )

    if provider == "http":
        return HttpAdapter(
            endpoint=config["endpoint"],
            headers=config.get("headers"),
            request_field=config.get("request_field", "prompt"),
            response_path=config.get("response_path", "response"),
            timeout=config.get("timeout", 60),
        )

    raise ValueError(f"Unknown adapter provider: {provider}")