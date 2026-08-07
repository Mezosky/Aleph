from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from aleph import SCHEMA_VERSION, __version__
from aleph.core.config import get_config
from api.jobs import jobs

config = get_config()
app = FastAPI(title="Aleph API", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)


@app.get("/v1/health")
def health() -> dict[str, str]:
    database = "ok" if jobs.health() else "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "database": database,
    }


@app.post("/v1/analyses", status_code=status.HTTP_202_ACCEPTED)
async def submit(request: Request, background: BackgroundTasks) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    title: str | None = None
    source: bytes | str
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(400, "multipart request requires a file")
        source = await upload.read()
        title_value = form.get("title")
        title = str(title_value) if title_value else getattr(upload, "filename", None)
        allow_network = False
    else:
        try:
            payload: dict[str, Any] = await request.json()
        except Exception as exc:
            raise HTTPException(400, "request body must be JSON or multipart") from exc
        source = str(payload.get("url", "")).strip()
        title = str(payload["title"]).strip() if payload.get("title") else None
        if not source:
            raise HTTPException(400, "JSON request requires a url")
        allow_network = True
    job = jobs.create(source, title, allow_network=allow_network)
    background.add_task(jobs.run, job.id)
    return {
        "id": job.id,
        "state": job.state,
        "status_url": f"/v1/analyses/{job.id}/status",
    }


def _job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "analysis job not found")
    return job


@app.get("/v1/analyses/{job_id}/status")
def analysis_status(job_id: str):
    return _job(job_id).status()


@app.get("/v1/analyses/{job_id}")
def analysis_result(job_id: str):
    job = _job(job_id)
    if job.state == "failed":
        raise HTTPException(422, job.error or "analysis failed")
    if job.result is None:
        raise HTTPException(409, "analysis is not complete")
    return job.result


@app.get("/v1/analyses")
def list_analyses(limit: int = 100):
    """List durable runs newest-first, including superseded versions."""
    return {"analyses": [run.status() for run in jobs.list(limit=limit)]}


@app.get("/v1/documents/{document_id}/analyses")
def document_history(document_id: str):
    """Return the append-only analysis history for one stored source."""
    history = jobs.history(document_id)
    if not history:
        raise HTTPException(404, "document record not found")
    return {"document_record_id": document_id, "analyses": [run.status() for run in history]}


@app.post("/v1/analyses/{job_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
def rerun_analysis(job_id: str, background: BackgroundTasks):
    """Create a new version from the original immutable source snapshot input."""
    if jobs.get(job_id) is None:
        raise HTTPException(404, "analysis job not found")
    run = jobs.rerun(job_id)
    if run is None:
        raise HTTPException(404, "analysis job not found")
    background.add_task(jobs.run, run.id)
    return {
        "id": run.id,
        "state": run.state,
        "supersedes_run_id": job_id,
        "status_url": f"/v1/analyses/{run.id}/status",
    }
