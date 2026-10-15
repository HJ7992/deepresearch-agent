"""M0 hello-world: planner -> researcher -> writer -> critic graph.

Runs fully offline (no LLM calls) so CI and local setup can be verified before
any API key exists. Real model nodes replace these stubs in M1. The critic
loop demonstrates conditional edges and exactly-one revision semantics.
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .state import AgentState

logger = logging.getLogger(__name__)


def planner(state: AgentState) -> dict:
    q = state["question"]
    sub_questions = [f"What is {q}?", f"Why does {q} matter?"]
    logger.info("planner: %d sub-questions", len(sub_questions))
    return {"sub_questions": sub_questions}


def researcher(state: AgentState) -> dict:
    return {"notes": [f"note about: {sq}" for sq in state["sub_questions"]]}


def writer(state: AgentState) -> dict:
    critique = state.get("critique")
    bullets = "\n".join(f"- {n}" for n in state["notes"])
    report = f"# Draft report\n\nQuestion: {state['question']}\n\n{bullets}"
    out: dict = {"report": report}
    if critique:
        report += f"\n\n> Revision: addressed critique -> {critique}"
        out = {"report": report, "revised": True}
    return out


def critic(state: AgentState) -> dict:
    if state.get("revised"):
        return {}
    return {"critique": "cite a source for every claim", "revised": False}


def route_after_critic(state: AgentState) -> str:
    return END if state.get("revised") else "writer"


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)
    g.add_node("planner", planner)
    g.add_node("researcher", researcher)
    g.add_node("writer", writer)
    g.add_node("critic", critic)
    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "writer")
    g.add_edge("writer", "critic")
    g.add_conditional_edges("critic", route_after_critic, {"writer": "writer", END: END})
    return g.compile(checkpointer=checkpointer)


def main(question: str = "What is retrieval-augmented generation?") -> dict:
    app = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "demo"}}
    result = app.invoke({"question": question}, config=config)
    print(result["report"])
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
