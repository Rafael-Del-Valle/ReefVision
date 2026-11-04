"""Read-only compatibility check for real 1.1 scientific migration column layouts.

This fixture intentionally mirrors 1.1's 0038_scientific_data.py and
0039_computed_metrics.py. It does not import or merge an unaccepted branch.
The 1.6 desktop must reject these populated databases before any DDL.
"""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


@pytest.mark.parametrize("revision", ["0038", "0039"])
def test_scientific_lineage_with_observations_cannot_be_mistaken_for_qc(
    revision: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        # Exact scientific record field names from the isolated 1.1 migration.
        connection.execute(
            text(
                "CREATE TABLE scientific_records ("
                "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
                "variable TEXT NOT NULL, source_kind TEXT NOT NULL, "
                "observed_at TEXT NOT NULL, image_id TEXT, video_id TEXT, "
                "track_id TEXT, model_run_id TEXT, payload_json TEXT NOT NULL, "
                "content_sha256 TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO scientific_records "
                "(id, project_id, variable, source_kind, observed_at, "
                "payload_json, content_sha256, created_at) VALUES "
                "('observation-1', 'project-1', 'polyp_count', 'manual', "
                "'2026-04-03T12:00:00', '{\"count\": 12}', 'sha-preserved', "
                "'2026-04-03T12:01:00')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE environmental_cache_entries ("
                "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
                "cache_key TEXT NOT NULL, source_url TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, content_sha256 TEXT NOT NULL, "
                "fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
                "UNIQUE(project_id, cache_key))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO environmental_cache_entries VALUES "
                "('cache-1', 'project-1', 'temp', 'local://temperature', "
                "'{\"celsius\": 22.2}', 'cache-sha', "
                "'2026-04-03T12:00:00', '2026-04-04T12:00:00')"
            )
        )
        if revision == "0039":
            connection.execute(
                text(
                    "CREATE TABLE computed_metric_definitions ("
                    "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
                    "name TEXT NOT NULL, expression TEXT NOT NULL, "
                    "formula_version TEXT NOT NULL, input_spec_json TEXT NOT NULL, "
                    "output_unit TEXT NOT NULL, definition_sha256 TEXT NOT NULL, "
                    "created_at TEXT NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO computed_metric_definitions VALUES "
                    "('metric-1', 'project-1', 'count', 'x', 'v1', "
                    "'{}', 'count', 'definition-sha', '2026-04-03T12:00:00')"
                )
            )
        with pytest.raises(RuntimeError, match="revision .* collision"):
            assert_compatible_revision_0038(connection)
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        )
        assert connection.scalar(
            text("SELECT payload_json FROM scientific_records")
        ) == (
            '{"count": 12}'
        )
        assert connection.scalar(
            text("SELECT payload_json FROM environmental_cache_entries")
        ) == (
            '{"celsius": 22.2}'
        )
        if revision == "0039":
            assert connection.scalar(
                text("SELECT definition_sha256 FROM computed_metric_definitions")
            ) == "definition-sha"
    engine.dispose()
