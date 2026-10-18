"""API 测试：提交任务、轮询状态、404、健康检查（不触发真实 LLM）。"""

from fastapi.testclient import TestClient

from deepresearch import api


def _fake_run(question, thread_id="x", max_revisions=1):
    return {
        "question": question,
        "report": f"# {question}\n\n结论 [1]。",
        "metrics": {"llm_calls": 3, "total_tokens": 1200, "llm_seconds": 4.2},
        "citation_coverage": 0.85,
        "invalid_citations": [],
        "sources": [{"n": 1, "source": "a.md", "text": "x"}],
        "revisions": 1,
    }


class _FakeStore:
    def count(self):
        return 7


def test_submit_and_poll(monkeypatch):
    monkeypatch.setattr(api, "_run", _fake_run)
    client = TestClient(api.app)

    resp = client.post("/research", json={"question": "什么是 RAG？"})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] == "done"
    assert detail["report"].startswith("# 什么是 RAG？")
    assert detail["metrics"]["total_tokens"] == 1200
    assert detail["citation_coverage"] == 0.85


def test_unknown_run_returns_404():
    client = TestClient(api.app)
    assert client.get("/runs/does-not-exist").status_code == 404


def test_health_reports_indexed_chunks(monkeypatch):
    monkeypatch.setattr(api, "get_store", lambda: _FakeStore())
    client = TestClient(api.app)
    body = client.get("/health").json()
    assert body == {"status": "ok", "indexed_chunks": 7}
