import requests
from typing import Dict, Optional

from adapters.base import BaseAdapter


class HttpAdapter(BaseAdapter):
    """
    Generic adapter for ANY external system / client API.
    """

    def __init__(
        self,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        request_field: str = "prompt",
        response_path: str = "response",
        timeout: int = 60,
    ):
        self.endpoint = endpoint
        self.headers = headers or {}
        self.request_field = request_field
        self.response_path = response_path
        self.timeout = timeout

    @property
    def name(self) -> str:
        return f"http:{self.endpoint}"

    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        payload = {
            self.request_field: prompt,
            "temperature": temperature,
        }

        response = requests.post(
            self.endpoint,
            json=payload,
            headers={"Content-Type": "application/json", **self.headers},
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        return self._extract(data)

    def _extract(self, data: dict):
        """
        Supports nested response extraction like:
        "choices.0.message.content"
        """
        parts = self.response_path.split(".")
        current = data

        for part in parts:
            if isinstance(current, list):
                current = current[int(part)]
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise ValueError(f"Could not resolve response_path '{self.response_path}' in response: {data}")

        return str(current)