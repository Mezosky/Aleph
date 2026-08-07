"""Add append-only live acquisition snapshots and news observations.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("sources_total", sa.Integer(), nullable=False),
        sa.Column("sources_checked", sa.Integer(), nullable=False),
        sa.Column("feed_snapshots", sa.Integer(), nullable=False),
        sa.Column("items_seen", sa.Integer(), nullable=False),
        sa.Column("items_new", sa.Integer(), nullable=False),
        sa.Column("relevant_items", sa.Integer(), nullable=False),
        sa.Column("article_snapshots", sa.Integer(), nullable=False),
        sa.Column("failures", json_type, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "retrieval_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("scrape_run_id", sa.String(32), sa.ForeignKey("scrape_runs.id"), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("resource_kind", sa.String(16), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.Text()),
        sa.Column("etag", sa.Text()),
        sa.Column("last_modified", sa.Text()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("url", "content_sha256", name="uq_retrieval_url_content"),
    )
    op.create_index(
        "ix_retrieval_snapshots_run_kind", "retrieval_snapshots", ["scrape_run_id", "resource_kind"]
    )
    op.create_index(
        "ix_retrieval_snapshots_source_fetched", "retrieval_snapshots", ["source_id", "fetched_at"]
    )
    op.create_table(
        "discovered_news",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "feed_snapshot_id",
            sa.String(32),
            sa.ForeignKey("retrieval_snapshots.id"),
            nullable=False,
        ),
        sa.Column("article_snapshot_id", sa.String(32), sa.ForeignKey("retrieval_snapshots.id")),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("matched_terms", json_type, nullable=False),
        sa.Column("raw_metadata", json_type, nullable=False),
    )
    op.create_index(
        "ix_discovered_news_source_published", "discovered_news", ["source_id", "published_at"]
    )
    op.create_index("ix_discovered_news_relevance", "discovered_news", ["relevance_score"])


def downgrade() -> None:
    op.drop_table("discovered_news")
    op.drop_table("retrieval_snapshots")
    op.drop_table("scrape_runs")
