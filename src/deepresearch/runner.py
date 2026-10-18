"""高层入口：组装模型 + 检索器 + 持久化 checkpoint + 计量器。

- run(question, review=False)：启动一次调研；若 pause 则返回 paused=True；
- resume(thread_id, decision)：用 Command(resume=...) 继续暂停的调研；
- get_state(thread_id)：读取某一会话的最新状态（含报告）。
同一个 thread_id 的 checkpoint 落在 SQLite/Postgres，跨进程可恢复。
"""

from __future__ import annotations

from langgraph.types import Command

from .checkpointer import make_checkpointer
from .config import settings
from .graph import build_graph
from .llm import make_default_model
from .observability import make_callbacks
from .retriever import get_store
from .state import AgentState
from .usage import UsageTracker


def build_app(review: bool = False, max_revisions: int = 1, mode: str = "full"):
    """构建可持久化的图。

    mode：full=完整流水线；no_retrieval=关检索（消融）；
    no_verify=关引用强制（消融）。
    """
    retriever = None if mode == "no_retrieval" else get_store()
    return build_graph(
        make_default_model(),
        retriever=retriever,
        checkpointer=make_checkpointer(),
        max_revisions=max_revisions,
        enable_review=review,
        enforce_citations=(mode != "no_verify"),
    )


def _config(thread_id: str, tracker: UsageTracker) -> dict:
    callbacks = [tracker, *make_callbacks()]
    return {"configurable": {"thread_id": thread_id}, "callbacks": callbacks}


def _finish(result: dict, tracker: UsageTracker) -> AgentState:
    """补上计量信息与暂停标记。"""
    out = dict(result)
    out["metrics"] = tracker.summary(
        settings.price_input_per_mtok, settings.price_output_per_mtok
    )
    out["paused"] = "__interrupt__" in out
    return out


def run(
    question: str,
    thread_id: str = "m3",
    max_revisions: int = 1,
    review: bool = False,
    mode: str = "full",
) -> AgentState:
    """启动一次调研。review=True 时会在 human_gate 暂停，等待 resume。"""
    tracker = UsageTracker()
    app = build_app(review=review, max_revisions=max_revisions, mode=mode)
    result = app.invoke({"question": question}, _config(thread_id, tracker))
    return _finish(result, tracker)


def resume(thread_id: str, decision: dict, max_revisions: int = 1) -> AgentState:
    """恢复暂停的调研：decision = {"approved": bool, "comment": str}。"""
    tracker = UsageTracker()
    app = build_app(review=True, max_revisions=max_revisions)
    result = app.invoke(Command(resume=decision), _config(thread_id, tracker))
    return _finish(result, tracker)


def get_state(thread_id: str):
    """读取某会话的最新状态（用于 --resume 时打印已有报告）。"""
    app = build_app(review=True)
    return app.get_state({"configurable": {"thread_id": thread_id}})
