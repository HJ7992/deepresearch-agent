"""可选观测：配了 Langfuse 的 key 才挂回调，否则返回空列表。

谁在用：runner._config() 把返回的回调拼进 graph.invoke 的 config。

为什么不做成硬依赖：本地开发、CI、演示往往没有 key。配好 LANGFUSE_* 之后，
每次调研的 LLM 调用会自动上报 trace（成本、延迟、输入输出），排查「哪一步慢/贵/错」
很方便；没配时用本地 UsageTracker + reports/*.json 记同样的指标，主流程不受影响。
"""

import logging

from .config import settings

logger = logging.getLogger(__name__)


def make_callbacks() -> list:
    """返回要挂到图上的 LangChain 回调列表；没配置或依赖缺失时返回空列表。"""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except Exception as exc:  # noqa: BLE001 — 观测是增强项，不能拖垮主流程
        logger.warning("Langfuse 已配置但初始化失败（%s），本次不上报", exc)
        return []
    logger.info("Langfuse 观测已启用")
    return [CallbackHandler()]
