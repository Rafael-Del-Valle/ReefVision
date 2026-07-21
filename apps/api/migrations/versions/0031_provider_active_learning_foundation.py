"""Unify provider assets, acceptance, embeddings, and active-learning promotion.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_model_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("provider_version", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=300), nullable=False),
        sa.Column("architecture", sa.String(length=200), nullable=False),
        sa.Column("task", sa.String(length=100), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("checkpoint_path", sa.String(length=1200), nullable=False),
        sa.Column("checkpoint_path_kind", sa.String(length=30), nullable=False),
        sa.Column("checkpoint_sha256", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checkpoint_format", sa.String(length=80), nullable=False),
        sa.Column("file_manifest_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column("revision", sa.String(length=200), nullable=True),
        sa.Column("license_json", sa.JSON(), nullable=False),
        sa.Column("required_packages_json", sa.JSON(), nullable=False),
        sa.Column("optional_packages_json", sa.JSON(), nullable=False),
        sa.Column("supported_devices_json", sa.JSON(), nullable=False),
        sa.Column("preferred_device", sa.String(length=30), nullable=False),
        sa.Column("estimated_vram_bytes", sa.BigInteger(), nullable=True),
        sa.Column("input_types_json", sa.JSON(), nullable=False),
        sa.Column("output_types_json", sa.JSON(), nullable=False),
        sa.Column("prompt_types_json", sa.JSON(), nullable=False),
        sa.Column("supports_training", sa.Boolean(), nullable=False),
        sa.Column("supports_inference", sa.Boolean(), nullable=False),
        sa.Column("supports_video", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("verification_json", sa.JSON(), nullable=False),
        sa.Column("last_health_check_json", sa.JSON(), nullable=False),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_load_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_inference_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", name="uq_provider_model_assets_model_id"),
    )
    op.create_index(
        "ix_provider_model_assets_provider_state",
        "provider_model_assets",
        ["provider_id", "state"],
    )
    op.create_index(
        "ix_provider_model_assets_checksum",
        "provider_model_assets",
        ["checkpoint_sha256"],
    )

    op.create_table(
        "provider_acceptance_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("provider_asset_id", sa.String(length=36), nullable=True),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=300), nullable=False),
        sa.Column("checkpoint_sha256", sa.String(length=64), nullable=True),
        sa.Column("device", sa.String(length=80), nullable=False),
        sa.Column("runtime_versions_json", sa.JSON(), nullable=False),
        sa.Column("load_result", sa.String(length=30), nullable=False),
        sa.Column("inference_result", sa.String(length=30), nullable=False),
        sa.Column("unload_result", sa.String(length=30), nullable=False),
        sa.Column("peak_memory_bytes", sa.BigInteger(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("test_input_identifier", sa.String(length=500), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("validation_kind", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_asset_id"],
            ["provider_model_assets.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_acceptance_provider_model",
        "provider_acceptance_records",
        ["provider_id", "model_id"],
    )
    op.create_index(
        "ix_provider_acceptance_recorded",
        "provider_acceptance_records",
        ["recorded_at"],
    )
    op.create_index(
        op.f("ix_provider_acceptance_records_run_id"),
        "provider_acceptance_records",
        ["run_id"],
    )

    with op.batch_alter_table("image_embeddings") as batch_op:
        batch_op.add_column(sa.Column("embedding_key", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "provider_id",
                sa.String(length=100),
                nullable=False,
                server_default=sa.text("'legacy'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "model_version",
                sa.String(length=100),
                nullable=False,
                server_default=sa.text("'unknown'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "preprocessing_version",
                sa.String(length=100),
                nullable=False,
                server_default=sa.text("'legacy'"),
            )
        )
        batch_op.add_column(sa.Column("source_image_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "source_kind",
                sa.String(length=30),
                nullable=False,
                server_default=sa.text("'image'"),
            )
        )
        batch_op.add_column(sa.Column("crop_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "normalization",
                sa.String(length=40),
                nullable=False,
                server_default=sa.text("'l2'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=30),
                nullable=False,
                server_default=sa.text("'ready'"),
            )
        )

    op.execute(
        "UPDATE image_embeddings "
        "SET embedding_key = substr(lower(hex(randomblob(32))), 1, 64) "
        "WHERE embedding_key IS NULL"
    )
    with op.batch_alter_table("image_embeddings") as batch_op:
        batch_op.alter_column("embedding_key", existing_type=sa.String(length=64), nullable=False)
        batch_op.drop_constraint("uq_image_embeddings_image_model", type_="unique")
        batch_op.create_unique_constraint(
            "uq_image_embeddings_image_key",
            ["image_id", "embedding_key"],
        )

    with op.batch_alter_table("review_queues") as batch_op:
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1"))
        )
        batch_op.add_column(sa.Column("generation_key", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("promoted_dataset_version_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(sa.Column("promoted_cycle_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(
            "uq_review_queues_generation_key",
            ["generation_key"],
        )
        batch_op.create_foreign_key(
            "fk_review_queues_promoted_dataset_version_id",
            "dataset_versions",
            ["promoted_dataset_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_review_queues_promoted_cycle_id",
            "active_learning_cycles",
            ["promoted_cycle_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("review_queue_items") as batch_op:
        batch_op.add_column(
            sa.Column(
                "selection_reasons_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "manual_state",
                sa.String(length=30),
                nullable=False,
                server_default=sa.text("'automatic'"),
            )
        )
        batch_op.add_column(sa.Column("fragment_key", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("near_duplicate_key", sa.String(length=128), nullable=True))

    with op.batch_alter_table("active_learning_cycles") as batch_op:
        batch_op.add_column(
            sa.Column("embedding_provider_id", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(sa.Column("embedding_model_id", sa.String(length=300), nullable=True))
        batch_op.add_column(
            sa.Column("embedding_model_checksum", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("queue_revision", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "accepted_annotation_ids_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "rejected_item_ids_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "warnings_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("active_learning_cycles") as batch_op:
        batch_op.drop_column("warnings_json")
        batch_op.drop_column("rejected_item_ids_json")
        batch_op.drop_column("accepted_annotation_ids_json")
        batch_op.drop_column("queue_revision")
        batch_op.drop_column("embedding_model_checksum")
        batch_op.drop_column("embedding_model_id")
        batch_op.drop_column("embedding_provider_id")

    with op.batch_alter_table("review_queue_items") as batch_op:
        batch_op.drop_column("near_duplicate_key")
        batch_op.drop_column("fragment_key")
        batch_op.drop_column("manual_state")
        batch_op.drop_column("selection_reasons_json")

    with op.batch_alter_table("review_queues") as batch_op:
        batch_op.drop_constraint(
            "fk_review_queues_promoted_cycle_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_review_queues_promoted_dataset_version_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint("uq_review_queues_generation_key", type_="unique")
        batch_op.drop_column("promoted_at")
        batch_op.drop_column("promoted_cycle_id")
        batch_op.drop_column("promoted_dataset_version_id")
        batch_op.drop_column("generation_key")
        batch_op.drop_column("revision")

    with op.batch_alter_table("image_embeddings") as batch_op:
        batch_op.drop_constraint("uq_image_embeddings_image_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_image_embeddings_image_model",
            ["image_id", "embedding_model_id"],
        )
        batch_op.drop_column("status")
        batch_op.drop_column("normalization")
        batch_op.drop_column("crop_json")
        batch_op.drop_column("source_kind")
        batch_op.drop_column("source_image_sha256")
        batch_op.drop_column("preprocessing_version")
        batch_op.drop_column("model_version")
        batch_op.drop_column("provider_id")
        batch_op.drop_column("embedding_key")

    op.drop_index(
        op.f("ix_provider_acceptance_records_run_id"),
        table_name="provider_acceptance_records",
    )
    op.drop_index(
        "ix_provider_acceptance_recorded",
        table_name="provider_acceptance_records",
    )
    op.drop_index(
        "ix_provider_acceptance_provider_model",
        table_name="provider_acceptance_records",
    )
    op.drop_table("provider_acceptance_records")

    op.drop_index(
        "ix_provider_model_assets_checksum",
        table_name="provider_model_assets",
    )
    op.drop_index(
        "ix_provider_model_assets_provider_state",
        table_name="provider_model_assets",
    )
    op.drop_table("provider_model_assets")
