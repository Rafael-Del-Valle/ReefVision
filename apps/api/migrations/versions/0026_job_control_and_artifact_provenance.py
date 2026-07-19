"""Add job orchestration controls and unified artifact provenance.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
        batch.add_column(sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("parent_job_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "checkpoint_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column(
                "resource_requirements_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column(
                "resume_supported",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("worker_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancel_after", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_jobs_parent_job_id",
            "jobs",
            ["parent_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_jobs_priority_created", "jobs", ["priority", "created_at"])
    op.create_index("ix_jobs_heartbeat", "jobs", ["status", "heartbeat_at"])

    op.create_table(
        "job_dependencies",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("depends_on_job_id", sa.String(length=36), nullable=False),
        sa.Column(
            "required_status",
            sa.String(length=30),
            nullable=False,
            server_default="succeeded",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["depends_on_job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "depends_on_job_id"),
        sa.CheckConstraint("job_id <> depends_on_job_id", name="ck_job_dependency_not_self"),
    )
    op.create_index(
        "ix_job_dependencies_depends_on",
        "job_dependencies",
        ["depends_on_job_id"],
    )

    op.create_table(
        "job_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_events_job_created", "job_events", ["job_id", "created_at"])

    op.create_table(
        "artifact_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("reefvision_version", sa.String(length=60), nullable=False),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("source_checksum", sa.String(length=64), nullable=True),
        sa.Column("source_annotation_revision", sa.Integer(), nullable=True),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=True),
        sa.Column("dataset_version_checksum", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=36), nullable=True),
        sa.Column("model_checksum", sa.String(length=64), nullable=True),
        sa.Column("provider_id", sa.String(length=120), nullable=True),
        sa.Column("provider_version", sa.String(length=120), nullable=True),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("postprocessing_json", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=40), nullable=False),
        sa.Column("parent_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("supersedes_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("managed_path", sa.String(length=800), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["model_id"], ["model_registrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["parent_artifact_id"],
            ["artifact_records.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_artifact_id"],
            ["artifact_records.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_artifact_records_project_type_created",
        "artifact_records",
        ["project_id", "artifact_type", "created_at"],
    )
    op.create_index("ix_artifact_records_checksum", "artifact_records", ["checksum"])
    op.create_index(
        "ix_artifact_records_source",
        "artifact_records",
        ["source_kind", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_records_source", table_name="artifact_records")
    op.drop_index("ix_artifact_records_checksum", table_name="artifact_records")
    op.drop_index(
        "ix_artifact_records_project_type_created",
        table_name="artifact_records",
    )
    op.drop_table("artifact_records")
    op.drop_index("ix_job_events_job_created", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_job_dependencies_depends_on", table_name="job_dependencies")
    op.drop_table("job_dependencies")
    op.drop_index("ix_jobs_heartbeat", table_name="jobs")
    op.drop_index("ix_jobs_priority_created", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("fk_jobs_parent_job_id", type_="foreignkey")
        batch.drop_column("last_transition_at")
        batch.drop_column("paused_at")
        batch.drop_column("cancel_after")
        batch.drop_column("heartbeat_at")
        batch.drop_column("worker_id")
        batch.drop_column("resume_supported")
        batch.drop_column("resource_requirements_json")
        batch.drop_column("checkpoint_json")
        batch.drop_column("parent_job_id")
        batch.drop_column("state_version")
        batch.drop_column("max_retries")
        batch.drop_column("retry_count")
        batch.drop_column("priority")
