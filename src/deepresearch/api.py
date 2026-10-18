"""FastAPI 服务层 + 单页前端。

- GET  /                 单页界面（原生 HTML/JS，无构建链）
- POST /research         提交调研（可开启人工审核），立即返回 run_id
- GET  /runs/{id}        查询状态 / 报告 / 计量
- POST /runs/{id}/review 人工审核：批准或退回（HITL）
- GET  /health           健康检查 + 已索引块数

设计取舍（面试话术）：调研是几十秒的长任务，接口用「提交 + 轮询」而不是同步
阻塞；HITL 暂停时状态为 awaiting_review，前端渲染批准/退回按钮。任务表在进程
内字典里，真正的状态持久化由 checkpoint 负责（--resume 可跨进程恢复）。
"""

from __future__ import annotations

import datetime as dt
import logging
import pathlib
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .retriever import get_store
from .runner import resume as _resume
from .runner import run as _run

logger = logging.getLogger(__name__)

WEB_DIR = pathlib.Path(__file__).parent / "web"

app = FastAPI(title="DeepResearch Agent API", version="0.5.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# 进程内任务表：run_id -> 状态字典
_runs: dict[str, dict] = {}


class ResearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500, description="调研问题")
    review: bool = Field(default=False, description="是否开启人工审核（HITL）")


class ReviewDecision(BaseModel):
    approved: bool
    comment: str = ""


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """单页界面入口。"""
    return FileResponse(WEB_DIR / "index.html")


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
        "review": req.review,
        "paused": False,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "report": None,
        "metrics": None,
        "citation_coverage": None,
        "invalid_citations": [],
        "sources": 0,
        "revisions": 0,
        "error": None,
    }
    background.add_task(_execute, run_id, req.question, req.review)
    return {"run_id": run_id, "status": "queued", "status_url": f"/runs/{run_id}"}


def _apply_result(run_id: str, result: dict) -> None:
    """把一次图执行的结果写回任务表（暂停或完成都走这里）。"""
    paused = bool(result.get("paused"))
    _runs[run_id].update(
        status="awaiting_review" if paused else "done",
        paused=paused,
        report=result.get("report"),
        metrics=result.get("metrics"),
        citation_coverage=result.get("citation_coverage"),
        invalid_citations=result.get("invalid_citations", []),
        sources=len(result.get("sources", [])),
        revisions=result.get("revisions", 0),
    )


def _execute(run_id: str, question: str, review: bool) -> None:
    """后台执行一次调研，把结果写回任务表。"""
    _runs[run_id]["status"] = "running"
    try:
        _apply_result(run_id, _run(question, thread_id=run_id, review=review))
    except Exception as exc:  # 后台任务不能把异常抛给调用方，只能记录
        logger.exception("run %s 执行失败", run_id)
        _runs[run_id].update(status="failed", error=str(exc)[:300], paused=False)


@app.post("/runs/{run_id}/review", status_code=202)
def review(run_id: str, decision: ReviewDecision, background: BackgroundTasks) -> dict:
    """人工审核：批准或退回。退回意见会触发 writer 重写。"""
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    if not run.get("paused"):
        raise HTTPException(status_code=409, detail="当前任务不在等待审核")

    _runs[run_id].update(status="running", paused=False)
    background.add_task(
        _deliver_review,
        run_id,
        {"approved": decision.approved, "comment": decision.comment},
    )
    return {"run_id": run_id, "status": "running"}


def _deliver_review(run_id: str, decision: dict) -> None:
    """后台恢复被人工审核暂停的图。"""
    try:
        _apply_result(run_id, _resume(run_id, decision))
    except Exception as exc:
        logger.exception("run %s 恢复失败", run_id)
        _runs[run_id].update(status="failed", error=str(exc)[:300], paused=False)


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """查询任务状态与结果。"""
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="run 不存在")
    return _runs[run_id]
