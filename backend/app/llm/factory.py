"""Provider selection and the resilient wrapper that guarantees mock mode keeps working."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..config import Settings
from ..schemas import BriefingNarrative, LLMContext, Observation
from .base import LLMProvider
from .gemini import GeminiProvider
from .groq import GroqProvider
from .mock import MockProvider


class ResilientProvider:
    """Calls the configured provider, validates its JSON with Pydantic, and falls back to the mock."""

    def __init__(self, primary: LLMProvider, notice: str | None = None):
        self.primary = primary
        self.mock = MockProvider()
        self.notice = notice  # e.g. "GEMINI_API_KEY missing – running in mock mode"

    @property
    def public_info(self) -> dict[str, Any]:
        return {
            "provider": self.primary.name,
            "model": self.primary.model,
            "live": self.primary.live,
            "notice": self.notice,
        }

    @staticmethod
    def _reason(name: str, exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})[:5]
            return f"{name} returned invalid structured output (fields: {', '.join(fields)}); used mock reasoning"
        return f"{name} unavailable ({type(exc).__name__}: {str(exc)[:80]}); used mock reasoning"

    def analyze(self, obs: Observation, email: dict) -> tuple[LLMContext, str, str, str | None]:
        reason: str | None = self.notice if not self.primary.live else None
        if self.primary.live:
            try:
                ctx = LLMContext.model_validate(self.primary.analyze_email(obs, email))
                return ctx, self.primary.name, self.primary.model, None
            except Exception as exc:  # noqa: BLE001 - any provider failure must degrade gracefully
                reason = self._reason(self.primary.name, exc)
        ctx = LLMContext.model_validate(self.mock.analyze_email(obs, email))
        return ctx, "mock", self.mock.model, reason

    def briefing(self, facts: dict[str, Any]) -> tuple[BriefingNarrative, str]:
        if self.primary.live:
            try:
                return BriefingNarrative.model_validate(self.primary.write_briefing(facts)), self.primary.name
            except Exception:  # noqa: BLE001
                pass
        return BriefingNarrative.model_validate(self.mock.write_briefing(facts)), "mock"


def build_provider(settings: Settings, transport: Any = None) -> ResilientProvider:
    name = settings.llm_provider
    if name == "gemini":
        if settings.gemini_api_key:
            return ResilientProvider(GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_s, transport))
        return ResilientProvider(MockProvider(), "GEMINI_API_KEY is not set – running in deterministic mock mode")
    if name == "groq":
        if settings.groq_api_key:
            return ResilientProvider(GroqProvider(settings.groq_api_key, settings.groq_model, settings.llm_timeout_s, transport))
        return ResilientProvider(MockProvider(), "GROQ_API_KEY is not set – running in deterministic mock mode")
    return ResilientProvider(MockProvider())
