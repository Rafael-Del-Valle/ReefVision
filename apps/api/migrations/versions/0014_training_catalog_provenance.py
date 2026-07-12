"""Add catalog-backed model provenance fields to training drafts and runs.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_drafts",
        sa.Column("catalog_model_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "training_drafts",
        sa.Column("resolved_model_asset_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "training_drafts",
        sa.Column("resolved_model_checksum", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "training_drafts",
        sa.Column("parameter_registry_version", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "training_drafts",
        sa.Column("selected_preset", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "training_drafts",
        sa.Column("installation_state", sa.String(length=40), nullable=True),
    )
    op.create_index(
        op.f("ix_training_drafts_catalog_model_id"),
        "training_drafts",
        ["catalog_model_id"],
        unique=False,
    )

    op.add_column(
        "training_runs",
        sa.Column("catalog_model_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "training_runs",
        sa.Column("resolved_model_asset_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "training_runs",
        sa.Column("resolved_model_checksum", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "training_runs",
        sa.Column("parameter_registry_version", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "training_runs",
        sa.Column("selected_preset", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "training_runs",
        sa.Column("installation_state", sa.String(length=40), nullable=True),
    )
    op.create_index(
        op.f("ix_training_runs_catalog_model_id"),
        "training_runs",
        ["catalog_model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_training_runs_catalog_model_id"), table_name="training_runs")
    op.drop_column("training_runs", "installation_state")
    op.drop_column("training_runs", "selected_preset")
    op.drop_column("training_runs", "parameter_registry_version")
    op.drop_column("training_runs", "resolved_model_checksum")
    op.drop_column("training_runs", "resolved_model_asset_id")
    op.drop_column("training_runs", "catalog_model_id")

    op.drop_index(op.f("ix_training_drafts_catalog_model_id"), table_name="training_drafts")
    op.drop_column("training_drafts", "installation_state")
    op.drop_column("training_drafts", "selected_preset")
    op.drop_column("training_drafts", "parameter_registry_version")
    op.drop_column("training_drafts", "resolved_model_checksum")
    op.drop_column("training_drafts", "resolved_model_asset_id")
    op.drop_column("training_drafts", "catalog_model_id")
