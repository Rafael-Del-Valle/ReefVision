"""Record the registered output separately from each training run's initialization model."""

import sqlalchemy as sa
from alembic import op

revision = "b19_registration_0001"
down_revision = "b18_spectral_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Inline the reference so SQLite retains the existing training table and all dependants.
    op.execute(
        "ALTER TABLE training_runs ADD COLUMN registered_model_id VARCHAR(36) "
        "REFERENCES model_registrations(id) ON DELETE SET NULL"
    )
    runs = sa.table(
        "training_runs",
        *(
            sa.column(name, sa.String())
            for name in ("id", "project_id", "status", "task", "provider_id", "registered_model_id")
        ),
        sa.column("artifact_manifest_json", sa.JSON()),
    )
    models = sa.table(
        "model_registrations",
        *(
            sa.column(name, sa.String())
            for name in ("id", "project_id", "task", "provider_name", "sha256")
        ),
        sa.column("metadata_json", sa.JSON()),
    )
    origin = models.c.metadata_json
    best = runs.c.artifact_manifest_json["best_checkpoint_sha256"].as_string()
    recorded = origin["source_checkpoint_sha256"].as_string()
    candidates = (
        sa.select(sa.func.min(models.c.id))
        .where(
            models.c.project_id == runs.c.project_id,
            models.c.task == runs.c.task,
            models.c.provider_name == runs.c.provider_id,
            origin["registered_from"].as_string() == "training_run",
            origin["source_training_run_id"].as_string() == runs.c.id,
            sa.or_(best == models.c.sha256, recorded == models.c.sha256),
            sa.or_(best.is_(None), best == models.c.sha256),
            sa.or_(recorded.is_(None), recorded == models.c.sha256),
        )
        .having(sa.func.count() == 1)
        .correlate(runs)
        .scalar_subquery()
    )
    op.execute(
        runs.update().where(runs.c.status == "completed").values(registered_model_id=candidates)
    )


def downgrade() -> None:
    op.drop_column("training_runs", "registered_model_id")
