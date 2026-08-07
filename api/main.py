from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from aleph import SCHEMA_VERSION, __version__
from api.jobs import jobs

app = FastAPI(title="Aleph API", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)


@app.get("/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "schema_version": SCHEMA_VERSION}


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
    return job.result.to_dict()
