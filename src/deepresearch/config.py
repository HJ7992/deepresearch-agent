"""Environment-driven settings. Real model wiring lands in M1."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # reads .env when present; no-op otherwise


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY") or None
    )
    openai_base_url: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL") or None
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("DEEPRESEARCH_MODEL", "gpt-4o-mini")
    )
    langfuse_public_key: str | None = field(
        default_factory=lambda: os.getenv("LANGFUSE_PUBLIC_KEY") or None
    )
    langfuse_secret_key: str | None = field(
        default_factory=lambda: os.getenv("LANGFUSE_SECRET_KEY") or None
    )
    langfuse_host: str = field(
        default_factory=lambda: os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )


settings = Settings()
