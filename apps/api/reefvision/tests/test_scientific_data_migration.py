from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from reefvision.config import clear_settings_cache


def test_scientific_migration_preserves_legacy_projects(tmp_path, monkeypatch):
    root = tmp_path / "migration-data"
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(root))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", url)
    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url)
    project_id = str(uuid4())
    try:
        command.upgrade(config, "0037")
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
        assert "scientific_records" in inspect(engine).get_table_names()
        assert "environmental_cache_entries" in inspect(engine).get_table_names()
        command.downgrade(config, "0037")
        assert "scientific_records" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT name FROM projects WHERE id=:id"), {"id": project_id}
                )
                == "Legacy"
            )
        command.upgrade(config, "head")
        assert "scientific_records" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        clear_settings_cache()
