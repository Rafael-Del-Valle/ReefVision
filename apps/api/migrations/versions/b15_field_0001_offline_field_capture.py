"""Add immutable offline field batches, originals, reconciliation and review.

Revision ID: b15_field_0001
Revises: b14_condition_0041
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b15_field_0001"
down_revision: str = "b14_condition_0041"
branch_labels: tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _id(name: str, *, primary: bool = False) -> sa.Column:
    return sa.Column(name, sa.String(36), primary_key=primary, nullable=False)


def _reference(name: str, target: str, *, primary: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.String(36),
        sa.ForeignKey(target, ondelete="CASCADE"),
        nullable=False,
        primary_key=primary,
    )


def upgrade() -> None:
    op.create_table(
        "field_capture_batches",
        _id("id", primary=True),
        _reference("project_id", "projects.id"),
        _id("origin_project_id"),
        _id("origin_batch_id"),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "manifest_sha256", name="uq_field_batch_project_manifest"
        ),
    )
    op.create_index(
        "ix_field_capture_batches_project",
        "field_capture_batches",
        ["project_id", "created_at", "id"],
    )
    op.create_table(
        "field_capture_observations",
        _id("id", primary=True),
        _reference("batch_id", "field_capture_batches.id"),
        _reference("project_id", "projects.id"),
        _id("source_observation_id"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("managed_path", sa.String(700), nullable=False),
        sa.Column("claim_key", sa.String(600)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("batch_id", "source_observation_id", name="uq_field_batch_observation"),
        sa.UniqueConstraint("batch_id", "ordinal", name="uq_field_batch_ordinal"),
    )
    op.create_index(
        "ix_field_observation_project_source",
        "field_capture_observations",
        ["project_id", "source_observation_id"],
    )
    op.create_index(
        "ix_field_observation_project_claim",
        "field_capture_observations",
        ["project_id", "claim_key"],
    )
    op.create_index(
        "ix_field_observation_project_media",
        "field_capture_observations",
        ["project_id", "kind", "sha256"],
    )
    op.create_table(
        "field_capture_reconciliations",
        _reference("batch_id", "field_capture_batches.id", primary=True),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "field_capture_reviews",
        _id("id", primary=True),
        _reference("batch_id", "field_capture_batches.id"),
        _reference("observation_id", "field_capture_observations.id"),
        _reference("against_observation_id", "field_capture_observations.id"),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "observation_id", "against_observation_id", name="uq_field_review_pair"
        ),
    )
    op.create_index(
        "ix_field_capture_reviews_batch", "field_capture_reviews", ["batch_id", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_table("field_capture_reviews")
    op.drop_table("field_capture_reconciliations")
    op.drop_table("field_capture_observations")
    op.drop_table("field_capture_batches")
