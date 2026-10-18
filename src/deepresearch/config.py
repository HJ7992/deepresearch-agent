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
    # ---- 检索层（M2） ----
    embedding_api_key: str | None = field(
        default_factory=lambda: os.getenv("EMBEDDING_API_KEY") or None
    )
    embedding_base_url: str | None = field(
        default_factory=lambda: os.getenv("EMBEDDING_BASE_URL") or None
    )
    embedding_model: str | None = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL") or None
    )
    # 配了 QDRANT_URL 连服务端；否则用本地嵌入式模式（零部署）
    qdrant_url: str | None = field(
        default_factory=lambda: os.getenv("QDRANT_URL") or None
    )
    qdrant_local_path: str = field(
        default_factory=lambda: os.getenv("QDRANT_LOCAL_PATH", ".qdrant")
    )
    qdrant_collection: str = field(
        default_factory=lambda: os.getenv("QDRANT_COLLECTION", "docs")
    )
    top_k: int = field(
        default_factory=lambda: int(os.getenv("DEEPRESEARCH_TOP_K", "4"))
    )
    # verifier 的最低引用覆盖率，低于则打回重写
    citation_min_coverage: float = field(
        default_factory=lambda: float(os.getenv("DEEPRESEARCH_MIN_COVERAGE", "0.6"))
    )
    # 估算成本用（每百万 token 单价，按你的模型计价填）
    price_input_per_mtok: float = field(
        default_factory=lambda: float(os.getenv("DEEPRESEARCH_PRICE_IN", "0"))
    )
    price_output_per_mtok: float = field(
        default_factory=lambda: float(os.getenv("DEEPRESEARCH_PRICE_OUT", "0"))
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
