"""Add transparent behavior models, predictions, and bout provenance.

Revision ID: 0035
Revises: 0034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "behavior_classifier_models",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("ethogram_revision_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("algorithm", sa.String(length=100), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("feature_set_version", sa.String(length=100), nullable=False),
        sa.Column("feature_preset", sa.String(length=100), nullable=False),
        sa.Column("feature_names_json", sa.JSON(), nullable=False),
        sa.Column("feature_request_json", sa.JSON(), nullable=False),
        sa.Column("scaler_json", sa.JSON(), nullable=False),
        sa.Column("centroids_json", sa.JSON(), nullable=False),
        sa.Column("class_counts_json", sa.JSON(), nullable=False),
        sa.Column("training_track_ids_json", sa.JSON(), nullable=False),
        sa.Column("training_bout_ids_json", sa.JSON(), nullable=False),
        sa.Column("training_sample_count", sa.Integer(), nullable=False),
        sa.Column("training_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ethogram_revision_id"],
            ["behavior_ethogram_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "training_sample_count >= 1",
            name="ck_behavior_classifier_training_samples",
        ),
        sa.UniqueConstraint(
            "project_id",
            "display_name",
            name="uq_behavior_classifier_project_name",
        ),
    )
    op.create_index(
        "ix_behavior_classifier_models_project",
        "behavior_classifier_models",
        ["project_id"],
    )
    op.create_index(
        "ix_behavior_classifier_models_ethogram",
        "behavior_classifier_models",
        ["ethogram_revision_id"],
    )
    op.create_index(
        "ix_behavior_classifier_models_manifest",
        "behavior_classifier_models",
        ["training_manifest_sha256"],
    )

    op.create_table(
        "behavior_predictions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("video_track_id", sa.String(length=36), nullable=False),
        sa.Column("classifier_id", sa.String(length=36), nullable=False),
        sa.Column("ethogram_revision_id", sa.String(length=36), nullable=False),
        sa.Column("behavior_state_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("prediction_score", sa.Float(), nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("feature_vector_json", sa.JSON(), nullable=False),
        sa.Column("feature_parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_track_revision", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("accepted_bout_series_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["video_track_id"],
            ["video_tracks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["classifier_id"],
            ["behavior_classifier_models.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ethogram_revision_id"],
            ["behavior_ethogram_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["behavior_state_id"],
            ["behavior_state_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "start_frame >= 0",
            name="ck_behavior_prediction_start",
        ),
        sa.CheckConstraint(
            "end_frame >= start_frame",
            name="ck_behavior_prediction_frame_order",
        ),
        sa.CheckConstraint(
            "prediction_score >= 0 AND prediction_score <= 1",
            name="ck_behavior_prediction_score",
        ),
        sa.CheckConstraint(
            "source_track_revision >= 1",
            name="ck_behavior_prediction_track_revision",
        ),
        sa.UniqueConstraint(
            "video_track_id",
            "classifier_id",
            "source_track_revision",
            "start_frame",
            "end_frame",
            name="uq_behavior_prediction_window",
        ),
    )
    op.create_index(
        "ix_behavior_predictions_track",
        "behavior_predictions",
        ["video_track_id", "start_frame", "end_frame"],
    )
    op.create_index(
        "ix_behavior_predictions_classifier",
        "behavior_predictions",
        ["classifier_id"],
    )
    op.create_index(
        "ix_behavior_predictions_review",
        "behavior_predictions",
        ["review_status", "created_at"],
    )

    with op.batch_alter_table("behavior_bout_revisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_behavior_classifier_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_behavior_prediction_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_behavior_bout_classifier",
            "behavior_classifier_models",
            ["source_behavior_classifier_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_behavior_bout_prediction",
            "behavior_predictions",
            ["source_behavior_prediction_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("behavior_bout_revisions") as batch_op:
        batch_op.drop_constraint(
            "fk_behavior_bout_prediction",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_behavior_bout_classifier",
            type_="foreignkey",
        )
        batch_op.drop_column("source_behavior_prediction_id")
        batch_op.drop_column("source_behavior_classifier_id")

    op.drop_index(
        "ix_behavior_predictions_review",
        table_name="behavior_predictions",
    )
    op.drop_index(
        "ix_behavior_predictions_classifier",
        table_name="behavior_predictions",
    )
    op.drop_index(
        "ix_behavior_predictions_track",
        table_name="behavior_predictions",
    )
    op.drop_table("behavior_predictions")

    op.drop_index(
        "ix_behavior_classifier_models_manifest",
        table_name="behavior_classifier_models",
    )
    op.drop_index(
        "ix_behavior_classifier_models_ethogram",
        table_name="behavior_classifier_models",
    )
    op.drop_index(
        "ix_behavior_classifier_models_project",
        table_name="behavior_classifier_models",
    )
    op.drop_table("behavior_classifier_models")
