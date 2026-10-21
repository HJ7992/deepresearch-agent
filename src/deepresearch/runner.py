"""高层入口：把「模型 + 检索器 + checkpoint + 计量」组装好，对外只暴露三件事。

谁在用：main.py（CLI）、api.py（HTTP 服务）、mcp_server.py（MCP 工具）都调这里。

对外三个函数：
- run(question, ...)：启动一次调研；若停在人工审核，返回里 paused=True；
- resume(thread_id, decision)：用 Command(resume=...) 继续被暂停的调研；
- get_state(thread_id)：读某会话的最新状态（--resume 时先打印已有报告）。
同一个 thread_id 的 checkpoint 落在 SQLite/Postgres，跨进程可恢复。
"""

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

    mode 只用于评测消融：
    - full：完整流水线；
    - no_retrieval：不接检索器（看「没有资料」时会发生什么）；
    - no_verify：关掉引用硬门槛。
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
    """一次执行的 config：thread_id 决定 checkpoint 落到哪个会话，callbacks 负责计量。"""
    callbacks = [tracker, *make_callbacks()]
    return {"configurable": {"thread_id": thread_id}, "callbacks": callbacks}


def _finish(result: dict, tracker: UsageTracker) -> AgentState:
    """收尾：补上计量信息，并标出这次是不是停在人工审核。"""
    out = dict(result)
    out["metrics"] = tracker.summary(
        settings.price_input_per_mtok, settings.price_output_per_mtok
    )
    # 图被 interrupt 打断时，结果里会有 __interrupt__ 键
    out["paused"] = "__interrupt__" in out
    return out


def run(
    question: str,
    thread_id: str = "m3",
    max_revisions: int = 1,
    review: bool = False,
    mode: str = "full",
) -> AgentState:
    """启动一次调研。review=True 时会停在人工审核门，等 resume。"""
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
    """读取某个会话的最新状态（CLI 恢复前用来打印已有报告）。"""
    app = build_app(review=True)
    return app.get_state({"configurable": {"thread_id": thread_id}})
