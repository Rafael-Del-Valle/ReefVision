"""Retain native appearance scores and independent cross-recording decisions."""

import sqlalchemy as sa
from alembic import op

revision = "b20_appearance_0001"
down_revision = "b19_registration_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pose_appearance_studies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_id",
            sa.String(36),
            sa.ForeignKey("model_registrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reference_id",
            sa.String(36),
            sa.ForeignKey("reefpose_references.id", ondelete="RESTRICT"),
        ),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_id_map_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "operation_id", name="uq_appearance_study_op"),
    )
    op.create_index(
        "ix_pose_appearance_studies_project_id", "pose_appearance_studies", ["project_id"]
    )
    op.create_table(
        "pose_appearance_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "study_id",
            sa.String(36),
            sa.ForeignKey("pose_appearance_studies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_revision_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_role_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("role_slot", sa.String(20), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_id_map_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("study_id", "role_slot", name="uq_appearance_decision_slot"),
        sa.UniqueConstraint("study_id", "operation_id", name="uq_appearance_decision_op"),
    )
    op.create_index(
        "ix_pose_appearance_decisions_study_id", "pose_appearance_decisions", ["study_id"]
    )


def downgrade() -> None:
    op.drop_table("pose_appearance_decisions")
    op.drop_table("pose_appearance_studies")
