"""Add immutable canonical pose landmark schemas.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pose_landmark_schemas",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pose_landmark_schemas_project_created",
        "pose_landmark_schemas",
        ["project_id", "created_at"],
    )

    op.create_table(
        "pose_landmark_schema_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "schema_id",
            sa.String(length=36),
            sa.ForeignKey("pose_landmark_schemas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("groups_json", sa.JSON(), nullable=False),
        sa.Column("expanded_labels_json", sa.JSON(), nullable=False),
        sa.Column("keypoint_count", sa.Integer(), nullable=False),
        sa.Column("allows_repeated_labels", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_pose_landmark_schema_revisions_revision",
        ),
        sa.CheckConstraint(
            "keypoint_count >= 1",
            name="ck_pose_landmark_schema_revisions_keypoint_count",
        ),
        sa.UniqueConstraint(
            "schema_id",
            "revision",
            name="uq_pose_landmark_schema_revisions_schema_revision",
        ),
        sa.UniqueConstraint(
            "schema_id",
            "content_hash",
            name="uq_pose_landmark_schema_revisions_schema_hash",
        ),
    )
    op.create_index(
        "ix_pose_landmark_schema_revisions_schema_created",
        "pose_landmark_schema_revisions",
        ["schema_id", "created_at"],
    )

    op.create_table(
        "pose_model_schema_bindings",
        sa.Column(
            "model_id",
            sa.String(length=36),
            sa.ForeignKey("model_registrations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_id", sa.String(length=36), nullable=False),
        sa.Column("schema_revision", sa.Integer(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["schema_id", "schema_revision"],
            [
                "pose_landmark_schema_revisions.schema_id",
                "pose_landmark_schema_revisions.revision",
            ],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_pose_model_schema_bindings_schema_revision",
        "pose_model_schema_bindings",
        ["schema_id", "schema_revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pose_model_schema_bindings_schema_revision",
        table_name="pose_model_schema_bindings",
    )
    op.drop_table("pose_model_schema_bindings")
    op.drop_index(
        "ix_pose_landmark_schema_revisions_schema_created",
        table_name="pose_landmark_schema_revisions",
    )
    op.drop_table("pose_landmark_schema_revisions")
    op.drop_index(
        "ix_pose_landmark_schemas_project_created",
        table_name="pose_landmark_schemas",
    )
    op.drop_table("pose_landmark_schemas")
