"""Persist local worker capacity and exclusive job reservations."""

import sqlalchemy as sa
from alembic import op

revision = "b20_compute_0001"
down_revision = "b20_appearance_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_compute_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cpu_slots", sa.Integer(), nullable=False),
        sa.Column("gpu_slots", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_local_compute_singleton"),
        sa.CheckConstraint("cpu_slots BETWEEN 0 AND 8", name="ck_local_compute_cpu"),
        sa.CheckConstraint("gpu_slots BETWEEN 0 AND 1", name="ck_local_compute_gpu"),
    )
    op.create_table(
        "local_compute_leases",
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column("pool", sa.String(6), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("local_compute_leases")
    op.drop_table("local_compute_limits")
