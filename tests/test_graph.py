from langgraph.checkpoint.memory import InMemorySaver

from deepresearch.graph import build_graph


def test_hello_world_runs_offline():
    app = build_graph()
    out = app.invoke({"question": "What is RAG?"})
    assert out["report"].startswith("# Draft report")
    assert len(out["sub_questions"]) == 2
    assert len(out["notes"]) == 2


def test_revision_loop_runs_exactly_once():
    app = build_graph()
    out = app.invoke({"question": "What is RAG?"})
    assert out["report"].count("Revision") == 1
    assert out["revised"] is True


def test_checkpoint_state_is_persisted():
    app = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}
    app.invoke({"question": "What is RAG?"}, config)
    snapshot = app.get_state(config)
    assert snapshot.values["report"]
    assert snapshot.values["revised"] is True
