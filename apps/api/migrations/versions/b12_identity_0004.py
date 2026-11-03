"""Freeze project-owned image calibration evidence (unverified).

Revision ID: b12_identity_0004
Revises: b12_identity_0003

Track B remains isolated from the unmerged 1.1 migration lineage.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b12_identity_0004"
down_revision: str | None = "b12_identity_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecology_identity_calibration_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_evidence_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("calibration_json", sa.JSON(), nullable=False),
        sa.Column("calibration_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["annotation_evidence_id"],
            ["ecology_identity_annotation_evidence.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id",
            "annotation_evidence_id",
            name="uq_ecology_calibration_annotation_evidence",
        ),
    )
    op.create_index(
        "ix_ecology_calibration_evidence_project_image",
        "ecology_identity_calibration_evidence",
        ["project_id", "image_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecology_calibration_evidence_project_image",
        table_name="ecology_identity_calibration_evidence",
    )
    op.drop_table("ecology_identity_calibration_evidence")
