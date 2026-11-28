"""reviewed coral and ecological evidence

Revision ID: b12_integrated_0002
Revises: b12_integrated_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b12_integrated_0002"
down_revision: str | None = "b12_integrated_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecology_analysis_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("source_id_map_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('growth','abundance')", name="ck_ecology_analysis_kind"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["ecology_analysis_records.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ecology_analysis_project_created",
        "ecology_analysis_records",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ecology_analysis_supersedes",
        "ecology_analysis_records",
        ["supersedes_id"],
        unique=False,
    )
    op.create_table(
        "coral_graph_revisions",
        sa.Column("graph_id", sa.String(length=36), nullable=False),
        sa.Column("identity_revision_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("decision", sa.String(length=12), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_id_map_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["skeleton_analysis_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["identity_revision_id"], ["ecology_identity_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["coral_graph_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_id", "revision", name="uq_coral_graph_revision"),
    )
    op.create_index(
        op.f("ix_coral_graph_revisions_analysis_id"),
        "coral_graph_revisions",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coral_graph_revisions_graph_id"),
        "coral_graph_revisions",
        ["graph_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coral_graph_revisions_project_id"),
        "coral_graph_revisions",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "coral_branch_correspondence_revisions",
        sa.Column("correspondence_id", sa.String(length=36), nullable=False),
        sa.Column("earlier_graph_revision_id", sa.String(length=36), nullable=False),
        sa.Column("later_graph_revision_id", sa.String(length=36), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_id_map_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["earlier_graph_revision_id"], ["coral_graph_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["later_graph_revision_id"], ["coral_graph_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["coral_branch_correspondence_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "correspondence_id", "revision", name="uq_coral_correspondence_revision"
        ),
    )
    op.create_index(
        op.f("ix_coral_branch_correspondence_revisions_correspondence_id"),
        "coral_branch_correspondence_revisions",
        ["correspondence_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coral_branch_correspondence_revisions_project_id"),
        "coral_branch_correspondence_revisions",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "ecology_pose_link_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("link_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("organism_revision_id", sa.String(length=36), nullable=False),
        sa.Column("association_run_id", sa.String(length=36), nullable=False),
        sa.Column("animal_identity_id", sa.String(length=36), nullable=False),
        sa.Column("frame_start", sa.Integer(), nullable=False),
        sa.Column("frame_end", sa.Integer(), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('link', 'correct', 'unlink')", name="ck_ecology_pose_link_action"
        ),
        sa.CheckConstraint(
            "frame_start >= 0 AND frame_end >= frame_start", name="ck_ecology_pose_link_frames"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_ecology_pose_link_revision"),
        sa.ForeignKeyConstraint(
            ["animal_identity_id"], ["pose_animal_identities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["association_run_id"], ["pose_identity_association_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["organism_revision_id"], ["ecology_identity_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["ecology_pose_link_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("link_id", "revision", name="uq_ecology_pose_link_revision"),
    )
    op.create_index(
        "ix_ecology_pose_link_project",
        "ecology_pose_link_revisions",
        ["project_id", "link_id", "revision"],
        unique=False,
    )
    op.create_table(
        "coral_growth_records",
        sa.Column("correspondence_revision_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_id_map_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["correspondence_revision_id"],
            ["coral_branch_correspondence_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_coral_growth_records_correspondence_revision_id"),
        "coral_growth_records",
        ["correspondence_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coral_growth_records_project_id"),
        "coral_growth_records",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_coral_growth_records_project_id"), table_name="coral_growth_records")
    op.drop_index(
        op.f("ix_coral_growth_records_correspondence_revision_id"),
        table_name="coral_growth_records",
    )
    op.drop_table("coral_growth_records")
    op.drop_index("ix_ecology_pose_link_project", table_name="ecology_pose_link_revisions")
    op.drop_table("ecology_pose_link_revisions")
    op.drop_index(
        op.f("ix_coral_branch_correspondence_revisions_project_id"),
        table_name="coral_branch_correspondence_revisions",
    )
    op.drop_index(
        op.f("ix_coral_branch_correspondence_revisions_correspondence_id"),
        table_name="coral_branch_correspondence_revisions",
    )
    op.drop_table("coral_branch_correspondence_revisions")
    op.drop_index(op.f("ix_coral_graph_revisions_project_id"), table_name="coral_graph_revisions")
    op.drop_index(op.f("ix_coral_graph_revisions_graph_id"), table_name="coral_graph_revisions")
    op.drop_index(op.f("ix_coral_graph_revisions_analysis_id"), table_name="coral_graph_revisions")
    op.drop_table("coral_graph_revisions")
    op.drop_index("ix_ecology_analysis_supersedes", table_name="ecology_analysis_records")
    op.drop_index("ix_ecology_analysis_project_created", table_name="ecology_analysis_records")
    op.drop_table("ecology_analysis_records")
