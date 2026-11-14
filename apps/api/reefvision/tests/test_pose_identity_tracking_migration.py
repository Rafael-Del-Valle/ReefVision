from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import UniqueConstraint

from reefvision.config import clear_settings_cache
from reefvision.db.models.pose_identity_tracking import (
    PoseAnimalIdentity,
    PoseIdentityAssociationDecision,
    PoseIdentityAssociationRun,
    PoseIdentityCorrection,
    PoseIdentityEvaluationRun,
    PoseIdentityObservation,
    PoseIdentityOcclusion,
    PoseIdentityTruthDataset,
)

EXPECTED_TABLES = {
    "pose_identity_association_runs",
    "pose_animal_identities",
    "pose_identity_observations",
    "pose_identity_association_decisions",
    "pose_identity_occlusions",
    "pose_identity_corrections",
    "pose_identity_truth_datasets",
    "pose_identity_evaluation_runs",
}


def _alembic_config(database_path: Path) -> Config:
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return config


def test_identity_models_preserve_revision_and_provenance_contracts() -> None:
    assert PoseIdentityAssociationRun.__table__.name in EXPECTED_TABLES
    assert PoseAnimalIdentity.__table__.c.stable_identity_key.nullable is False
    assert PoseAnimalIdentity.__table__.c.verification_state.default.arg == "unreviewed"
    assert PoseIdentityObservation.__table__.c.coordinate_space.default.arg == "source_pixels"
    assert PoseIdentityObservation.__table__.c.landmarks_json.nullable is False
    assert PoseIdentityAssociationDecision.__table__.c.score_components_json.nullable is False
    assert PoseIdentityOcclusion.__table__.c.end_frame.nullable is True
    assert PoseIdentityCorrection.__table__.c.before_sha256.nullable is False
    assert PoseIdentityTruthDataset.__table__.c.manifest_sha256.unique is True
    assert PoseIdentityEvaluationRun.__table__.c.metrics_json.nullable is False

    observation_uniques = {
        tuple(constraint.columns.keys())
        for constraint in PoseIdentityObservation.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("observation_series_id", "revision") in observation_uniques


def test_identity_foreign_keys_retain_source_video_schema_and_revision() -> None:
    run_columns = PoseIdentityAssociationRun.__table__.c
    assert next(iter(run_columns.video_id.foreign_keys)).target_fullname == "videos.id"
    assert run_columns.pose_schema_revision.nullable is False
    assert run_columns.pose_schema_content_hash.nullable is False
    assert run_columns.parameters_sha256.nullable is False

    observation_columns = PoseIdentityObservation.__table__.c
    assert next(iter(observation_columns.source_video_track_id.foreign_keys)).target_fullname == (
        "video_tracks.id"
    )
    assert next(
        iter(observation_columns.supersedes_observation_id.foreign_keys)
    ).target_fullname == ("pose_identity_observations.id")


def test_0041_upgrade_and_downgrade_preserve_existing_video_tracks(
    tmp_path: Path, monkeypatch: object
) -> None:
    database_path = tmp_path / "pose-identity-migration.db"
    monkeypatch.setenv("REEFVISION_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    clear_settings_cache()
    config = _alembic_config(database_path)
    command.upgrade(config, "0040")

    with sqlite3.connect(database_path) as connection:
        project_id = "00000000-0000-0000-0000-000000000001"
        label_id = "00000000-0000-0000-0000-000000000002"
        video_id = "00000000-0000-0000-0000-000000000003"
        track_id = "00000000-0000-0000-0000-000000000004"
        connection.execute(
            "INSERT INTO projects (id, name, slug, storage_root, default_annotation_type, "
            "georeference_height_offset_m, created_at, updated_at) VALUES "
            "(?, 'Migration project', 'migration-project', 'projects/migration', 'bbox', 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (project_id,),
        )
        connection.execute(
            "INSERT INTO label_classes (id, project_id, class_index, display_order, name, "
            "display_color, is_active, created_at, updated_at) VALUES "
            "(?, ?, 0, 0, 'fish', '#336699', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (label_id, project_id),
        )
        connection.execute(
            "INSERT INTO videos (id, project_id, original_filename, managed_path, sha256, "
            "media_type, width_px, height_px, frame_count, fps, duration_seconds, "
            "metadata_json, status, revision, created_at, updated_at) VALUES "
            "(?, ?, 'fixture.mp4', 'videos/fixture.mp4', ?, 'video/mp4', 10, 10, 1, 1, 1, "
            "'{}', 'imported', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (video_id, project_id, "a" * 64),
        )
        connection.execute(
            "INSERT INTO video_tracks (id, video_id, label_class_id, track_number, "
            "geometry_kind, keyframes_json, interpolation, status, revision, created_at, "
            "updated_at) VALUES (?, ?, ?, 1, 'pose', '[]', 'linear', 'draft', 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (track_id, video_id, label_id),
        )
        connection.commit()

    command.upgrade(config, "0041")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= EXPECTED_TABLES
        assert connection.execute(
            "SELECT id, revision FROM video_tracks WHERE id = ?", (track_id,)
        ).fetchone() == (track_id, 1)

    command.downgrade(config, "0040")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert not EXPECTED_TABLES & tables
        assert connection.execute(
            "SELECT id, revision FROM video_tracks WHERE id = ?", (track_id,)
        ).fetchone() == (track_id, 1)
