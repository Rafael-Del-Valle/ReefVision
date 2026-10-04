"""Add immutable pose-training datasets.

Revision ID: 0037
Revises: 0036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pose_training_datasets",
        sa.Column(
            "id",
            sa.String(length=36),
            primary_key=True,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "source_round_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "schema_version",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "pose_schema_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "pose_schema_revision",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "pose_schema_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_selection_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_retraining_manifest_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "manifest_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "manifest_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "item_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "pose_schema_revision >= 1",
            name="ck_pose_training_dataset_schema_revision",
        ),
        sa.CheckConstraint(
            "item_count >= 1",
            name="ck_pose_training_dataset_item_count",
        ),
        sa.UniqueConstraint(
            "source_round_id",
            name="uq_pose_training_dataset_source_round",
        ),
        sa.UniqueConstraint(
            "project_id",
            "manifest_sha256",
            name="uq_pose_training_dataset_manifest",
        ),
    )

    op.create_index(
        "ix_pose_training_datasets_project_created",
        "pose_training_datasets",
        ["project_id", "created_at"],
    )

    op.create_table(
        "pose_training_dataset_items",
        sa.Column(
            "id",
            sa.String(length=36),
            primary_key=True,
        ),
        sa.Column(
            "dataset_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "video_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "video_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "video_revision",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "video_track_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "label_class_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "frame_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "verified_track_revision",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "pose_schema_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "pose_schema_revision",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "pose_schema_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "verified_pose_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "canonical_pose_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "source_models_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "source_job_ids_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "acquisition_provenance_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "review_provenance_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "item_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["pose_training_datasets.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "frame_index >= 0",
            name="ck_pose_training_item_frame",
        ),
        sa.CheckConstraint(
            "video_revision >= 1",
            name="ck_pose_training_item_video_revision",
        ),
        sa.CheckConstraint(
            "verified_track_revision >= 1",
            name="ck_pose_training_item_track_revision",
        ),
        sa.CheckConstraint(
            "pose_schema_revision >= 1",
            name="ck_pose_training_item_schema_revision",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "candidate_id",
            name="uq_pose_training_item_candidate",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "video_track_id",
            "frame_index",
            name="uq_pose_training_item_track_frame",
        ),
    )

    op.create_index(
        "ix_pose_training_items_dataset_frame",
        "pose_training_dataset_items",
        ["dataset_id", "frame_index"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pose_training_items_dataset_frame",
        table_name="pose_training_dataset_items",
    )
    op.drop_table("pose_training_dataset_items")

    op.drop_index(
        "ix_pose_training_datasets_project_created",
        table_name="pose_training_datasets",
    )
    op.drop_table("pose_training_datasets")
