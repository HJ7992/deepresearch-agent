"""聊天模型工厂。模型永远由外部注入节点（依赖注入），
测试和 CI 用剧本假模型离线跑，零 API 开销。"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import Settings, settings


def make_default_model(override: Settings | None = None) -> ChatOpenAI:
    """按配置创建默认模型；任何 OpenAI 兼容端点都能用（含国产模型）。"""
    cfg = override or settings
    if not cfg.openai_api_key:
        raise RuntimeError(
            "未配置模型 API key。请把 .env.example 复制为 .env 并填入 "
            "OPENAI_API_KEY（任意 OpenAI 兼容端点均可，含国产模型）。"
        )
    return ChatOpenAI(
        model=cfg.model_name,
        api_key=cfg.openai_api_key,
        base_url=cfg.openai_base_url or None,
        temperature=0.2,
        timeout=60,
        max_retries=2,
    )
