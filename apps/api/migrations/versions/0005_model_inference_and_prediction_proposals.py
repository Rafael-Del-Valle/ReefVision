"""Add model registration, proposals, and annotation provenance.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("annotations") as batch_op:
        batch_op.add_column(sa.Column("provenance_json", sa.JSON(), nullable=True))

    op.create_table(
        "model_registrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("source_filename", sa.String(length=500), nullable=False),
        sa.Column("managed_path", sa.String(length=700), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("framework", sa.String(length=100), nullable=False),
        sa.Column("task", sa.String(length=100), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("provider_version", sa.String(length=100), nullable=False),
        sa.Column("class_map_json", sa.JSON(), nullable=False),
        sa.Column("input_size_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("managed_path"),
        sa.UniqueConstraint(
            "project_id",
            "display_name",
            name="uq_model_registrations_project_display_name",
        ),
        sa.UniqueConstraint("project_id", "sha256", name="uq_model_registrations_project_sha256"),
    )
    op.create_index(
        "ix_model_registrations_project_purpose",
        "model_registrations",
        ["project_id", "purpose"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_registrations_project_id"),
        "model_registrations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_registrations_sha256"), "model_registrations", ["sha256"], unique=False
    )

    op.create_table(
        "prediction_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("inference_job_id", sa.String(length=36), nullable=False),
        sa.Column("model_checksum", sa.String(length=64), nullable=False),
        sa.Column("label_class_id", sa.String(length=36), nullable=True),
        sa.Column("predicted_label", sa.String(length=200), nullable=False),
        sa.Column("predicted_index", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("was_edited", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("reviewer_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_annotation_id", sa.String(length=36), nullable=True),
        sa.Column("inference_settings_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["model_registrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inference_job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["label_class_id"], ["label_classes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prediction_proposals_image_status",
        "prediction_proposals",
        ["image_id", "review_status"],
        unique=False,
    )
    op.create_index(
        "ix_prediction_proposals_job_status",
        "prediction_proposals",
        ["inference_job_id", "review_status"],
        unique=False,
    )
    op.create_index(
        "ix_prediction_proposals_model_status",
        "prediction_proposals",
        ["model_id", "review_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_proposals_project_id"),
        "prediction_proposals",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_proposals_image_id"),
        "prediction_proposals",
        ["image_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_proposals_model_id"),
        "prediction_proposals",
        ["model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_proposals_inference_job_id"),
        "prediction_proposals",
        ["inference_job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_proposals_label_class_id"),
        "prediction_proposals",
        ["label_class_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_prediction_proposals_label_class_id"),
        table_name="prediction_proposals",
    )
    op.drop_index(
        op.f("ix_prediction_proposals_inference_job_id"),
        table_name="prediction_proposals",
    )
    op.drop_index(op.f("ix_prediction_proposals_model_id"), table_name="prediction_proposals")
    op.drop_index(op.f("ix_prediction_proposals_image_id"), table_name="prediction_proposals")
    op.drop_index(op.f("ix_prediction_proposals_project_id"), table_name="prediction_proposals")
    op.drop_index("ix_prediction_proposals_model_status", table_name="prediction_proposals")
    op.drop_index("ix_prediction_proposals_job_status", table_name="prediction_proposals")
    op.drop_index("ix_prediction_proposals_image_status", table_name="prediction_proposals")
    op.drop_table("prediction_proposals")

    op.drop_index(op.f("ix_model_registrations_sha256"), table_name="model_registrations")
    op.drop_index(op.f("ix_model_registrations_project_id"), table_name="model_registrations")
    op.drop_index("ix_model_registrations_project_purpose", table_name="model_registrations")
    op.drop_table("model_registrations")

    with op.batch_alter_table("annotations") as batch_op:
        batch_op.drop_column("provenance_json")
