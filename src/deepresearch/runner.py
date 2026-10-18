"""高层入口：组装真实模型 + 检索器 + 计量器，执行一次完整调研。

返回的字典额外带一个 "metrics" 键（调用次数、token、耗时、估算成本），
CLI 和 API 都用它落盘/返回。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from .config import settings
from .graph import build_graph
from .llm import make_default_model
from .retriever import get_store
from .state import AgentState
from .usage import UsageTracker


def run(question: str, thread_id: str = "m2", max_revisions: int = 1) -> AgentState:
    """问题进、报告出。M2 用内存 checkpoint，M3 换 Postgres 持久化。"""
    tracker = UsageTracker()
    app = build_graph(
        make_default_model(),
        retriever=get_store(),
        checkpointer=InMemorySaver(),
        max_revisions=max_revisions,
    )
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [tracker],
    }
    result = dict(app.invoke({"question": question}, config=config))
    result["metrics"] = tracker.summary(
        settings.price_input_per_mtok, settings.price_output_per_mtok
    )
    return result
