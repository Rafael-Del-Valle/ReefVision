from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from reefvision.config import clear_settings_cache


def test_0041_round_trip_preserves_scalar_metric_rows(tmp_path, monkeypatch):
    root = tmp_path / "aggregate-migration-data"
    url = f"sqlite:///{tmp_path / 'aggregate-migration.db'}"
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(root))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", url)
    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url)
    project_id = str(uuid4())
    definition_id = str(uuid4())
    result_id = str(uuid4())
    try:
        command.upgrade(config, "0040")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, slug, storage_root, "
                    "default_annotation_type, created_at, updated_at) VALUES "
                    "(:id, 'Legacy', 'legacy', 'projects/legacy', 'bbox', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": project_id},
            )
            connection.execute(
                text(
                    "INSERT INTO computed_metric_definitions "
                    "(id, project_id, name, expression, formula_version, input_spec_json, "
                    "output_unit, definition_sha256, created_at) VALUES "
                    "(:id, :project_id, 'Density', 'n / area', 'legacy-engine', '[]', "
                    "'count/m2', :sha, CURRENT_TIMESTAMP)"
                ),
                {"id": definition_id, "project_id": project_id, "sha": "a" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO computed_metric_results "
                    "(id, project_id, definition_id, observed_at, payload_json, "
                    "content_sha256, created_at) VALUES "
                    "(:id, :project_id, :definition_id, CURRENT_TIMESTAMP, '{}', :sha, "
                    "CURRENT_TIMESTAMP)"
                ),
                {
                    "id": result_id,
                    "project_id": project_id,
                    "definition_id": definition_id,
                    "sha": "b" * 64,
                },
            )

        command.upgrade(config, "0041")
        definition_columns = {
            item["name"] for item in inspect(engine).get_columns("computed_metric_definitions")
        }
        result_columns = {
            item["name"] for item in inspect(engine).get_columns("computed_metric_results")
        }
        assert {"definition_kind", "configuration_json"} <= definition_columns
        assert "result_kind" in result_columns
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT definition_kind, configuration_json FROM "
                    "computed_metric_definitions WHERE id=:id"
                ),
                {"id": definition_id},
            ).one() == ("scalar", None)
            assert (
                connection.scalar(
                    text("SELECT result_kind FROM computed_metric_results WHERE id=:id"),
                    {"id": result_id},
                )
                == "scalar"
            )

        command.downgrade(config, "0040")
        command.upgrade(config, "0041")
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT name FROM computed_metric_definitions WHERE id=:id"),
                    {"id": definition_id},
                )
                == "Density"
            )
            assert (
                connection.scalar(
                    text("SELECT definition_kind FROM computed_metric_definitions WHERE id=:id"),
                    {"id": definition_id},
                )
                == "scalar"
            )
            assert (
                connection.scalar(
                    text("SELECT result_kind FROM computed_metric_results WHERE id=:id"),
                    {"id": result_id},
                )
                == "scalar"
            )
    finally:
        engine.dispose()
        clear_settings_cache()
