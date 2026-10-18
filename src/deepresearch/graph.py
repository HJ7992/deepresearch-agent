"""图构建器。

M3 流水线：
  planner ──Send 扇出──► researcher × N（并行，只答一个子问题）
        ──► collect（去重 + 全局重编号）──► writer
        ──► verifier（程序化核验）──► human_gate（HITL，可暂停）
        ──► critic ──不达标/被退回──► writer（修订轮数封顶）

设计要点（面试话术）：
- Send 是动态扇出：子问题数量在运行时才知道，不能用静态边；
- 路由条件同时看 critic 结论、引用覆盖率、无效引用、人工审核结果；
- max_revisions 计「修订轮数」：writer 最多跑 1 + max 次，防止无限烧钱。
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .config import settings
from .nodes import (
    make_collect,
    make_critic,
    make_human_gate,
    make_planner,
    make_researcher,
    make_verifier,
    make_writer,
)
from .state import AgentState

logger = logging.getLogger(__name__)


def build_graph(
    model,
    retriever=None,
    checkpointer=None,
    max_revisions: int = 1,
    min_citation_coverage: float | None = None,
    enable_review: bool = False,
    enforce_citations: bool = True,
):
    """真实流水线。retriever 为空时 researcher 会如实说明「没有资料」。
    enforce_citations=False 仅用于消融实验：跳过覆盖率/编造引用的硬门槛。"""
    threshold = (
        settings.citation_min_coverage
        if min_citation_coverage is None
        else min_citation_coverage
    )

    g = StateGraph(AgentState)
    g.add_node("planner", make_planner(model))
    g.add_node("researcher", make_researcher(model, retriever))
    g.add_node("collect", make_collect())
    g.add_node("writer", make_writer(model))
    g.add_node("verifier", make_verifier(threshold))
    g.add_node("human_gate", make_human_gate(enable_review))
    g.add_node("critic", make_critic(model))

    def fan_out(state: AgentState):
        """把每个子问题变成一个独立的 Send 任务（数量运行期才确定）。"""
        return [Send("researcher", {"sub_question": sq}) for sq in state["sub_questions"]]

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", fan_out, ["researcher"])
    g.add_edge("researcher", "collect")
    g.add_edge("collect", "writer")
    g.add_edge("writer", "verifier")
    g.add_edge("verifier", "human_gate")
    g.add_edge("human_gate", "critic")

    def route_after_critic(state: AgentState) -> str:
        # human_approved 为 False 时（人工退回）无论 critic 怎么判都要重写
        ok = (
            state.get("verdict_passed")
            and state.get("human_approved", True) is not False
        )
        if enforce_citations:
            ok = (
                ok
                and state.get("citation_coverage", 1.0) >= threshold
                and not state.get("invalid_citations")
            )
        if ok or state.get("revisions", 0) > max_revisions:
            return END
        return "writer"

    g.add_conditional_edges("critic", route_after_critic, {"writer": "writer", END: END})
    return g.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# 离线桩节点（无 LLM、无检索器）——演示 + 拓扑冒烟测试
# ---------------------------------------------------------------------------

def _stub_planner(state: AgentState) -> dict:
    q = state["question"]
    return {"sub_questions": [f"What is {q}?", f"Why does {q} matter?"]}


def _stub_researcher(state: AgentState) -> dict:
    return {
        "findings": [
            {
                "sub_question": sq,
                "text": f"note about: {sq}",
                "sources": [{"n": 1, "id": "stub", "source": "stub.md", "text": "stub 资料"}],
            }
            for sq in state["sub_questions"]
        ]
    }


def _stub_writer(state: AgentState) -> dict:
    bullets = "\n".join(f"- {n}" for n in state.get("notes", []))
    report = f"# Draft report\n\nQuestion: {state['question']}\n\n{bullets}"
    if state.get("critique"):
        report += f"\n\n> Revision: addressed critique -> {state['critique']}"
        return {"report": report, "revised": True}
    return {"report": report}


def _stub_verifier(state: AgentState) -> dict:
    return {"citation_coverage": 1.0, "invalid_citations": [], "unsourced": []}


def _stub_critic(state: AgentState) -> dict:
    if state.get("revised"):
        return {}
    return {"critique": "cite a source for every claim", "revised": False}


def _stub_route(state: AgentState) -> str:
    return END if state.get("revised") else "writer"


def build_offline_graph(checkpointer=None):
    g = StateGraph(AgentState)
    g.add_node("planner", _stub_planner)
    g.add_node("researcher", _stub_researcher)
    g.add_node("collect", make_collect())
    g.add_node("writer", _stub_writer)
    g.add_node("verifier", _stub_verifier)
    g.add_node("critic", _stub_critic)
    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "collect")
    g.add_edge("collect", "writer")
    g.add_edge("writer", "verifier")
    g.add_edge("verifier", "critic")
    g.add_conditional_edges("critic", _stub_route, {"writer": "writer", END: END})
    return g.compile(checkpointer=checkpointer)


def main(question: str = "What is retrieval-augmented generation?") -> dict:
    """离线演示：python -m deepresearch.graph，不需要任何 API key。"""
    app = build_offline_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "demo"}}
    result = app.invoke({"question": question}, config=config)
    print(result["report"])
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
