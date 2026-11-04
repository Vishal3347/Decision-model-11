"""Gemini provider (REST). The API key is sent in a header, never in the URL, and never logged."""
from __future__ import annotations

import httpx

from .base import LLMProvider, ProviderError

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0, transport: httpx.BaseTransport | None = None):
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._transport = transport

    def complete_json(self, system: str, user: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(_URL.format(model=self.model), headers={"x-goog-api-key": self._api_key}, json=body)
                resp.raise_for_status()
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Gemini HTTP {e.response.status_code}") from None
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise ProviderError(f"Gemini request failed ({type(e).__name__})") from None
