"""Runtime configuration. Secrets only ever come from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

# Real environment variables always win over .env files (override=False).
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_path: str
    llm_provider: str
    gemini_api_key: str | None
    gemini_model: str
    groq_api_key: str | None
    groq_model: str
    llm_timeout_s: float
    stage_delay_ms: int
    sync_runs: bool
    cors_origins: list[str] = field(default_factory=list)


def get_settings() -> Settings:
    """Read settings fresh from the environment (not cached, so tests can override)."""
    return Settings(
        database_path=os.environ.get("DATABASE_PATH", str(BACKEND_DIR / "data" / "decision_sim.db")),
        llm_provider=os.environ.get("LLM_PROVIDER", "mock").strip().lower(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        groq_api_key=os.environ.get("GROQ_API_KEY") or None,
        groq_model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        llm_timeout_s=float(os.environ.get("LLM_TIMEOUT_SECONDS", "20")),
        stage_delay_ms=int(os.environ.get("STAGE_DELAY_MS", "250")),
        sync_runs=_bool("SYNC_RUNS", False),
        cors_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()],
    )
