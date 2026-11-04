"""Groq provider (OpenAI-compatible chat completions with JSON mode)."""
from __future__ import annotations

import httpx

from .base import LLMProvider, ProviderError

_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0, transport: httpx.BaseTransport | None = None):
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._transport = transport

    def complete_json(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(_URL, headers={"Authorization": f"Bearer {self._api_key}"}, json=body)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Groq HTTP {e.response.status_code}") from None
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise ProviderError(f"Groq request failed ({type(e).__name__})") from None
