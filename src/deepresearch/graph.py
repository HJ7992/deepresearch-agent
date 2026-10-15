"""图构建器。

- build_graph(model)：真实流水线。模型是注入进来的，所以 CI 可以用「剧本
  假模型」完全离线地跑（见 tests/test_fake_graph.py）。
- build_offline_graph()：M0 的桩节点版本，拓扑与真图完全一致，不需要 LLM，
  用作演示和拓扑冒烟测试。

设计要点（面试话术）：修订循环必须封顶——max_revisions 表示「critic 否决后
允许的修订轮数」，否则一个永不满意的 critic 会让程序无限烧钱。
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import make_critic, make_planner, make_researcher, make_writer
from .state import AgentState

logger = logging.getLogger(__name__)


def build_graph(model, checkpointer=None, max_revisions: int = 1):
    """真实流水线：planner -> researcher -> writer -> critic，critic 可打回。"""
    g = StateGraph(AgentState)
    g.add_node("planner", make_planner(model))
    g.add_node("researcher", make_researcher(model))
    g.add_node("writer", make_writer(model))
    g.add_node("critic", make_critic(model))
    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "writer")
    g.add_edge("writer", "critic")

    def route_after_critic(state: AgentState) -> str:
        # max_revisions 计的是「修订轮数」：writer 最多跑 1 + max 次。
        # revisions 是 critic 已审查的次数，所以这里用 > 判断。
        if state.get("verdict_passed") or state.get("revisions", 0) > max_revisions:
            return END
        return "writer"

    g.add_conditional_edges("critic", route_after_critic, {"writer": "writer", END: END})
    return g.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# M0 离线桩节点（拓扑一致、无 LLM）——演示 + 拓扑冒烟测试
# ---------------------------------------------------------------------------

def _stub_planner(state: AgentState) -> dict:
    q = state["question"]
    return {"sub_questions": [f"What is {q}?", f"Why does {q} matter?"]}


def _stub_researcher(state: AgentState) -> dict:
    return {"notes": [f"note about: {sq}" for sq in state["sub_questions"]]}


def _stub_writer(state: AgentState) -> dict:
    bullets = "\n".join(f"- {n}" for n in state["notes"])
    report = f"# Draft report\n\nQuestion: {state['question']}\n\n{bullets}"
    if state.get("critique"):
        report += f"\n\n> Revision: addressed critique -> {state['critique']}"
        return {"report": report, "revised": True}
    return {"report": report}


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
    g.add_node("writer", _stub_writer)
    g.add_node("critic", _stub_critic)
    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "writer")
    g.add_edge("writer", "critic")
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
