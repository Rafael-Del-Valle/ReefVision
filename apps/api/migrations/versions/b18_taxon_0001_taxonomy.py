"""Freeze reviewed taxonomy, survey visits, and conditional detection estimates."""

import sqlalchemy as sa
from alembic import op

revision = "b18_taxon_0001"
down_revision = "b17_monitor_0003"
branch_labels = None
depends_on = None


def _record_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def _role_column(name: str) -> sa.Column:
    return sa.Column(
        name, sa.String(36), sa.ForeignKey("reviewer_lab_role_revisions.id"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "taxonomy_proposals",
        *_record_columns(),
        sa.Column(
            "identity_revision_id",
            sa.String(36),
            sa.ForeignKey("ecology_identity_revisions.id"),
            nullable=False,
        ),
        _role_column("author_role_revision_id"),
    )
    op.create_index(
        "ix_taxonomy_proposals_project", "taxonomy_proposals", ["project_id", "created_at", "id"]
    )
    op.create_table(
        "taxonomy_reviews",
        *_record_columns(),
        sa.Column(
            "proposal_id",
            sa.String(36),
            sa.ForeignKey("taxonomy_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _role_column("reviewer_role_revision_id"),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("proposal_id", "revision", name="uq_taxonomy_review_revision"),
    )
    op.create_table(
        "detectability_visits",
        *_record_columns(),
        sa.Column(
            "proposal_id", sa.String(36), sa.ForeignKey("taxonomy_proposals.id"), nullable=False
        ),
        _role_column("observer_role_revision_id"),
        sa.Column("organism_key", sa.String(100), nullable=False),
        sa.Column("protocol", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "organism_key", "protocol", "started_at", name="uq_detectability_visit"
        ),
    )
    op.create_index(
        "ix_detectability_visits_project_start",
        "detectability_visits",
        ["project_id", "started_at", "id"],
    )
    op.create_table(
        "detectability_presence_reviews",
        *_record_columns(),
        sa.Column(
            "visit_id",
            sa.String(36),
            sa.ForeignKey("detectability_visits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _role_column("reviewer_role_revision_id"),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("visit_id", "revision", name="uq_detectability_presence_revision"),
    )
    op.create_table(
        "detectability_assessments",
        *_record_columns(),
        sa.UniqueConstraint("project_id", "content_sha256", name="uq_detectability_result_content"),
    )
    op.create_index(
        "ix_detectability_assessments_project",
        "detectability_assessments",
        ["project_id", "created_at", "id"],
    )


def downgrade() -> None:
    for table in (
        "detectability_assessments",
        "detectability_presence_reviews",
        "detectability_visits",
        "taxonomy_reviews",
        "taxonomy_proposals",
    ):
        op.drop_table(table)
