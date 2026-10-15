"""高层入口：组装真实模型图并执行一次完整调研。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from .graph import build_graph
from .llm import make_default_model
from .state import AgentState


def run(question: str, thread_id: str = "m1", max_revisions: int = 1) -> AgentState:
    """问题进、报告出。M1 用内存态 checkpoint 就够了，M3 换 Postgres 持久化。"""
    app = build_graph(make_default_model(), checkpointer=InMemorySaver(),
                      max_revisions=max_revisions)
    config = {"configurable": {"thread_id": thread_id}}
    return app.invoke({"question": question}, config=config)
