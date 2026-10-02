"""Add skeleton analysis revision persistence.

Revision ID: 0033
Revises: 0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skeleton_analysis_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("analysis_series_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_analysis_id", sa.String(length=36), nullable=True),
        sa.Column("mask_annotation_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("mask_revision", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=30), nullable=False),
        sa.Column("algorithm", sa.String(length=60), nullable=False),
        sa.Column("algorithm_version", sa.String(length=40), nullable=False),
        sa.Column("terminal_spur_max_length_pixels", sa.Float(), nullable=False),
        sa.Column("input_mask_sha256", sa.String(length=64), nullable=False),
        sa.Column("calibration_sha256", sa.String(length=64), nullable=True),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("correction_json", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mask_annotation_id"],
            ["mask_annotations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_analysis_id"],
            ["skeleton_analysis_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "analysis_revision >= 1",
            name="ck_skeleton_analysis_revisions_revision",
        ),
        sa.CheckConstraint(
            "mask_revision >= 1",
            name="ck_skeleton_analysis_revisions_mask_revision",
        ),
        sa.CheckConstraint(
            "terminal_spur_max_length_pixels >= 0",
            name="ck_skeleton_analysis_revisions_spur_threshold",
        ),
        sa.UniqueConstraint(
            "analysis_series_id",
            "analysis_revision",
            name="uq_skeleton_analysis_series_revision",
        ),
    )
    op.create_index(
        "ix_skeleton_analysis_mask_revision",
        "skeleton_analysis_revisions",
        ["mask_annotation_id", "mask_revision", "created_at"],
    )
    op.create_index(
        "ix_skeleton_analysis_series_revision",
        "skeleton_analysis_revisions",
        ["analysis_series_id", "analysis_revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_skeleton_analysis_series_revision",
        table_name="skeleton_analysis_revisions",
    )
    op.drop_index(
        "ix_skeleton_analysis_mask_revision",
        table_name="skeleton_analysis_revisions",
    )
    op.drop_table("skeleton_analysis_revisions")
