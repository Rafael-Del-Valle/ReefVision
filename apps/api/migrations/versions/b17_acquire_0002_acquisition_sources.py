"""Preserve configured local sources and bind each acquisition to immutable field media."""

import sqlalchemy as sa
from alembic import op

revision = "b17_acquire_0002"
down_revision = "b17_workflows_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("local_consent_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cursor >= 0 AND revision >= 1", name="ck_acquisition_source_cursor"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_acquisition_sources_project",
        "acquisition_sources",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "acquisition_captures",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("capture_key", sa.String(length=200), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("field_batch_id", sa.String(length=36), nullable=False),
        sa.Column("field_observation_id", sa.String(length=36), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("receipt_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_acquisition_capture_ordinal"),
        sa.ForeignKeyConstraint(
            ["field_batch_id"], ["field_capture_batches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["field_observation_id"], ["field_capture_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["acquisition_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "capture_key", name="uq_acquisition_capture_request"),
        sa.UniqueConstraint("source_id", "ordinal", name="uq_acquisition_capture_ordinal"),
    )
    op.create_index(
        "ix_acquisition_captures_project",
        "acquisition_captures",
        ["project_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("acquisition_captures")
    op.drop_table("acquisition_sources")
