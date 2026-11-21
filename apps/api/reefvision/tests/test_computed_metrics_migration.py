from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from reefvision.config import clear_settings_cache


def test_computed_metric_migration_round_trip_preserves_legacy_projects(tmp_path, monkeypatch):
    root = tmp_path / "metric-migration-data"
    url = f"sqlite:///{tmp_path / 'metric-migration.db'}"
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(root))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", url)
    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url)
    project_id = str(uuid4())
    try:
        command.upgrade(config, "0038")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, slug, storage_root, default_annotation_type, "
                    "created_at, updated_at) VALUES (:id, 'Legacy', 'legacy', 'projects/legacy', "
                    "'bbox', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": project_id},
            )
        command.upgrade(config, "head")
        tables = inspect(engine).get_table_names()
        assert "computed_metric_definitions" in tables
        assert "computed_metric_results" in tables
        command.downgrade(config, "0038")
        tables = inspect(engine).get_table_names()
        assert "computed_metric_definitions" not in tables
        assert "computed_metric_results" not in tables
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT name FROM projects WHERE id=:id"), {"id": project_id}
                )
                == "Legacy"
            )
    finally:
        engine.dispose()
        clear_settings_cache()
