"""Migration 0042 is additive and preserves legacy scientific evidence."""

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from reefvision.config import clear_settings_cache


def test_environmental_analysis_migration_round_trip_preserves_legacy_rows(
    tmp_path, monkeypatch
) -> None:
    url = f"sqlite:///{tmp_path / 'environmental-analysis.db'}"
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(tmp_path / "environmental-analysis-data"))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", url)
    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url)
    project_id = str(uuid4())
    record_id = str(uuid4())
    try:
        command.upgrade(config, "0041")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, slug, storage_root, default_annotation_type, "
                    "created_at, updated_at) VALUES (:id, 'Legacy', 'legacy-analysis', "
                    "'projects/legacy-analysis', 'bbox', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": project_id},
            )
            connection.execute(
                text(
                    "INSERT INTO scientific_records "
                    "(id, project_id, variable, source_kind, observed_at, payload_json, "
                    "content_sha256, created_at) VALUES "
                    "(:id, :project_id, 'water_temperature', 'observed', CURRENT_TIMESTAMP, "
                    "'{}', :sha, CURRENT_TIMESTAMP)"
                ),
                {"id": record_id, "project_id": project_id, "sha": "a" * 64},
            )

        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert "environmental_analysis_definitions" in inspector.get_table_names()
        assert "environmental_analysis_results" in inspector.get_table_names()
        assert {
            "analysis_kind",
            "configuration_json",
            "calculation_version",
            "definition_sha256",
        }.issubset(
            {
                column["name"]
                for column in inspector.get_columns("environmental_analysis_definitions")
            }
        )
        assert {
            "source_record_ids_json",
            "source_analysis_result_ids_json",
            "quality_control_json",
            "uncertainty_json",
            "workflow_node_run_id",
        }.issubset(
            {column["name"] for column in inspector.get_columns("environmental_analysis_results")}
        )
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT variable FROM scientific_records WHERE id=:id"), {"id": record_id}
                )
                == "water_temperature"
            )

        command.downgrade(config, "0041")
        inspector = inspect(engine)
        assert "environmental_analysis_definitions" not in inspector.get_table_names()
        assert "environmental_analysis_results" not in inspector.get_table_names()
        assert "environmental_event_definitions" in inspector.get_table_names()
        assert "computed_metric_results" in inspector.get_table_names()
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT variable FROM scientific_records WHERE id=:id"), {"id": record_id}
                )
                == "water_temperature"
            )
    finally:
        engine.dispose()
        clear_settings_cache()


def test_environmental_analysis_workflow_node_result_is_unique(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'environmental-analysis-unique.db'}"
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(tmp_path / "unique-data"))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", url)
    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        unique_columns = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(
                "environmental_analysis_results"
            )
        }
        assert ("workflow_node_run_id",) in unique_columns
    finally:
        engine.dispose()
        clear_settings_cache()
