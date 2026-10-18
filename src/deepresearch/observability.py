"""可选 Langfuse 观测：配置了 key 才挂回调，否则返回空列表。

设计取舍：不把 Langfuse 做成硬依赖——本地开发、CI 和演示没有 key 也能跑；
配好 LANGFUSE_* 后，每次调研的 LLM 调用会自动上报 trace（成本、延迟、输入输出）。
"""

from __future__ import annotations

import logging

from .config import settings

logger = logging.getLogger(__name__)


def make_callbacks() -> list:
    """返回 LangChain 回调列表；没有配置或依赖缺失时为空。"""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except Exception as exc:  # noqa: BLE001 — 观测是增强项，不能拖垮主流程
        logger.warning("Langfuse 已配置但初始化失败（%s），本次不上报", exc)
        return []
    logger.info("Langfuse 观测已启用")
    return [CallbackHandler()]
