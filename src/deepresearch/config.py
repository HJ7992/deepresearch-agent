"""运行时配置：所有开关都从环境变量读，有 .env 文件就先加载它。

谁在用：几乎所有模块都写 `from .config import settings` 读同一份配置；
测试里用 `Settings(openai_api_key=None)` 造一份临时配置，只覆盖其中一项。

为什么用 dataclass + field(default_factory)：
字段默认值在「创建实例时」才求值（此时才去读环境变量），而不是在类定义时
就冻结成常量。所以先导入模块、再改环境变量、或在测试里显式传值，都能生效。
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # 有 .env 就读；没有也不报错


# ---------------------------------------------------------------------------
# 环境变量小工具：把「读环境变量 + 转换类型」都收在这里，字段声明就能一行写完
# ---------------------------------------------------------------------------

def _env_optional(name: str) -> str | None:
    """读一个可以缺省的字符串：没配、或写成空串，都算「没配」（返回 None）。"""
    return os.getenv(name) or None


def _env_str(name: str, default: str) -> str:
    """读一个有默认值的字符串：完全没配时才用 default（显式写的空串会保留）。"""
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    """读整数配置；没配就用 default。写错成非数字时照旧报错，让配错早点暴露。"""
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    """读浮点配置；规则同 _env_int。"""
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """一次导入期间生效的全部配置。frozen=True：拿到手就不要再改。"""

    # ---- 模型接入 ----
    openai_api_key: str | None = field(
        default_factory=lambda: _env_optional("OPENAI_API_KEY")
    )
    # 想接国产模型就填它们的 OpenAI 兼容地址；留空则用官方默认地址
    openai_base_url: str | None = field(
        default_factory=lambda: _env_optional("OPENAI_BASE_URL")
    )
    model_name: str = field(
        default_factory=lambda: _env_str("DEEPRESEARCH_MODEL", "gpt-4o-mini")
    )
    # 结构化输出的首选方式。真正调用时还有一整条降级链
    # （首选 → json_mode → prompted），所以通常不用改；
    # 例如 DeepSeek 思考型模型不支持 tool_choice，会自动落到 json_mode。
    structured_mode: str = field(
        default_factory=lambda: _env_str("DEEPRESEARCH_STRUCTURED_MODE", "function_calling")
    )

    # ---- 检索层 ----
    # 嵌入：三项都配了才用真实嵌入服务，否则退回本地哈希嵌入（离线、免费）
    embedding_api_key: str | None = field(
        default_factory=lambda: _env_optional("EMBEDDING_API_KEY")
    )
    embedding_base_url: str | None = field(
        default_factory=lambda: _env_optional("EMBEDDING_BASE_URL")
    )
    embedding_model: str | None = field(
        default_factory=lambda: _env_optional("EMBEDDING_MODEL")
    )
    # 向量库：配了 QDRANT_URL 就连服务端，否则用本地嵌入式模式（零部署）
    qdrant_url: str | None = field(
        default_factory=lambda: _env_optional("QDRANT_URL")
    )
    qdrant_local_path: str = field(
        default_factory=lambda: _env_str("QDRANT_LOCAL_PATH", ".qdrant")
    )
    qdrant_collection: str = field(
        default_factory=lambda: _env_str("QDRANT_COLLECTION", "docs")
    )
    # 每次检索取回几个片段
    top_k: int = field(
        default_factory=lambda: _env_int("DEEPRESEARCH_TOP_K", 4)
    )
    # verifier 的最低引用覆盖率，低于它本轮报告被打回重写
    citation_min_coverage: float = field(
        default_factory=lambda: _env_float("DEEPRESEARCH_MIN_COVERAGE", 0.6)
    )

    # ---- 持久化 ----
    # 默认 SQLite（零部署，进程重启后还能从断点续跑）；配了 DATABASE_URL 就用 Postgres
    checkpoint_db: str = field(
        default_factory=lambda: _env_str(
            "DEEPRESEARCH_CHECKPOINT_DB", "data/checkpoints.sqlite"
        )
    )
    database_url: str | None = field(
        default_factory=lambda: _env_optional("DATABASE_URL")
    )

    # ---- 成本估算（每百万 token 的单价，按你用的模型填；填 0 就是不计价）----
    price_input_per_mtok: float = field(
        default_factory=lambda: _env_float("DEEPRESEARCH_PRICE_IN", 0.0)
    )
    price_output_per_mtok: float = field(
        default_factory=lambda: _env_float("DEEPRESEARCH_PRICE_OUT", 0.0)
    )

    # ---- 观测（可选）：配了 key 才把 LLM 调用上报到 Langfuse ----
    langfuse_public_key: str | None = field(
        default_factory=lambda: _env_optional("LANGFUSE_PUBLIC_KEY")
    )
    langfuse_secret_key: str | None = field(
        default_factory=lambda: _env_optional("LANGFUSE_SECRET_KEY")
    )
    langfuse_host: str = field(
        default_factory=lambda: _env_str("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )


# 进程级唯一实例：业务代码统一 import 它，测试里自己 new 一个覆盖个别字段
settings = Settings()
