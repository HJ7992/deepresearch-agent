"""API 测试：提交任务、轮询状态、404、健康检查（不触发真实 LLM）。"""

from fastapi.testclient import TestClient

from deepresearch import api


def _fake_run(question, thread_id="x", max_revisions=1, review=False, mode="full"):
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


def _fake_paused(question, thread_id="x", max_revisions=1, review=False, mode="full"):
    """模拟开启了 HITL 的调研：跑到人工门暂停。"""
    return {
        "question": question,
        "report": "# 待审核 [1]",
        "paused": True,
        "citation_coverage": 0.8,
        "invalid_citations": [],
        "sources": [{"n": 1, "source": "a.md", "text": "x"}],
        "revisions": 1,
        "metrics": {"llm_calls": 5, "total_tokens": 9000},
    }


def _fake_resume(thread_id, decision, max_revisions=1):
    approved = bool(decision.get("approved"))
    return {
        "question": "q",
        "report": "# 终稿 [1]" if approved else "# 退回后重写 [1]",
        "paused": False,
        "citation_coverage": 0.9,
        "invalid_citations": [],
        "sources": [{"n": 1, "source": "a.md", "text": "x"}],
        "revisions": 2,
        "metrics": {"llm_calls": 1, "total_tokens": 1200},
    }


def test_review_approve_flow(monkeypatch):
    """开启 review 的调研：先 awaiting_review，批准后 done。"""
    monkeypatch.setattr(api, "_run", _fake_paused)
    monkeypatch.setattr(api, "_resume", _fake_resume)
    client = TestClient(api.app)

    submitted = client.post("/research", json={"question": "什么是 RAG？", "review": True})
    assert submitted.status_code == 202
    run_id = submitted.json()["run_id"]

    waiting = client.get(f"/runs/{run_id}").json()
    assert waiting["status"] == "awaiting_review"
    assert waiting["paused"] is True
    assert waiting["report"].startswith("# 待审核")

    reviewed = client.post(f"/runs/{run_id}/review", json={"approved": True, "comment": ""})
    assert reviewed.status_code == 202

    done = client.get(f"/runs/{run_id}").json()
    assert done["status"] == "done"
    assert done["report"].startswith("# 终稿")


def test_review_conflict_when_not_paused(monkeypatch):
    """已完成/未暂停的任务不能再提交审核（409）。"""
    monkeypatch.setattr(
        api,
        "_run",
        lambda *a, **k: {
            "question": "q",
            "report": "# x",
            "paused": False,
            "metrics": {},
            "citation_coverage": 1.0,
            "invalid_citations": [],
            "sources": [],
            "revisions": 1,
        },
    )
    client = TestClient(api.app)
    run_id = client.post("/research", json={"question": "什么是 RAG？"}).json()["run_id"]
    assert client.get(f"/runs/{run_id}").json()["status"] == "done"

    resp = client.post(f"/runs/{run_id}/review", json={"approved": True})
    assert resp.status_code == 409


def test_index_page_served():
    """根路径返回单页界面。"""
    client = TestClient(api.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "DeepResearch" in resp.text
