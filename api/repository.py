"""Append-only repository for documents and analysis runs."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from aleph.core.enums import RetrievalMethod
from aleph.ingestion import FetchedDocument, classify_source
from api.database import (
    AnalysisArtifactRow,
    AnalysisRunRow,
    Database,
    DocumentRow,
    SourceSnapshotRow,
    utcnow,
)

_PROVENANCE_HEADERS = frozenset(
    {
        "cache-control",
        "content-disposition",
        "content-length",
        "content-type",
        "date",
        "digest",
        "etag",
        "last-modified",
    }
)


def _id() -> str:
    return uuid.uuid4().hex


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class StoredRun:
    id: str
    document_id: str
    supersedes_run_id: str | None
    source_snapshot_id: str | None
    source_kind: str
    source_payload: bytes
    source_name: str | None
    source_url: str | None
    allow_network: bool
    state: str
    model_provider: str
    model_name: str
    model_revision: str
    pipeline_version: str
    prompt_version: str
    schema_version: str
    config_fingerprint: str
    result: dict[str, Any] | None
    result_sha256: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime

    @property
    def source(self) -> bytes | str:
        if self.source_kind == "bytes":
            return self.source_payload
        return self.source_payload.decode("utf-8")

    def status(self) -> dict[str, Any]:
        phases = [] if self.result is None else list(self.result.get("phases", []))
        complete_phases = sum(1 for phase in phases if phase.get("state") == "complete")
        return {
            "id": self.id,
            "document_record_id": self.document_id,
            "supersedes_run_id": self.supersedes_run_id,
            "state": self.state,
            "progress": 1.0 if self.state in {"complete", "failed"} else 0.0,
            "completed_phases": complete_phases,
            "current_phase": None,
            "phases": phases,
            "error": self.error,
            "slug": self.result.get("document", {}).get("identity", {}).get("slug")
            if self.result
            else None,
            "model": {
                "provider": self.model_provider,
                "name": self.model_name,
                "revision": self.model_revision,
            },
            "pipeline_version": self.pipeline_version,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "result_sha256": self.result_sha256,
            "created_at": _timestamp(self.created_at),
            "started_at": _timestamp(self.started_at),
            "completed_at": _timestamp(self.completed_at),
            "updated_at": _timestamp(self.updated_at),
        }


class AnalysisRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_run(
        self,
        source: bytes | str,
        title: str | None,
        *,
        allow_network: bool,
        model_provider: str,
        model_name: str,
        model_revision: str,
        pipeline_version: str,
        prompt_version: str,
        schema_version: str,
        config_fingerprint: str,
        supersedes_run_id: str | None = None,
    ) -> StoredRun:
        kind = classify_source(source)
        if kind == "path":
            payload = str(source).encode("utf-8")
        elif kind == "bytes":
            payload = bytes(source)
        else:
            payload = str(source).encode("utf-8")
        source_fingerprint = _sha256(kind.encode() + b"\0" + payload)
        with self.database.sessions.begin() as session:
            document = session.scalar(
                select(DocumentRow).where(DocumentRow.source_fingerprint == source_fingerprint)
            )
            if document is None:
                document = DocumentRow(
                    id=_id(),
                    source_fingerprint=source_fingerprint,
                    source_kind=kind,
                    source_payload=payload,
                    source_name=title,
                    source_url=payload.decode("utf-8") if kind == "url" else None,
                    content_sha256=_sha256(payload) if kind == "bytes" else None,
                )
                session.add(document)
                session.flush()
            run = AnalysisRunRow(
                id=_id(),
                document_id=document.id,
                supersedes_run_id=supersedes_run_id,
                state="queued",
                allow_network=allow_network,
                model_provider=model_provider,
                model_name=model_name,
                model_revision=model_revision,
                pipeline_version=pipeline_version,
                prompt_version=prompt_version,
                schema_version=schema_version,
                config_fingerprint=config_fingerprint,
            )
            session.add(run)
            session.flush()
            return self._stored(run, document)

    def rerun(
        self,
        run_id: str,
        *,
        model_provider: str,
        model_name: str,
        model_revision: str,
        pipeline_version: str,
        prompt_version: str,
        schema_version: str,
        config_fingerprint: str,
    ) -> StoredRun | None:
        with self.database.sessions.begin() as session:
            original = session.get(AnalysisRunRow, run_id)
            if original is None:
                return None
            document = session.get(DocumentRow, original.document_id)
            if document is None:
                return None
            run = AnalysisRunRow(
                id=_id(),
                document_id=original.document_id,
                supersedes_run_id=original.id,
                # Re-analysis is against the exact original bytes. A deliberate
                # refresh of a URL is a new submission and gets a new snapshot.
                source_snapshot_id=original.source_snapshot_id,
                state="queued",
                allow_network=False if original.source_snapshot_id else original.allow_network,
                model_provider=model_provider,
                model_name=model_name,
                model_revision=model_revision,
                pipeline_version=pipeline_version,
                prompt_version=prompt_version,
                schema_version=schema_version,
                config_fingerprint=config_fingerprint,
            )
            session.add(run)
            session.flush()
            return self._stored(run, document)

    def get(self, run_id: str) -> StoredRun | None:
        with self.database.sessions() as session:
            row = session.execute(
                select(AnalysisRunRow, DocumentRow)
                .join(DocumentRow, DocumentRow.id == AnalysisRunRow.document_id)
                .where(AnalysisRunRow.id == run_id)
            ).one_or_none()
            return None if row is None else self._stored(*row)

    def list_runs(self, *, limit: int = 100) -> list[StoredRun]:
        bounded = max(1, min(limit, 500))
        with self.database.sessions() as session:
            rows = session.execute(
                select(AnalysisRunRow, DocumentRow)
                .join(DocumentRow, DocumentRow.id == AnalysisRunRow.document_id)
                .order_by(AnalysisRunRow.created_at.desc())
                .limit(bounded)
            ).all()
            return [self._stored(run, document) for run, document in rows]

    def history(self, document_id: str) -> list[StoredRun]:
        with self.database.sessions() as session:
            rows = session.execute(
                select(AnalysisRunRow, DocumentRow)
                .join(DocumentRow, DocumentRow.id == AnalysisRunRow.document_id)
                .where(AnalysisRunRow.document_id == document_id)
                .order_by(AnalysisRunRow.created_at.asc())
            ).all()
            return [self._stored(run, document) for run, document in rows]

    def claim(self, run_id: str) -> bool:
        with self.database.sessions.begin() as session:
            result = session.execute(
                update(AnalysisRunRow)
                .where(AnalysisRunRow.id == run_id, AnalysisRunRow.state == "queued")
                .values(state="running", started_at=utcnow(), updated_at=utcnow())
            )
            return result.rowcount == 1

    def record_snapshot(self, run_id: str, fetched: FetchedDocument) -> str:
        snapshot_id = _id()
        try:
            retrieved_at = datetime.fromisoformat(fetched.retrieved_at.replace("Z", "+00:00"))
        except ValueError:
            retrieved_at = utcnow()
        with self.database.sessions.begin() as session:
            run = session.get(AnalysisRunRow, run_id)
            if run is None:
                raise KeyError(f"analysis run {run_id!r} not found")
            snapshot = SourceSnapshotRow(
                id=snapshot_id,
                run_id=run_id,
                content_sha256=fetched.sha256,
                content=fetched.content,
                size_bytes=fetched.size_bytes,
                url=fetched.url,
                final_url=fetched.final_url,
                file_name=fetched.file_name,
                media_type=fetched.media_type,
                retrieval_method=str(fetched.retrieval_method.value),
                retrieved_at=retrieved_at,
                status_code=fetched.status_code,
                redirect_chain=list(fetched.redirect_chain),
                etag=fetched.etag,
                last_modified=fetched.last_modified,
                # Authentication, cookies and arbitrary server metadata have no
                # evidentiary value and must never be copied into the audit DB.
                response_headers={
                    key.lower(): value
                    for key, value in fetched.headers.items()
                    if key.lower() in _PROVENANCE_HEADERS
                },
            )
            session.add(snapshot)
            run.source_snapshot_id = snapshot_id
            run.updated_at = utcnow()
            document = session.get(DocumentRow, run.document_id)
            if document is not None:
                document.content_sha256 = fetched.sha256
        return snapshot_id

    def snapshot(self, snapshot_id: str) -> FetchedDocument | None:
        with self.database.sessions() as session:
            row = session.get(SourceSnapshotRow, snapshot_id)
            if row is None:
                return None
            retrieved_at = _as_utc(row.retrieved_at).isoformat().replace("+00:00", "Z")
            return FetchedDocument(
                content=row.content,
                sha256=row.content_sha256,
                size_bytes=row.size_bytes,
                retrieval_method=RetrievalMethod(row.retrieval_method),
                retrieved_at=retrieved_at,
                url=row.url,
                final_url=row.final_url,
                file_name=row.file_name,
                media_type=row.media_type,
                status_code=row.status_code,
                redirect_chain=tuple(row.redirect_chain),
                etag=row.etag,
                last_modified=row.last_modified,
                from_cache=True,
                headers=dict(row.response_headers),
            )

    def complete(self, run_id: str, result: dict[str, Any]) -> None:
        rendered = _canonical(result)
        artifacts = [
            ("document", result.get("document", {})),
            ("propositions", result.get("propositions", {})),
            ("topic_graph", result.get("topic_graph", {})),
            ("search_vocabulary", result.get("search_vocabulary", {})),
            ("readiness", result.get("readiness", {})),
            ("phases", result.get("phases", [])),
        ]
        with self.database.sessions.begin() as session:
            run = session.get(AnalysisRunRow, run_id)
            if run is None:
                raise KeyError(f"analysis run {run_id!r} not found")
            if run.state == "complete":
                raise ValueError("completed analysis runs are immutable")
            now = utcnow()
            run.state = "complete"
            run.result_json = result
            run.result_sha256 = _sha256(rendered)
            run.error = None
            run.completed_at = now
            run.updated_at = now
            for ordinal, (name, payload) in enumerate(artifacts):
                session.add(
                    AnalysisArtifactRow(
                        id=_id(),
                        run_id=run_id,
                        name=name,
                        ordinal=ordinal,
                        payload=payload,
                        payload_sha256=_sha256(_canonical(payload)),
                    )
                )

    def fail(self, run_id: str, error: str) -> None:
        with self.database.sessions.begin() as session:
            run = session.get(AnalysisRunRow, run_id)
            if run is None or run.state == "complete":
                return
            now = utcnow()
            run.state = "failed"
            run.error = error[:4000]
            run.completed_at = now
            run.updated_at = now

    @staticmethod
    def _stored(run: AnalysisRunRow, document: DocumentRow) -> StoredRun:
        return StoredRun(
            id=run.id,
            document_id=run.document_id,
            supersedes_run_id=run.supersedes_run_id,
            source_snapshot_id=run.source_snapshot_id,
            source_kind=document.source_kind,
            source_payload=document.source_payload,
            source_name=document.source_name,
            source_url=document.source_url,
            allow_network=run.allow_network,
            state=run.state,
            model_provider=run.model_provider,
            model_name=run.model_name,
            model_revision=run.model_revision,
            pipeline_version=run.pipeline_version,
            prompt_version=run.prompt_version,
            schema_version=run.schema_version,
            config_fingerprint=run.config_fingerprint,
            result=run.result_json,
            result_sha256=run.result_sha256,
            error=run.error,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            updated_at=run.updated_at,
        )
