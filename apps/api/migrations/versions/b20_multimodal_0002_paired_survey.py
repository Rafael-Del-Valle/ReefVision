"""Freeze paired reviewed acoustic and optical survey observations."""

import sqlalchemy as sa
from alembic import op

revision = "b20_multimodal_0002"
down_revision = "b20_appearance_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "multimodal_studies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column(
            "audio_report_id",
            sa.String(36),
            sa.ForeignKey("bioacoustic_reports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "role_revision_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_role_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("source_id_map_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "operation_id", name="uq_multimodal_project_operation"),
    )
    op.create_index("ix_multimodal_studies_project_id", "multimodal_studies", ["project_id"])


def downgrade() -> None:
    op.drop_table("multimodal_studies")
