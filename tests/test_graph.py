"""离线桩图（无 LLM）的基础行为测试：拓扑、修订循环、checkpoint。"""

from langgraph.checkpoint.memory import InMemorySaver

from deepresearch.graph import build_offline_graph


def test_offline_graph_runs():
    """离线图能跑通：报告生成、子问题与笔记齐全。"""
    app = build_offline_graph()
    out = app.invoke({"question": "What is RAG?"})
    assert out["report"].startswith("# Draft report")
    assert len(out["sub_questions"]) == 2
    assert len(out["notes"]) == 2


def test_revision_loop_runs_exactly_once():
    """桩 critic 否决一次、修订一次后通过——修订循环恰好跑一轮。"""
    app = build_offline_graph()
    out = app.invoke({"question": "What is RAG?"})
    assert out["report"].count("Revision") == 1
    assert out["revised"] is True


def test_checkpoint_state_is_persisted():
    """跑完后 checkpoint 里能取到完整状态（断点恢复的基础）。"""
    app = build_offline_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}
    app.invoke({"question": "What is RAG?"}, config)
    snapshot = app.get_state(config)
    assert snapshot.values["report"]
    assert snapshot.values["revised"] is True
