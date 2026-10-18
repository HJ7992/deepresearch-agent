"""FastAPI 服务层。

- POST /research     提交调研任务，立即返回 run_id（后台执行）
- GET  /runs/{id}    查询状态/报告/计量
- GET  /health       健康检查 + 已索引块数

设计取舍（面试话术）：调研是长任务（几十秒），所以接口是「提交 + 轮询」，
不是同步阻塞；状态先放进程内字典，M3 会随 checkpoint 一起落 Postgres。
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .retriever import get_store
from .runner import run as _run

logger = logging.getLogger(__name__)

app = FastAPI(title="DeepResearch Agent API", version="0.2.0")

# 进程内任务表：run_id -> 状态字典
_runs: dict[str, dict] = {}


class ResearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500, description="调研问题")


@app.get("/health")
def health() -> dict:
    """健康检查：数据库里有多少块可检索。"""
    try:
        return {"status": "ok", "indexed_chunks": get_store().count()}
    except Exception as exc:  # noqa: BLE001 — 健康检查不能因向量库异常而 500
        return {"status": "degraded", "error": str(exc)[:200]}


@app.post("/research", status_code=202)
def submit(req: ResearchRequest, background: BackgroundTasks) -> dict:
    """提交调研任务：立刻返回 run_id，后台跑图。"""
    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = {
        "run_id": run_id,
        "status": "queued",
        "question": req.question,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "report": None,
        "metrics": None,
        "citation_coverage": None,
        "sources": 0,
        "revisions": 0,
        "error": None,
    }
    background.add_task(_execute, run_id, req.question)
    return {"run_id": run_id, "status": "queued", "status_url": f"/runs/{run_id}"}


def _execute(run_id: str, question: str) -> None:
    """后台执行一次调研，把结果写回任务表。"""
    _runs[run_id]["status"] = "running"
    try:
        result = _run(question, thread_id=run_id)
        _runs[run_id].update(
            status="done",
            report=result.get("report"),
            metrics=result.get("metrics"),
            citation_coverage=result.get("citation_coverage"),
            sources=len(result.get("sources", [])),
            revisions=result.get("revisions", 0),
        )
    except Exception as exc:  # 后台任务不能把异常抛给调用方，只能记录
        logger.exception("run %s 执行失败", run_id)
        _runs[run_id].update(status="failed", error=str(exc)[:300])


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """查询任务状态与结果。"""
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="run 不存在")
    return _runs[run_id]
