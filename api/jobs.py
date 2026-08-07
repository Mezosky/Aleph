from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aleph.pipeline import PipelineResult, run_analysis


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class Job:
    id: str
    source: bytes | str
    title: str | None
    allow_network: bool
    state: str = "queued"
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    result: PipelineResult | None = None
    error: str | None = None

    def status(self) -> dict[str, Any]:
        phases = [] if self.result is None else [phase.to_dict() for phase in self.result.phases]
        return {
            "id": self.id,
            "state": self.state,
            "progress": 1 if self.state in {"complete", "failed"} else 0,
            "current_phase": None,
            "phases": phases,
            "error": self.error,
            "slug": self.result.slug if self.result else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, source: bytes | str, title: str | None, *, allow_network: bool) -> Job:
        job = Job(uuid.uuid4().hex, source, title, allow_network)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None:
            return
        job.state = "running"
        job.updated_at = now()
        try:
            job.result = run_analysis(
                job.source,
                title=job.title,
                allow_network=job.allow_network,
            )
            job.state = "complete"
        except Exception as exc:  # the status endpoint must preserve a failed job
            job.error = f"{type(exc).__name__}: {exc}"
            job.state = "failed"
        job.updated_at = now()


jobs = JobStore()
