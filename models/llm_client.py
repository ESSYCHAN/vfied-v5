import os

from adapters.openai_adapter import OpenAIAdapter
from adapters.anthropic_adapter import AnthropicAdapter
from adapters.http_adapter import HttpAdapter


def build_adapter(config: dict, credential: str = None):
    """Build a model adapter.

    `credential` is the per-run API key for key-based providers (MIGRATION.md
    Step 1), injected by the caller (decrypted just-in-time, scoped to one run,
    never read from a shared env in SaaS). It falls back to the provider's env
    var when None so local/CLI runs keep working. Endpoint-based (`http`)
    providers take NO credential — VFIED holds none; any auth lives in `headers`.
    """
    provider = config.get("provider", "").lower()

    if provider == "openai":
        return OpenAIAdapter(
            model=config.get("model", "gpt-4o-mini"),
            system_prompt=config.get("system_prompt"),
            api_key=credential,
        )

    if provider == "anthropic":
        return AnthropicAdapter(
            model=config.get("model", "claude-3-5-sonnet-20240620"),
            system_prompt=config.get("system_prompt"),
            api_key=credential,
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