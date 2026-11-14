from __future__ import annotations

import runpy
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.util import CommandError
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.exc import IntegrityError

from reefvision.config import Settings
from reefvision.desktop import run_pending_migrations
from reefvision.services.system import SystemService

_API_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _API_ROOT / "migrations" / "versions"
_INTEGRATED_HEAD = "b12_integrated_0002"
_POSE_MIGRATIONS = (
    "0038_pose_anatomy_definitions.py",
    "0039_pose_evaluation_runs.py",
    "0040_job_deduplication_key.py",
    "0041_pose_identity_tracking.py",
    "0042_pose_biological_measurements.py",
    "0043_reefpose_references.py",
    "0044_reefpose_heldout_locks.py",
)
_PROJECT_ID = "e03ed253-51b5-4396-a9cd-7dbc5ce645af"
_SCHEMA_ID = "a49971f7-7805-4a69-81e7-72b62ea14417"


MigrationDatabase = tuple[Settings, Config, Engine]


@pytest.fixture
def migration_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MigrationDatabase]:
    settings = Settings(data_dir=tmp_path)
    url = settings.resolved_database_url
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REEFVISION_DATABASE_URL", url)
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)
    try:
        yield settings, config, engine
    finally:
        engine.dispose()


def _create_project(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO projects (id, name, slug, storage_root, default_annotation_type, "
            "created_at, updated_at) VALUES (?, 'Reef survey', 'reef-survey', "
            "'projects/reef-survey', 'bbox', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (_PROJECT_ID,),
        )


def _create_standalone_reefpose_db(config: Config, engine: Engine, revision: str) -> None:
    command.upgrade(config, "0037")
    _create_project(engine)
    with engine.begin() as connection:
        # A standalone database used these same DDL bodies under numeric revision IDs.
        with Operations.context(MigrationContext.configure(connection)):
            for migration in _POSE_MIGRATIONS[: int(revision) - 37]:
                path = next(_VERSIONS.glob(f"*{migration}"))
                runpy.run_path(str(path))["upgrade"]()
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.exec_driver_sql(
            "INSERT INTO pose_landmark_schemas (id, project_id, name, created_at) "
            "VALUES (?, ?, 'Anatomy', CURRENT_TIMESTAMP)",
            (_SCHEMA_ID, _PROJECT_ID),
        )
        connection.exec_driver_sql(
            "INSERT INTO pose_landmark_schema_revisions "
            "(id, schema_id, revision, schema_version, groups_json, expanded_labels_json, "
            "keypoint_count, allows_repeated_labels, content_hash, created_at, definition_json) "
            "VALUES (?, ?, 1, '1', '[]', '[]', 1, 0, ?, CURRENT_TIMESTAMP, ?)",
            (
                "85e145e2-96a0-463e-9693-8fe79b25a13b",
                _SCHEMA_ID,
                "1" * 64,
                '{"landmark":"tail"}',
            ),
        )


def _read_heads(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_heads()


@pytest.mark.parametrize(
    "legacy_revision", ("0038", "0039", "0040", "0041", "0042", "0043", "0044")
)
def test_upgrade_preserves_standalone_reefpose_rows(
    migration_db: MigrationDatabase, legacy_revision: str
) -> None:
    _, config, engine = migration_db
    _create_standalone_reefpose_db(config, engine, legacy_revision)

    command.upgrade(config, "head")

    assert _read_heads(engine) == (_INTEGRATED_HEAD,)
    assert set(inspect(engine).get_table_names()) >= {
        "scientific_records",
        "environmental_analysis_results",
        "ecology_identity_revisions",
        "reefpose_heldout_locks",
    }
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT definition_json FROM pose_landmark_schema_revisions WHERE schema_id = ?",
                (_SCHEMA_ID,),
            ).scalar_one()
            == '{"landmark":"tail"}'
        )


@pytest.mark.parametrize("legacy_revision", ("0042", "b12_identity_0005"))
def test_desktop_upgrade_preserves_reefvision_branch_data(
    migration_db: MigrationDatabase, legacy_revision: str
) -> None:
    settings, config, engine = migration_db
    command.upgrade(config, legacy_revision)
    _create_project(engine)
    with engine.begin() as connection:
        if legacy_revision == "0042":
            add_evidence = (
                "INSERT INTO scientific_records "
                "(id, project_id, variable, source_kind, observed_at, payload_json, "
                "content_sha256, created_at) VALUES (?, ?, 'temperature', 'observed', "
                "CURRENT_TIMESTAMP, '{}', 'sample-hash', CURRENT_TIMESTAMP)"
            )
            read_evidence = "SELECT variable FROM scientific_records WHERE project_id = ?"
            expected = "temperature"
        else:
            add_evidence = (
                "INSERT INTO ecology_identity_revisions "
                "(id, project_id, organism_key, revision, kind, reason, created_at) "
                "VALUES (?, ?, 'coral-41', 1, 'organism', 'survey', CURRENT_TIMESTAMP)"
            )
            read_evidence = (
                "SELECT organism_key FROM ecology_identity_revisions WHERE project_id = ?"
            )
            expected = "coral-41"
        connection.exec_driver_sql(
            add_evidence, ("97d271f0-2daa-4e92-be60-c2d9e9152503", _PROJECT_ID)
        )

    run_pending_migrations(settings)
    run_pending_migrations(settings)

    assert _read_heads(engine) == (_INTEGRATED_HEAD,)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(read_evidence, (_PROJECT_ID,)).scalar_one() == expected


@pytest.mark.parametrize(
    "damage",
    (
        "DROP TABLE pose_identity_truth_datasets",
        "ALTER TABLE reefpose_heldout_locks DROP COLUMN protocol_sha256",
        "CREATE TABLE scientific_records (id VARCHAR(36) PRIMARY KEY)",
        "CREATE TABLE review_queue_item_events (id VARCHAR(36) PRIMARY KEY)",
    ),
)
def test_upgrade_rejects_ambiguous_or_incomplete_schema(
    migration_db: MigrationDatabase, damage: str
) -> None:
    _, config, engine = migration_db
    _create_standalone_reefpose_db(config, engine, "0044")
    with engine.begin() as connection:
        connection.exec_driver_sql(damage)
    before_tables = inspect(engine).get_table_names()

    with pytest.raises(CommandError, match="Cannot determine migration lineage"):
        command.upgrade(config, "head")

    assert _read_heads(engine) == ("0044",)
    assert inspect(engine).get_table_names() == before_tables


def test_failed_merge_rolls_back_legacy_revision_and_schema_changes(
    migration_db: MigrationDatabase,
) -> None:
    _, config, engine = migration_db
    _create_standalone_reefpose_db(config, engine, "0044")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER block_merge BEFORE UPDATE ON alembic_version "
            "WHEN NEW.version_num = 'b12_integrated_0002' "
            "BEGIN SELECT RAISE(ABORT, 'simulated merge failure'); END"
        )
    before_tables = inspect(engine).get_table_names()

    with pytest.raises(IntegrityError, match="simulated merge failure"):
        command.upgrade(config, "head")

    assert _read_heads(engine) == ("0044",)
    assert inspect(engine).get_table_names() == before_tables


def test_system_preflight_reads_legacy_reefpose_without_relabeling(
    migration_db: MigrationDatabase,
) -> None:
    settings, config, engine = migration_db
    _create_standalone_reefpose_db(config, engine, "0044")

    preflight = SystemService(settings, engine).migration_preflight()

    assert preflight.compatible_for_upgrade
    assert preflight.requires_backup
    assert preflight.current_schema_revision == "0044"
    assert set(preflight.pending_revisions) >= {"0038", "b12_identity_0001", _INTEGRATED_HEAD}
    assert "reefpose_0038" not in preflight.pending_revisions
    assert _read_heads(engine) == ("0044",)


def test_merged_schema_downgrades_to_common_revision_and_upgrades_again(
    migration_db: MigrationDatabase,
) -> None:
    _, config, engine = migration_db
    command.upgrade(config, "head")
    _create_project(engine)

    command.downgrade(config, "0037")

    assert _read_heads(engine) == ("0037",)
    assert {
        "scientific_records",
        "ecology_identity_revisions",
        "reefpose_heldout_locks",
    }.isdisjoint(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT id FROM projects").scalar_one() == _PROJECT_ID

    command.upgrade(config, "head")
    assert _read_heads(engine) == (_INTEGRATED_HEAD,)


@pytest.mark.parametrize("legacy_revision", ("0038", "0042", "0044"))
def test_offline_upgrade_cannot_disambiguate_numeric_revision(
    migration_db: MigrationDatabase, legacy_revision: str
) -> None:
    _, config, _ = migration_db

    with pytest.raises(CommandError, match="requires an online upgrade"):
        command.upgrade(config, f"{legacy_revision}:head", sql=True)


def test_desktop_resumes_from_separate_branch_heads(migration_db: MigrationDatabase) -> None:
    settings, config, engine = migration_db
    command.upgrade(config, "0042")
    command.upgrade(config, "reefpose_0044")
    assert set(_read_heads(engine)) == {"0042", "reefpose_0044"}

    run_pending_migrations(settings)

    assert _read_heads(engine) == (_INTEGRATED_HEAD,)


def test_desktop_migrates_its_configured_database(
    migration_db: MigrationDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, config, engine = migration_db
    _create_standalone_reefpose_db(config, engine, "0044")
    unrelated_database = tmp_path / "unrelated.db"
    monkeypatch.setenv("REEFVISION_DATABASE_URL", f"sqlite:///{unrelated_database.as_posix()}")

    run_pending_migrations(settings)

    assert _read_heads(engine) == (_INTEGRATED_HEAD,)
    assert not unrelated_database.exists()
