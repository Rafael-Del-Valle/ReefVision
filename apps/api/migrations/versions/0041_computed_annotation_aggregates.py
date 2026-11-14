"""Discriminate scalar metrics from reviewed annotation aggregates.

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "computed_metric_definitions",
        sa.Column("definition_kind", sa.String(40), nullable=False, server_default="scalar"),
    )
    op.add_column(
        "computed_metric_definitions",
        sa.Column("configuration_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "computed_metric_results",
        sa.Column("result_kind", sa.String(40), nullable=False, server_default="scalar"),
    )


def downgrade() -> None:
    op.drop_column("computed_metric_results", "result_kind")
    op.drop_column("computed_metric_definitions", "configuration_json")
    op.drop_column("computed_metric_definitions", "definition_kind")
