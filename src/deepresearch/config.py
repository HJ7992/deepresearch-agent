"""环境变量驱动的配置（有 .env 就读，没有就跳过）。
真实模型在 M1 接入，Langfuse 观测在 M4 接入。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # 有 .env 就读；没有也不报错


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
    # 结构化输出的首选实现方式。实际调用时有一整条自动降级链
    # （首选 → json_mode → prompted），所以通常不用改；
    # DeepSeek 思考型模型不支持 tool_choice，会自动落到 json_mode。
    structured_mode: str = field(
        default_factory=lambda: os.getenv("DEEPRESEARCH_STRUCTURED_MODE", "function_calling")
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
