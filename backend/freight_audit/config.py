from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
# Serverless (Vercel): the deployment is read-only except /tmp, which is wiped on cold start.
WRITABLE = Path("/tmp/freight_audit") if os.getenv("VERCEL") else ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT / ".env", ROOT / "backend" / ".env"), extra="ignore")

    database_url: str = f"sqlite:///{(WRITABLE / 'freight_audit.db').as_posix()}"
    # Gemini. GOOGLE_API_KEY or GEMINI_API_KEY is picked up; leave empty to run fully offline.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Extraction backend: "auto" (Gemini if a key is set, else heuristic), "gemini", "heuristic".
    extractor: str = "auto"
    # USD per 1M tokens, for cost reporting only. Check current pricing for your model.
    llm_price_in: float = 0.30
    llm_price_out: float = 2.50
    llm_timeout_s: float = 120.0
    outbox_dir: Path = WRITABLE / "outbox"
    upload_dir: Path = WRITABLE / "uploads"
    cors_origins: str = "http://localhost:5173"
    dispute_from: str = "freight-audit@example.com"

    @property
    def api_key(self) -> str | None:
        return self.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
