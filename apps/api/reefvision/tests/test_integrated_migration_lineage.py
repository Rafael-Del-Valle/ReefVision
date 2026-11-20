from __future__ import annotations

import json
import runpy
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.util import CommandError
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration, ProjectExchangePackage
from reefvision.desktop import run_pending_migrations
from reefvision.services.system import SystemService
from reefvision.storage.datasets import canonical_json_sha256

_API_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _API_ROOT / "migrations" / "versions"
_INTEGRATED_HEAD = "b17_workflows_0001"
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


def test_schedule_migration_preserves_the_existing_project(migration_db: MigrationDatabase) -> None:
    _, config, engine = migration_db
    command.upgrade(config, "b16_integrated_0001")
    _create_project(engine)
    previous_tables = set(inspect(engine).get_table_names())
    schedule_tables = {"workflow_schedules", "workflow_schedule_occurrences"}
    with engine.connect() as connection:
        old_project = connection.exec_driver_sql("SELECT * FROM projects").one()
    command.upgrade(config, "b17_workflows_0001")
    schema = inspect(engine)
    assert set(schema.get_table_names()) == previous_tables | schedule_tables
    occurrence_keys = schema.get_unique_constraints("workflow_schedule_occurrences")
    assert {tuple(key["column_names"]) for key in occurrence_keys} >= {
        ("schedule_id", "scheduled_at"),
        ("workflow_run_id",),
    }
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT * FROM projects").one() == old_project
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    command.downgrade(config, "b16_integrated_0001")
    assert set(inspect(engine).get_table_names()) == previous_tables
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT * FROM projects").one() == old_project


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


@pytest.mark.parametrize("origin", ["local", "restored", "unknown", "empty"])
def test_desktop_recovers_early_runtime_schema_preserving_receipts(
    migration_db: MigrationDatabase, origin: str
) -> None:
    settings, config, engine = migration_db
    command.upgrade(config, "b15_model_0001")
    _create_project(engine)
    model_id = "f59e9b26-2737-4760-9225-d77ce2117358"
    source_project = _PROJECT_ID if origin == "local" else "e594820a-554c-49f9-b7d8-cff196b42e2c"
    source_model = model_id if origin == "local" else "8481cfdc-965e-40c0-8ecc-83ac52edb681"
    origin_map = {source_project: _PROJECT_ID, source_model: model_id}
    snapshot = {
        "schema_version": "reviewed-model-runtime-0001",
        "source_project_id": source_project,
        "source_model_id": source_model,
        "checkpoint_sha256": "a" * 64,
    }
    raw, digest = json.dumps(snapshot), canonical_json_sha256(snapshot)
    with Session(engine) as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=_PROJECT_ID,
                purpose="detector",
                display_name="Prior model",
                source_filename="prior.pt",
                managed_path="models/prior.pt",
                sha256="a" * 64,
                file_size_bytes=10,
                framework="ultralytics",
                task="detect",
                provider_name="ultralytics",
                provider_version="fixture",
            )
        )
        if origin == "restored":
            session.add(
                ProjectExchangePackage(
                    project_id=_PROJECT_ID,
                    direction="import",
                    status="complete",
                    format_version="1.5",
                    archive_path="exchange/copied.zip",
                    options_json={"origin_id_map": origin_map},
                )
            )
        session.commit()
    with engine.begin() as con:
        con.exec_driver_sql("ALTER TABLE model_runtime_selections DROP COLUMN source_id_map_json")
        if origin != "empty":
            con.exec_driver_sql(
                "INSERT INTO model_runtime_selections "
                "(id, project_id, model_id, snapshot_json, content_sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?, '2026-11-19 23:59:50')",
                (_SCHEMA_ID, _PROJECT_ID, model_id, raw, digest),
            )
    if origin == "unknown":
        old_tables = inspect(engine).get_table_names()
        with pytest.raises(CommandError, match="pre-upgrade backup"):
            run_pending_migrations(settings)
        assert inspect(engine).get_table_names() == old_tables
        assert _read_heads(engine) == ("b15_model_0001",)
        assert "source_id_map_json" not in {
            c["name"] for c in inspect(engine).get_columns("model_runtime_selections")
        }
    else:
        run_pending_migrations(settings)
        run_pending_migrations(settings)
        assert _read_heads(engine) == (_INTEGRATED_HEAD,)
        with engine.connect() as con:
            mapping = con.exec_driver_sql(
                "SELECT source_id_map_json FROM model_runtime_selections"
            ).scalar()
            assert (json.loads(mapping) if mapping else None) == (
                origin_map if origin == "restored" else {} if origin == "local" else None
            )
            assert con.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    with engine.connect() as con:
        preserved = con.exec_driver_sql(
            "SELECT id, project_id, model_id, snapshot_json, content_sha256, created_at "
            "FROM model_runtime_selections"
        ).all()
        assert preserved == (
            []
            if origin == "empty"
            else [(_SCHEMA_ID, _PROJECT_ID, model_id, raw, digest, "2026-11-19 23:59:50")]
        )


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
    before_tables = inspect(engine).get_table_names()

    def interrupt_merge(conn, cursor, statement, parameters, context, executemany):
        if "UPDATE alembic_version" in statement and "b12_integrated_0002" in statement:
            raise RuntimeError("simulated merge failure")

    event.listen(Engine, "before_cursor_execute", interrupt_merge)
    try:
        with pytest.raises(RuntimeError, match="simulated merge failure"):
            command.upgrade(config, "head")
    finally:
        event.remove(Engine, "before_cursor_execute", interrupt_merge)

    assert _read_heads(engine) == ("0044",)
    assert inspect(engine).get_table_names() == before_tables


def test_desktop_rejects_unknown_future_schema_without_changing_database(
    migration_db: MigrationDatabase,
) -> None:
    settings, config, engine = migration_db
    command.upgrade(config, "head")
    _create_project(engine)
    future = "reefvision_future_fixture"
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = ?", (future,))
    database = settings.resolved_data_dir / "reefvision.db"
    engine.dispose()
    before = database.read_bytes()

    assert SystemService(settings, engine).compatibility().compatible_for_read_write is False
    with pytest.raises(CommandError, match=future):
        run_pending_migrations(settings)

    assert _read_heads(engine) == (future,)
    assert database.read_bytes() == before


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


def test_temporal_migration_preserves_prior_scientific_tables(
    migration_db: MigrationDatabase,
) -> None:
    _, config, engine = migration_db
    prior = "b13_scientific_0001"
    tables = {"temporal_reefpose_datasets", "temporal_reefpose_runs", "temporal_reefpose_frames"}
    command.upgrade(config, prior)
    _create_project(engine)
    command.upgrade(config, "head")
    assert tables <= set(inspect(engine).get_table_names())
    command.downgrade(config, prior)
    assert tables.isdisjoint(inspect(engine).get_table_names())
    assert set(_read_heads(engine)) == {prior, "spatial_0039", "reviewq_0041"}
    assert {"spatial_source_assets", "spatial_calibration_reviews"} <= set(
        inspect(engine).get_table_names()
    )
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


@pytest.mark.parametrize("revision", ["0038", "0039", "0040", "0041"])
def test_desktop_distinguishes_historical_qc_revision(
    migration_db: MigrationDatabase, revision: str
) -> None:
    settings, config, engine = migration_db
    command.upgrade(config, f"reviewq_{revision}")
    _create_project(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = ?", (revision,))
    database = settings.resolved_data_dir / "reefvision.db"
    before = database.read_bytes()
    preflight = SystemService(settings, engine).migration_preflight()
    assert preflight.compatible_for_upgrade and preflight.current_schema_revision == revision
    assert f"reviewq_{revision}" not in preflight.pending_revisions
    assert "0038" in preflight.pending_revisions
    assert before == database.read_bytes()
    run_pending_migrations(settings)
    run_pending_migrations(settings)
    assert _read_heads(engine) == (_INTEGRATED_HEAD,)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT id FROM projects").scalar_one() == _PROJECT_ID
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()


@pytest.mark.parametrize(
    "drift", ["index", "event vocabulary", "foreign key", "default", "mixed", "ledger trigger"]
)
def test_ambiguous_qc_copy_refuses_all_writes(migration_db: MigrationDatabase, drift: str) -> None:
    settings, config, engine = migration_db
    command.upgrade(config, "reviewq_0038")
    with engine.begin() as connection:
        if drift == "index":
            connection.exec_driver_sql("DROP INDEX ix_review_queue_item_events_item_created")
            connection.exec_driver_sql(
                "CREATE INDEX ix_review_queue_item_events_item_created "
                "ON review_queue_item_events(review_queue_item_id, created_at DESC) "
                "WHERE actor != ''"
            )
        elif drift == "mixed":
            connection.exec_driver_sql("CREATE TABLE scientific_records (id TEXT PRIMARY KEY)")
        elif drift == "ledger trigger":
            connection.exec_driver_sql(
                "CREATE TRIGGER extra_ledger_action AFTER UPDATE ON alembic_version "
                "BEGIN SELECT 1; END"
            )
        else:
            ddl = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name='review_queue_item_events'"
            ).scalar_one()
            indexes = (
                connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                    "AND tbl_name='review_queue_item_events'"
                )
                .scalars()
                .all()
            )
            before, after = {
                "event vocabulary": ("'unassign'", "'triage_complete'"),
                "foreign key": ("ON DELETE CASCADE", "ON DELETE CASCADE ON UPDATE CASCADE"),
                "default": (
                    "actor VARCHAR(100) NOT NULL",
                    "actor VARCHAR(100) DEFAULT 'local' NOT NULL",
                ),
            }[drift]
            assert before in ddl
            connection.exec_driver_sql("DROP TABLE review_queue_item_events")
            connection.exec_driver_sql(ddl.replace(before, after))
            for statement in indexes:
                connection.exec_driver_sql(statement)
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = '0038'")
    database = settings.resolved_data_dir / "reefvision.db"
    before_file = database.read_bytes()
    preflight = SystemService(settings, engine).migration_preflight()
    assert not preflight.compatible_for_upgrade
    assert "verified pre-upgrade backup" in " ".join(preflight.blocking_issues)
    with pytest.raises(CommandError, match="Preserve the original"):
        run_pending_migrations(settings)
    assert database.read_bytes() == before_file


def test_unversioned_database_is_never_mistaken_for_clean_install(
    migration_db: MigrationDatabase,
) -> None:
    settings, _, engine = migration_db
    with engine.begin() as con:
        con.exec_driver_sql("CREATE TABLE observations (record TEXT)")
        con.exec_driver_sql("INSERT INTO observations VALUES ('recorded field observation')")
    database = settings.resolved_data_dir / "reefvision.db"
    before = database.read_bytes()
    assert not SystemService(settings, engine).migration_preflight().compatible_for_upgrade
    with pytest.raises(CommandError, match="no recorded migration"):
        run_pending_migrations(settings)
    assert before == database.read_bytes()
