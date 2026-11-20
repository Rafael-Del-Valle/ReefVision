from __future__ import annotations

import runpy
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import Engine, create_engine, inspect

from reefvision.config import Settings

_API_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_SPATIAL = _API_ROOT / "migrations" / "legacy_spatial"
_PROJECT_ID = "507af087-ff80-458f-9470-9b3bdc980a5b"
_ASSET_ID = "04f9c44e-d30e-494f-ab1e-9aa3b4db02e9"
_REVIEW_ID = "be5cb2db-445f-4a15-8434-5a7d168bd22e"
_MERGE_HEAD = "b14_integration_0001"
_HEAD = "b17_monitor_0003"

MigrationDatabase = tuple[Config, Engine]


@pytest.fixture
def migration_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MigrationDatabase]:
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", settings.resolved_database_url)
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    engine = create_engine(settings.resolved_database_url)
    try:
        yield config, engine
    finally:
        engine.dispose()


def _heads(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_heads()


def _create_project(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO projects (id, name, slug, storage_root, default_annotation_type, "
            "created_at, updated_at) VALUES (?, 'Spatial survey', 'spatial-survey', "
            "'projects/spatial-survey', 'bbox', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (_PROJECT_ID,),
        )


def _create_legacy_spatial_database(config: Config, engine: Engine, revision: str) -> None:
    command.upgrade(config, "0037")
    _create_project(engine)
    migrations = (
        "0038_spatial_source_assets.py",
        "0039_spatial_calibration_reviews.py",
    )
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            for migration in migrations[: int(revision) - 37]:
                runpy.run_path(str(_LEGACY_SPATIAL / migration))["upgrade"]()
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = ?", (revision,))


def test_integrated_graph_has_unique_revisions_and_one_head() -> None:
    scripts = ScriptDirectory.from_config(Config(str(_API_ROOT / "alembic.ini")))

    revisions = list(scripts.walk_revisions())

    assert len({revision.revision for revision in revisions}) == len(revisions)
    assert scripts.get_heads() == [_HEAD]
    merge = scripts.get_revision(_MERGE_HEAD)
    assert merge is not None
    assert set(merge.down_revision) == {"b13_temporal_0001", "spatial_0039"}


@pytest.mark.parametrize("legacy_revision", ("0038", "0039"))
def test_upgrade_preserves_legacy_spatial_records(
    migration_db: MigrationDatabase, legacy_revision: str
) -> None:
    config, engine = migration_db
    _create_legacy_spatial_database(config, engine, legacy_revision)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO spatial_source_assets "
            "(id, project_id, original_filename, source_format, source_kind, managed_path, "
            "sha256, size_bytes, created_at) VALUES (?, ?, 'reef.obj', 'obj', 'mesh', "
            "'projects/spatial-survey/assets/reef.obj', ?, 128, CURRENT_TIMESTAMP)",
            (_ASSET_ID, _PROJECT_ID, "a" * 64),
        )
        if legacy_revision == "0039":
            connection.exec_driver_sql(
                "INSERT INTO spatial_calibration_reviews "
                "(id, project_id, spatial_source_asset_id, source_sha256, evidence_sha256, "
                "evidence_json, created_at) VALUES (?, ?, ?, ?, ?, '{}', CURRENT_TIMESTAMP)",
                (_REVIEW_ID, _PROJECT_ID, _ASSET_ID, "a" * 64, "b" * 64),
            )

    command.upgrade(config, "head")

    assert _heads(engine) == (_HEAD,)
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT original_filename FROM spatial_source_assets WHERE id = ?", (_ASSET_ID,)
            ).scalar_one()
            == "reef.obj"
        )
        if legacy_revision == "0039":
            assert (
                connection.exec_driver_sql(
                    "SELECT id FROM spatial_calibration_reviews WHERE id = ?", (_REVIEW_ID,)
                ).scalar_one()
                == _REVIEW_ID
            )


def test_validated_1_3_database_gains_spatial_branch_without_data_loss(
    migration_db: MigrationDatabase,
) -> None:
    config, engine = migration_db
    command.upgrade(config, "b13_temporal_0001")
    _create_project(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO scientific_records "
            "(id, project_id, variable, source_kind, observed_at, payload_json, "
            "content_sha256, created_at) VALUES (?, ?, 'temperature', 'observed', "
            "CURRENT_TIMESTAMP, '{}', ?, CURRENT_TIMESTAMP)",
            ("9929f410-05ff-4362-8ef9-f5036257e43e", _PROJECT_ID, "c" * 64),
        )

    command.upgrade(config, "head")

    assert _heads(engine) == (_HEAD,)
    assert {
        "spatial_source_assets",
        "spatial_calibration_reviews",
        "spatial_asset_metadata_revisions",
    } <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT variable FROM scientific_records WHERE project_id = ?", (_PROJECT_ID,)
            ).scalar_one()
            == "temperature"
        )


def test_ambiguous_numeric_spatial_and_science_schema_is_rejected_unchanged(
    migration_db: MigrationDatabase,
) -> None:
    config, engine = migration_db
    _create_legacy_spatial_database(config, engine, "0039")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE scientific_records (id VARCHAR(36) PRIMARY KEY)")
    before_tables = inspect(engine).get_table_names()

    with pytest.raises(CommandError, match="Cannot determine migration lineage"):
        command.upgrade(config, "head")

    assert _heads(engine) == ("0039",)
    assert inspect(engine).get_table_names() == before_tables
