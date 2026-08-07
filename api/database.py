"""Durable relational state for Aleph analysis runs.

The JSON contract remains the public product, but it is no longer the storage
model. Documents, immutable source snapshots, append-only runs and phase
artifacts are separate rows so a new analysis can never overwrite the evidence
or output of an older one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

JSON_VALUE = JSON().with_variant(JSONB(), "postgresql")
DATABASE_REVISION = "0002"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AnalysisRunRow(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    supersedes_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=True
    )
    source_snapshot_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    allow_network: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_revision: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSON_VALUE)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_analysis_runs_document_created", "document_id", "created_at"),
        Index("ix_analysis_runs_state_created", "state", "created_at"),
    )


class SourceSnapshotRow(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(Text)
    retrieval_method: Mapped[str] = mapped_column(String(40), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    redirect_chain: Mapped[list] = mapped_column(JSON_VALUE, default=list, nullable=False)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    response_headers: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "content_sha256", name="uq_snapshot_run_content"),
        Index("ix_source_snapshots_hash", "content_sha256"),
    )


class AnalysisArtifactRow(Base):
    __tablename__ = "analysis_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict | list] = mapped_column(JSON_VALUE, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "name", name="uq_artifact_run_name"),
        Index("ix_analysis_artifacts_run_ordinal", "run_id", "ordinal"),
    )


class ScrapeRunRow(Base):
    """One explicit live-retrieval invocation and its continuously updated counters."""

    __tablename__ = "scrape_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    sources_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sources_checked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feed_snapshots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relevant_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    article_snapshots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failures: Mapped[list] = mapped_column(JSON_VALUE, default=list, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class RetrievalSnapshotRow(Base):
    """Immutable exact bytes acquired from a feed, sitemap, robots file or article."""

    __tablename__ = "retrieval_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scrape_run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("url", "content_sha256", name="uq_retrieval_url_content"),
        Index("ix_retrieval_snapshots_run_kind", "scrape_run_id", "resource_kind"),
        Index("ix_retrieval_snapshots_source_fetched", "source_id", "fetched_at"),
    )


class DiscoveredNewsRow(Base):
    """Deduplicated feed item; observation timestamps accumulate across scrape runs."""

    __tablename__ = "discovered_news"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feed_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("retrieval_snapshots.id"), nullable=False
    )
    article_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("retrieval_snapshots.id"))
    relevance_score: Mapped[float] = mapped_column(nullable=False)
    matched_terms: Mapped[list] = mapped_column(JSON_VALUE, default=list, nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSON_VALUE, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_discovered_news_source_published", "source_id", "published_at"),
        Index("ix_discovered_news_relevance", "relevance_score"),
    )


class Database:
    """Own the SQLAlchemy engine and short-lived session factory."""

    def __init__(self, url: str, *, auto_create: bool = True) -> None:
        if not url:
            raise ValueError("database URL must not be empty")
        engine_options: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            engine_options["connect_args"] = {"check_same_thread": False}
            if url in {"sqlite://", "sqlite:///:memory:"}:
                engine_options["poolclass"] = StaticPool
            elif url.startswith("sqlite:///"):
                path = Path(url.removeprefix("sqlite:///"))
                if str(path) != ":memory:":
                    path.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, **engine_options)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if auto_create:
            tables = set(inspect(self.engine).get_table_names())
            if "alembic_version" not in tables:
                Base.metadata.create_all(self.engine)
                # create_all is the zero-friction SQLite path. Stamp that
                # materialised head so a later Alembic migration can advance it
                # instead of trying to recreate the baseline tables. Once a DB
                # is versioned, only Alembic may change its shape.
                with self.engine.begin() as connection:
                    connection.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS alembic_version "
                            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                        )
                    )
                    connection.execute(
                        text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                        {"revision": DATABASE_REVISION},
                    )

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def healthy(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:  # health reporting must not crash the health endpoint
            return False

    def dispose(self) -> None:
        self.engine.dispose()
