"""Durable analysis-job orchestration.

The API process is only an executor. Queue state, source bytes, immutable source
snapshots and completed outputs all live in the database, so a restart cannot
erase an analysis and a re-run cannot overwrite an earlier result.
"""

from __future__ import annotations

import threading
from typing import Any

from aleph import SCHEMA_VERSION
from aleph.core.config import Config, get_config
from aleph.core.ids import stable_hash
from aleph.ingestion import load_source
from aleph.llm import get_provider
from aleph.pipeline import PIPELINE_VERSION, PROMPT_VERSION, run_analysis
from api.database import Database
from api.repository import AnalysisRepository, StoredRun


class JobStore:
    """Compatibility facade over the durable analysis repository."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        database: Database | None = None,
    ) -> None:
        self.config = config or get_config()
        self.database = database or Database(
            self.config.database_url.reveal(),
            auto_create=self.config.database_auto_create,
        )
        self.repository = AnalysisRepository(self.database)
        # Serialises get-or-create document insertion inside one process. The
        # database uniqueness constraint remains the cross-process authority.
        self._create_lock = threading.Lock()
        self._execution_slots = threading.BoundedSemaphore(max(1, self.config.max_concurrent_jobs))

    def _model_name(self) -> str:
        return (
            "aleph-deterministic-mock"
            if self.config.llm_provider.value == "mock"
            else self.config.qwen_model
        )

    def _model_revision(self) -> str:
        return "builtin" if self.config.llm_provider.value == "mock" else self.config.qwen_revision

    def _config_fingerprint(self) -> str:
        return stable_hash(
            self.config.llm_provider.value,
            self._model_name(),
            self._model_revision(),
            self.config.llm_temperature,
            self.config.seed,
            self.config.retrieval_mode.value,
            PIPELINE_VERSION,
            PROMPT_VERSION,
            SCHEMA_VERSION,
            length=64,
        )

    def create(self, source: bytes | str, title: str | None, *, allow_network: bool) -> StoredRun:
        with self._create_lock:
            return self.repository.create_run(
                source,
                title,
                allow_network=allow_network,
                model_provider=self.config.llm_provider.value,
                model_name=self._model_name(),
                model_revision=self._model_revision(),
                pipeline_version=PIPELINE_VERSION,
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                config_fingerprint=self._config_fingerprint(),
            )

    def rerun(self, run_id: str) -> StoredRun | None:
        with self._create_lock:
            return self.repository.rerun(
                run_id,
                model_provider=self.config.llm_provider.value,
                model_name=self._model_name(),
                model_revision=self._model_revision(),
                pipeline_version=PIPELINE_VERSION,
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                config_fingerprint=self._config_fingerprint(),
            )

    def get(self, run_id: str) -> StoredRun | None:
        return self.repository.get(run_id)

    def list(self, *, limit: int = 100) -> list[StoredRun]:
        return self.repository.list_runs(limit=limit)

    def history(self, document_id: str) -> list[StoredRun]:
        return self.repository.history(document_id)

    def run(self, run_id: str) -> None:
        with self._execution_slots:
            if not self.repository.claim(run_id):
                return
            run = self.repository.get(run_id)
            if run is None:
                return
            provider: Any | None = None
            try:
                fetched = (
                    self.repository.snapshot(run.source_snapshot_id)
                    if run.source_snapshot_id
                    else None
                )
                if fetched is None:
                    source: bytes | str = run.source
                    if run.source_kind == "text":
                        source = run.source_payload
                    fetched = load_source(
                        source,
                        allow_network=run.allow_network,
                        file_name=run.source_name,
                        config=self.config,
                    )
                    self.repository.record_snapshot(run_id, fetched)
                provider = get_provider(config=self.config)
                result = run_analysis(
                    fetched,
                    title=run.source_name,
                    allow_network=False,
                    provider=provider,
                )
                self.repository.complete(run_id, result.to_dict())
            except Exception as exc:  # status must preserve a failed run durably
                self.repository.fail(run_id, f"{type(exc).__name__}: {exc}")
            finally:
                if provider is not None:
                    close = getattr(provider, "close", None)
                    if callable(close):
                        close()

    def health(self) -> bool:
        return self.database.healthy()


jobs = JobStore()
