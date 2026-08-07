"""Create append-only documents, snapshots, runs and artifacts.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_payload", sa.LargeBinary(), nullable=False),
        sa.Column("source_name", sa.Text()),
        sa.Column("source_url", sa.Text()),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_content_sha256", "documents", ["content_sha256"])

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("document_id", sa.String(32), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("supersedes_run_id", sa.String(32), sa.ForeignKey("analysis_runs.id")),
        sa.Column("source_snapshot_id", sa.String(32)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("allow_network", sa.Boolean(), nullable=False),
        sa.Column("model_provider", sa.String(80), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_revision", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_json", json_type),
        sa.Column("result_sha256", sa.String(64)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_analysis_runs_document_created", "analysis_runs", ["document_id", "created_at"]
    )
    op.create_index("ix_analysis_runs_state_created", "analysis_runs", ["state", "created_at"])

    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("final_url", sa.Text()),
        sa.Column("file_name", sa.Text()),
        sa.Column("media_type", sa.Text()),
        sa.Column("retrieval_method", sa.String(40), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("redirect_chain", json_type, nullable=False),
        sa.Column("etag", sa.Text()),
        sa.Column("last_modified", sa.Text()),
        sa.Column("response_headers", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "content_sha256", name="uq_snapshot_run_content"),
    )
    op.create_index("ix_source_snapshots_hash", "source_snapshots", ["content_sha256"])
    op.create_table(
        "analysis_artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "name", name="uq_artifact_run_name"),
    )
    op.create_index(
        "ix_analysis_artifacts_run_ordinal", "analysis_artifacts", ["run_id", "ordinal"]
    )


def downgrade() -> None:
    op.drop_table("analysis_artifacts")
    op.drop_table("source_snapshots")
    op.drop_table("analysis_runs")
    op.drop_table("documents")
