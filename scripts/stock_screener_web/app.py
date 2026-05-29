# -*- coding: utf-8 -*-
"""
Web UI for A-share stock screener.

Run:
  cd scripts/stock_screener_web
  pip install fastapi uvicorn pandas akshare
  python app.py
"""

from __future__ import annotations

import io
import sys
import threading
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from screener import (
    ScanConfig,
    ScanJob,
    ScanProgress,
    flatten_export_rows,
    run_scan,
)

STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="A股选股工具", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://jameschen0304.github.io",
        "http://localhost:8765",
        "http://127.0.0.1:8765",
    ],
    allow_origin_regex=r"https://.*\.github\.io",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_jobs: dict[str, ScanJob] = {}
_lock = threading.Lock()


class ScanRequest(BaseModel):
    pe_min: float = Field(5, ge=0)
    pe_max: float = Field(25, ge=0)
    periods: int = Field(6, ge=2, le=12)
    limit: int = Field(80, ge=0, le=6000)
    max_workers: int = Field(6, ge=1, le=16)
    apply_hard_rules: bool = Field(
        True, description="为 true 时仅保留通过硬性规则的股票"
    )
    min_current_ratio: float = Field(1.0, ge=0)
    revenue_growth_years: int = Field(3, ge=2, le=5)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.post("/api/scan/start")
def start_scan(req: ScanRequest) -> dict:
    if req.pe_min > req.pe_max:
        raise HTTPException(400, "市盈率下限不能大于上限")

    job_id = uuid.uuid4().hex[:12]
    cfg = ScanConfig(
        pe_min=req.pe_min,
        pe_max=req.pe_max,
        periods=req.periods,
        limit=req.limit,
        max_workers=req.max_workers,
        apply_hard_rules=req.apply_hard_rules,
        min_current_ratio=req.min_current_ratio,
        revenue_growth_years=req.revenue_growth_years,
    )
    job = ScanJob(config=cfg)

    with _lock:
        _jobs[job_id] = job

    def _run() -> None:
        run_scan(job)

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/scan/{job_id}/status")
def scan_status(job_id: str) -> dict:
    job = _get_job(job_id)
    p: ScanProgress = job.progress
    return {
        "status": p.status,
        "total": p.total,
        "done": p.done,
        "passed": p.passed,
        "message": p.message,
        "error": p.error,
        "started_at": p.started_at,
        "finished_at": p.finished_at,
        "percent": round(100 * p.done / p.total, 1) if p.total else 0,
    }


@app.get("/api/scan/{job_id}/results")
def scan_results(job_id: str) -> dict:
    job = _get_job(job_id)
    if job.progress.status not in ("done", "running"):
        if job.progress.status == "error":
            raise HTTPException(500, job.progress.error or "扫描失败")
    return {
        "status": job.progress.status,
        "summary": job.summary_rows,
        "count": len(job.results),
        "details": job.results,
    }


@app.get("/api/scan/{job_id}/export")
def export_csv(job_id: str) -> StreamingResponse:
    job = _get_job(job_id)
    if not job.results:
        raise HTTPException(404, "暂无可导出数据")
    df = flatten_export_rows(job.results)
    buf = io.StringIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)
    filename = f"screener_{job_id}.csv"
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _get_job(job_id: str) -> ScanJob:
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在或已过期")
    return job


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
    )
