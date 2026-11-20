"""Store reviewed project-local runtime selections without modifying registrations."""

import sqlalchemy as sa
from alembic import op

revision = "b15_model_0001"
down_revision = "b14_condition_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_runtime_selections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_id", sa.String(36), sa.ForeignKey("model_registrations.id"), nullable=False
        ),
        sa.Column("snapshot_json", sa.JSON, nullable=False),
        sa.Column("source_id_map_json", sa.JSON, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "content_sha256", name="uq_model_runtime_selection"),
    )
    for column in ("model_id", "project_id"):
        op.create_index(
            f"ix_model_runtime_selections_{column}", "model_runtime_selections", [column]
        )


def downgrade() -> None:
    op.drop_table("model_runtime_selections")
