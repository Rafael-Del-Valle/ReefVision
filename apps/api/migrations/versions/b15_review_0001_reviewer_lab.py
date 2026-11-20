"""Persist immutable Reviewer Lab roles, assignments, decisions, and reports.

Revision ID: b15_review_0001
Revises: b14_condition_0041
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b15_review_0001"
down_revision: str = "b14_condition_0041"
branch_labels: tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def identity() -> sa.Column[str]:
    return sa.Column("id", sa.String(36), primary_key=True)


def project() -> sa.Column[str]:
    return sa.Column(
        "project_id",
        sa.String(36),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )


def created_at() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "reviewer_lab_members",
        identity(),
        project(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(250), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.UniqueConstraint("project_id", "name_key", name="uq_reviewer_lab_member_name"),
    )
    op.create_table(
        "reviewer_lab_role_revisions",
        identity(),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_role_revisions.id"),
            unique=True,
        ),
        sa.Column(
            "granted_by_role_revision_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_role_revisions.id"),
        ),
        created_at(),
        sa.UniqueConstraint("member_id", "revision", name="uq_reviewer_lab_role_revision"),
    )
    op.create_table(
        "reviewer_lab_credentials",
        sa.Column(
            "role_revision_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_role_revisions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("credential_sha256", sa.String(64), nullable=False, unique=True),
    )
    op.create_table(
        "reviewer_lab_rounds",
        identity(),
        project(),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("plan_json", sa.JSON, nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        created_at(),
        sa.UniqueConstraint("project_id", "operation_id", name="uq_reviewer_lab_round_operation"),
    )
    op.create_table(
        "reviewer_lab_decisions",
        identity(),
        sa.Column(
            "round_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_rounds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column(
            "role_revision_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_role_revisions.id"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("value", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("decision_ids_json", sa.JSON),
        created_at(),
        sa.UniqueConstraint("round_id", "subject_id", "slot", name="uq_reviewer_lab_decision_slot"),
        sa.UniqueConstraint("round_id", "operation_id", name="uq_reviewer_lab_decision_operation"),
    )
    op.create_table(
        "reviewer_lab_reports",
        identity(),
        project(),
        sa.Column(
            "round_id",
            sa.String(36),
            sa.ForeignKey("reviewer_lab_rounds.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("content_json", sa.JSON, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
    )
    for table in ("reviewer_lab_members", "reviewer_lab_rounds", "reviewer_lab_reports"):
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])


def downgrade() -> None:
    for table in ("reviewer_lab_members", "reviewer_lab_rounds", "reviewer_lab_reports"):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
    for table in (
        "reviewer_lab_reports",
        "reviewer_lab_decisions",
        "reviewer_lab_rounds",
        "reviewer_lab_credentials",
        "reviewer_lab_role_revisions",
        "reviewer_lab_members",
    ):
        op.drop_table(table)
