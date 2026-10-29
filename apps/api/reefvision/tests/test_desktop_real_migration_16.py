"""Real SQLite desktop-migration regression for the isolated 1.6 lineage.

Unlike mocked migration tests, this exercises Alembic's env.py, all revision
scripts, and the database that the desktop opens again after upgrading.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from reefvision.config import Settings
from reefvision.db.session import create_database_engine
from reefvision.desktop import resolve_alembic_paths, run_pending_migrations
from reefvision.main import create_app


def test_desktop_fresh_sqlite_migration_persists_revision_across_restarts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "real-desktop-migration.sqlite"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{database.as_posix()}",
    )
    settings.ensure_directories()

    run_pending_migrations(settings)

    # A new engine must see the Alembic revision and the 1.6 review table.
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert inspect(connection).has_table("review_queue_item_events")
            assert inspect(connection).has_table("review_queue_bulk_requests")
    finally:
        engine.dispose()

    # An already-migrated installed desktop must not reset or repeat revisions.
    run_pending_migrations(settings)

    reopened_engine = create_database_engine(settings)
    try:
        with reopened_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert inspect(connection).has_table("review_queue_item_events")
    finally:
        reopened_engine.dispose()


def test_real_0041_schema_enforces_reviewer_request_identity(tmp_path: Path) -> None:
    """Inspect actual Alembic DDL, not a synthetic 0041 revision stamp."""
    database = tmp_path / "audit-contract.sqlite"
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{database.as_posix()}")
    settings.ensure_directories()
    run_pending_migrations(settings)

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"

            events = "review_queue_item_events"
            unique_constraints = inspector.get_unique_constraints(events)
            assert any(
                constraint["name"] == "uq_review_queue_item_event_request"
                and constraint["column_names"] == ["review_queue_item_id", "client_request_id"]
                for constraint in unique_constraints
            )
            event_columns = {column["name"]: column for column in inspector.get_columns(events)}
            assert event_columns["review_queue_item_id"]["nullable"] is False
            assert event_columns["client_request_id"]["nullable"] is False
            assert event_columns["event_type"]["nullable"] is False
            checks = inspector.get_check_constraints(events)
            assert any(
                check["name"] == "ck_review_queue_item_event_type"
                and "triage_complete" in check["sqltext"]
                for check in checks
            )

            bulk = "review_queue_bulk_requests"
            bulk_columns = {column["name"]: column for column in inspector.get_columns(bulk)}
            for required in (
                "id",
                "review_queue_id",
                "project_id",
                "action",
                "actor",
                "item_ids_json",
                "created_at",
            ):
                assert bulk_columns[required]["nullable"] is False
            assert inspector.get_pk_constraint(bulk)["constrained_columns"] == ["id"]
            foreign_keys = {
                (
                    fk["constrained_columns"][0],
                    fk["referred_table"],
                    fk["referred_columns"][0],
                    (fk.get("options") or {}).get("ondelete"),
                )
                for fk in inspector.get_foreign_keys(bulk)
            }
            assert foreign_keys == {
                ("review_queue_id", "review_queues", "id", "RESTRICT"),
                ("project_id", "projects", "id", "RESTRICT"),
            }
    finally:
        engine.dispose()


def test_real_0041_sqlite_enforces_reviewer_registry_foreign_keys(tmp_path: Path) -> None:
    """The actual migrated desktop engine must reject orphaned QC audit batches."""
    database = tmp_path / "review-foreign-keys.sqlite"
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{database.as_posix()}")
    settings.ensure_directories()
    run_pending_migrations(settings)

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_bulk_requests")) == 0

        # A declared RESTRICT foreign key is insufficient if the installed
        # SQLite connection does not actually enable FK enforcement.
        with (
            pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"),
            engine.begin() as connection,
        ):
            connection.execute(
                text(
                    "INSERT INTO review_queue_bulk_requests "
                    "(id, review_queue_id, project_id, action, actor, "
                    "item_ids_json, created_at) "
                    "VALUES (:id, :queue, :project, :action, :actor, :items, :created)"
                ),
                {
                    "id": "orphaned-review-attempt",
                    "queue": "nonexistent-queue",
                    "project": "nonexistent-project",
                    "action": "start",
                    "actor": "local researcher",
                    "items": "[]",
                    "created": "2026-10-29T00:00:00Z",
                },
            )

        # A failed review request cannot persist a registry marker that could
        # later be misinterpreted as proof of a human-reviewed workflow.
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_bulk_requests")) == 0
    finally:
        engine.dispose()


def test_reused_desktop_sqlite_connection_restores_foreign_key_enforcement(
    tmp_path: Path,
) -> None:
    """A pooled local connection must not retain disabled QC audit foreign keys."""
    database = tmp_path / "reused-foreign-keys.sqlite"
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{database.as_posix()}")
    settings.ensure_directories()
    run_pending_migrations(settings)

    engine = create_database_engine(settings)
    try:
        # Simulate a local caller disabling the PRAGMA on a pooled connection.
        # Returning it to the pool must not compromise subsequent review writes.
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            assert connection.scalar(text("PRAGMA foreign_keys")) == 0

        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_bulk_requests")) == 0

        with (
            pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"),
            engine.begin() as connection,
        ):
            connection.execute(
                text(
                    "INSERT INTO review_queue_bulk_requests "
                    "(id, review_queue_id, project_id, action, actor, "
                    "item_ids_json, created_at) "
                    "VALUES (:id, :queue, :project, :action, :actor, :items, :created)"
                ),
                {
                    "id": "pooled-orphan-attempt",
                    "queue": "missing-queue",
                    "project": "missing-project",
                    "action": "start",
                    "actor": "local researcher",
                    "items": "[]",
                    "created": "2026-10-29T00:00:00Z",
                },
            )

        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_bulk_requests")) == 0
    finally:
        engine.dispose()


def test_review_revision_roundtrip_commits_sqlite_version_markers(tmp_path: Path) -> None:
    """Real Alembic downgrade/re-upgrade must persist revision DML on SQLite.

    SQLite DDL may persist independently of a rolled-back alembic_version
    update, so checking only for the presence of tables misses this regression.
    """
    database = tmp_path / "roundtrip.sqlite"
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{database.as_posix()}")
    settings.ensure_directories()
    run_pending_migrations(settings)

    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = settings.resolved_database_url
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    command.downgrade(config, "0037")

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0037"
            assert not inspect(connection).has_table("review_queue_item_events")
    finally:
        engine.dispose()

    run_pending_migrations(settings)
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert inspect(connection).has_table("review_queue_item_events")
    finally:
        engine.dispose()


def test_fresh_migrated_desktop_api_can_create_and_reopen_project(tmp_path: Path) -> None:
    """Catch packaged first-write failures hidden by a healthy /system/version.

    Use real Alembic migrations, not Base.metadata.create_all, and reopen the
    SQLite file with a second API process-equivalent app. A historical Windows
    clean install returned HTTP 500 on POST /projects after HTTP readiness.
    """
    data_dir = tmp_path / "disposable-desktop"
    settings = Settings(
        env="test",
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
    )
    settings.ensure_directories()
    run_pending_migrations(settings)

    first_app = create_app(settings)
    with TestClient(first_app) as client:
        migration = client.get("/api/v1/system/migrations/status")
        assert migration.status_code == 200, migration.text
        state = migration.json()
        assert state["schema_status"] == "up_to_date"
        assert state["current_schema_revision"] == state["expected_schema_revision"]
        created = client.post(
            "/api/v1/projects",
            json={"name": "Disposable migrated project", "template": "blank"},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        assert created.json()["name"] == "Disposable migrated project"

    # Reopening must use the same on-disk database and preserve the project.
    run_pending_migrations(settings)
    reopened_app = create_app(settings)
    with TestClient(reopened_app) as client:
        migration = client.get("/api/v1/system/migrations/status")
        assert migration.status_code == 200, migration.text
        assert migration.json()["schema_status"] == "up_to_date"
        fetched = client.get(f"/api/v1/projects/{project_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["id"] == project_id
        assert fetched.json()["name"] == "Disposable migrated project"


def test_desktop_upgrade_from_0037_preserves_class_visibility_and_projects(
    tmp_path: Path,
) -> None:
    """Real 0037 -> 0041 upgrade retains existing project/class visibility.

    Exercise the actual legacy SQLite schema and API, never a metadata.create_all
    shortcut. This tests the isolated 1.6 lineage, not the conflicting 1.1 0038.
    """
    data_dir = tmp_path / "legacy-desktop"
    settings = Settings(
        env="test",
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
    )
    settings.ensure_directories()

    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = settings.resolved_database_url
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    command.upgrade(config, "0037")

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "Preserved legacy coral study", "template": "blank"},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        label = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"class_index": 0, "name": "Swiftia exserta", "display_color": "#2288AA"},
        )
        assert label.status_code == 201, label.text
        class_id = label.json()["id"]
        default = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/defaults/annotations",
            json={"hidden_class_ids": [class_id]},
        )
        assert default.status_code == 200, default.text
        override = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/preferences/annotations",
            json={"hidden_class_ids": []},
        )
        assert override.status_code == 200, override.text
        assert override.json()["saved"] is True
        before = client.get(f"/api/v1/projects/{project_id}/class-visibility")
        assert before.status_code == 200, before.text
        original_identity = before.json()["user_identity"]

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0037"
            assert not inspect(connection).has_table("review_queue_item_events")
    finally:
        engine.dispose()

    run_pending_migrations(settings)
    with TestClient(create_app(settings)) as client:
        migration = client.get("/api/v1/system/migrations/status")
        assert migration.status_code == 200, migration.text
        assert migration.json()["schema_status"] == "up_to_date"
        assert migration.json()["current_schema_revision"] == "0041"

        project = client.get(f"/api/v1/projects/{project_id}")
        assert project.status_code == 200, project.text
        assert project.json()["name"] == "Preserved legacy coral study"
        assert [item["id"] for item in project.json()["label_classes"]] == [class_id]

        visibility = client.get(f"/api/v1/projects/{project_id}/class-visibility")
        assert visibility.status_code == 200, visibility.text
        state = visibility.json()
        assert state["user_identity"] == original_identity
        assert state["project_defaults"]["annotations"]["saved"] is True
        assert state["project_defaults"]["annotations"]["hidden_class_ids"] == [class_id]
        assert state["user_preferences"]["annotations"]["saved"] is True
        assert state["user_preferences"]["annotations"]["hidden_class_ids"] == []

        # An upgraded installed desktop must still accept new writes.
        another = client.post(
            "/api/v1/projects",
            json={"name": "Post-upgrade project", "template": "blank"},
        )
        assert another.status_code == 201, another.text
        assert another.json()["id"] != project_id
        post_upgrade_id = another.json()["id"]

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert inspect(connection).has_table("review_queue_item_events")
            assert inspect(connection).has_table("review_queue_bulk_requests")
    finally:
        engine.dispose()

    # Reopening again must not lose either legacy or post-upgrade writes.
    run_pending_migrations(settings)
    with TestClient(create_app(settings)) as client:
        for preserved_id in (project_id, post_upgrade_id):
            fetched = client.get(f"/api/v1/projects/{preserved_id}")
            assert fetched.status_code == 200, fetched.text
        visibility = client.get(f"/api/v1/projects/{project_id}/class-visibility")
        assert visibility.status_code == 200, visibility.text
        assert visibility.json()["user_preferences"]["annotations"]["saved"] is True
        assert visibility.json()["user_preferences"]["annotations"]["hidden_class_ids"] == []


def test_legacy_upgrade_keeps_distinct_local_user_class_visibility(tmp_path: Path) -> None:
    """Two local identities sharing a study retain separate visibility after migration."""
    database = tmp_path / "shared-study.sqlite"
    database_url = f"sqlite:///{database.as_posix()}"
    settings_a = Settings(
        env="test",
        data_dir=tmp_path / "researcher-a",
        database_url=database_url,
        background_worker_enabled=False,
    )
    settings_b = Settings(
        env="test",
        data_dir=tmp_path / "researcher-b",
        database_url=database_url,
        background_worker_enabled=False,
    )
    settings_a.ensure_directories()
    settings_b.ensure_directories()

    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = settings_a.resolved_database_url
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings_a.resolved_database_url)
    command.upgrade(config, "0037")

    with TestClient(create_app(settings_a)) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "Shared legacy survey", "template": "blank"},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        class_ids = []
        for index, name in enumerate(("Swiftia open", "Swiftia closed")):
            label = client.post(
                f"/api/v1/projects/{project_id}/classes",
                json={
                    "class_index": index,
                    "name": name,
                    "display_color": "#2288AA",
                },
            )
            assert label.status_code == 201, label.text
            class_ids.append(label.json()["id"])

        defaults = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/defaults/annotations",
            json={"hidden_class_ids": [class_ids[0]]},
        )
        assert defaults.status_code == 200, defaults.text
        override_a = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/preferences/annotations",
            json={"hidden_class_ids": []},
        )
        assert override_a.status_code == 200, override_a.text
        identity_response = client.get(f"/api/v1/projects/{project_id}/class-visibility")
        assert identity_response.status_code == 200, identity_response.text
        identity_a = identity_response.json()["user_identity"]

    with TestClient(create_app(settings_b)) as client:
        initial = client.get(f"/api/v1/projects/{project_id}/class-visibility")
        assert initial.status_code == 200, initial.text
        identity_b = initial.json()["user_identity"]
        assert identity_b != identity_a
        assert initial.json()["user_preferences"]["annotations"]["saved"] is False
        assert initial.json()["project_defaults"]["annotations"]["hidden_class_ids"] == [
            class_ids[0]
        ]
        override_b = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/preferences/annotations",
            json={"hidden_class_ids": [class_ids[1]]},
        )
        assert override_b.status_code == 200, override_b.text

    run_pending_migrations(settings_a)
    # A second installed desktop must see the existing revision, not reapply it.
    run_pending_migrations(settings_b)
    for settings, identity, hidden in (
        (settings_a, identity_a, []),
        (settings_b, identity_b, [class_ids[1]]),
    ):
        with TestClient(create_app(settings)) as client:
            bundle = client.get(f"/api/v1/projects/{project_id}/class-visibility")
            assert bundle.status_code == 200, bundle.text
            state = bundle.json()
            assert state["user_identity"] == identity
            assert state["project_defaults"]["annotations"]["hidden_class_ids"] == [class_ids[0]]
            assert state["user_preferences"]["annotations"]["saved"] is True
            assert state["user_preferences"]["annotations"]["hidden_class_ids"] == hidden
            project = client.get(f"/api/v1/projects/{project_id}")
            assert project.status_code == 200, project.text
            assert [item["id"] for item in project.json()["label_classes"]] == class_ids

    engine = create_database_engine(settings_a)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert (
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM class_visibility_preferences "
                        "WHERE project_id = :project_id"
                    ),
                    {"project_id": project_id},
                )
                == 2
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("legacy_revision", [None, "0037"])
def test_desktop_refuses_partial_science_migration_without_mutating_data(
    tmp_path: Path, legacy_revision: str | None
) -> None:
    """An interrupted 1.1 migration must not become a 1.6 review lineage."""
    data_dir = tmp_path / "interrupted-science"
    settings = Settings(
        env="test",
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
    )
    settings.ensure_directories()

    if legacy_revision is not None:
        alembic_ini, migrations_dir = resolve_alembic_paths()
        config = Config(str(alembic_ini))
        config.attributes["configure_logger"] = False
        config.attributes["desktop_database_url"] = settings.resolved_database_url
        config.set_main_option("script_location", str(migrations_dir))
        config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
        command.upgrade(config, legacy_revision)

    engine = create_database_engine(settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE scientific_records (id TEXT PRIMARY KEY, note TEXT)")
            )
            connection.execute(
                text(
                    "INSERT INTO scientific_records (id, note) "
                    "VALUES ('observation', 'retain original coral measurement')"
                )
            )
        with engine.connect() as connection:
            schema_before = tuple(
                tuple(row)
                for row in connection.execute(
                    text("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")
                )
            )
    finally:
        engine.dispose()

    for _ in range(2):
        with pytest.raises(RuntimeError, match="Unsafe ReefVision .*scientific schema"):
            run_pending_migrations(settings)

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            schema_after = tuple(
                tuple(row)
                for row in connection.execute(
                    text("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")
                )
            )
            assert schema_after == schema_before
            assert (
                connection.scalar(
                    text("SELECT note FROM scientific_records WHERE id = 'observation'")
                )
                == "retain original coral measurement"
            )
            assert not inspect(connection).has_table("review_queue_item_events")
            if legacy_revision is None:
                assert not inspect(connection).has_table("alembic_version")
            else:
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0037"
    finally:
        engine.dispose()


def test_desktop_rejects_foreign_0038_stamp_without_touching_science(
    tmp_path: Path,
) -> None:
    """A conflicting 1.1-style stamp must fail before any desktop migration."""
    data_dir = tmp_path / "conflicting-desktop"
    settings = Settings(
        env="test",
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
    )
    settings.ensure_directories()
    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = settings.resolved_database_url
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    command.upgrade(config, "0037")

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "Do not mutate", "template": "blank"},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        label = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"class_index": 0, "name": "Swiftia exserta", "display_color": "#2288AA"},
        )
        assert label.status_code == 201, label.text
        class_id = label.json()["id"]
        defaults = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/defaults/annotations",
            json={"hidden_class_ids": [class_id]},
        )
        assert defaults.status_code == 200, defaults.text
        override = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/preferences/annotations",
            json={"hidden_class_ids": []},
        )
        assert override.status_code == 200, override.text
        assert override.json()["saved"] is True

    engine = create_database_engine(settings)
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '0038'"))
            connection.execute(
                text("CREATE TABLE scientific_records (id TEXT PRIMARY KEY, note TEXT)")
            )
            connection.execute(
                text(
                    "INSERT INTO scientific_records (id, note) "
                    "VALUES ('original', 'preserve scientific observations')"
                )
            )
            connection.execute(
                text("CREATE TABLE environmental_cache_entries (id TEXT PRIMARY KEY)")
            )
    finally:
        engine.dispose()

    # The guard must be idempotently read-only, including repeated startup attempts.
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            schema_before = tuple(
                tuple(row)
                for row in connection.execute(
                    text("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")
                )
            )
            # A refused foreign migration must not alter researcher visibility.
            visibility_before = {
                table: tuple(
                    tuple(row)
                    for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))
                )
                for table in (
                    "class_visibility_preferences",
                    "project_class_visibility_defaults",
                )
            }
            assert all(len(rows) == 1 for rows in visibility_before.values())
    finally:
        engine.dispose()

    for _ in range(2):
        with pytest.raises(RuntimeError, match="Unsafe ReefVision Alembic revision 0038"):
            run_pending_migrations(settings)

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            schema_after = tuple(
                tuple(row)
                for row in connection.execute(
                    text("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")
                )
            )
            assert schema_after == schema_before
            visibility_after = {
                table: tuple(
                    tuple(row)
                    for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))
                )
                for table in (
                    "class_visibility_preferences",
                    "project_class_visibility_defaults",
                )
            }
            assert visibility_after == visibility_before
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
            assert (
                connection.scalar(text("SELECT note FROM scientific_records WHERE id = 'original'"))
                == "preserve scientific observations"
            )
            assert (
                connection.scalar(
                    text("SELECT id FROM projects WHERE id = :project_id"),
                    {"project_id": project_id},
                )
                == project_id
            )
            assert not inspect(connection).has_table("review_queue_item_events")
    finally:
        engine.dispose()
