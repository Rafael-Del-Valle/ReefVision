"""Upgrade/downgrade event definitions without altering existing scientific projects."""

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from reefvision.config import clear_settings_cache


def test_event_definition_migration_round_trip(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'events.db'}"
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(tmp_path / "events-data"))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", url)
    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url)
    project_id = str(uuid4())
    try:
        command.upgrade(config, "0039")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, slug, storage_root, default_annotation_type, "
                    "created_at, updated_at) VALUES (:id, 'Legacy', 'legacy-events', "
                    "'projects/legacy-events', 'bbox', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": project_id},
            )
        command.upgrade(config, "head")
        assert "environmental_event_definitions" in inspect(engine).get_table_names()
        command.downgrade(config, "0039")
        assert "environmental_event_definitions" not in inspect(engine).get_table_names()
        assert "computed_metric_definitions" in inspect(engine).get_table_names()
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
