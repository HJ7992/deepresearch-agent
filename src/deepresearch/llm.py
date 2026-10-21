"""聊天模型工厂：整个项目只有这里 new 真实的 LLM 客户端。

谁在用：runner.build_app() 调 `make_default_model()` 造模型，再注入各个节点。

为什么用「外部注入」而不是节点里自己 new：节点只依赖一个「有 invoke 方法」的对象，
测试就能塞剧本假模型进去，离线跑完整流水线、零 API 开销（见 tests/test_fake_graph.py）。
"""

from langchain_openai import ChatOpenAI

from .config import Settings, settings


def make_default_model(override: Settings | None = None) -> ChatOpenAI:
    """按配置造一个聊天模型。任何 OpenAI 兼容端点都能用（含国产模型）。

    override 只在测试里用：传一份自己造好的 Settings，就不必改真实环境变量。
    """
    cfg = override or settings
    if not cfg.openai_api_key:
        # 这里主动给出人话错误，别让用户对着一堆 httpx 堆栈猜
        raise RuntimeError(
            "未配置模型 API key。请把 .env.example 复制为 .env 并填入 "
            "OPENAI_API_KEY（任意 OpenAI 兼容端点均可，含国产模型）。"
        )
    return ChatOpenAI(
        model=cfg.model_name,
        api_key=cfg.openai_api_key,
        base_url=cfg.openai_base_url or None,
        temperature=0.2,   # 调研任务要稳，不要发散
        timeout=60,
        max_retries=2,
    )
