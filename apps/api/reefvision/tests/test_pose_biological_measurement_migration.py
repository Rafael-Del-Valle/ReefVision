from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import UniqueConstraint

from reefvision.config import clear_settings_cache
from reefvision.db.models.pose_biological_measurement import (
    PoseBiologicalEventRevision,
    PoseEventDetectionRun,
    PoseMeasurementRun,
    PoseMeasurementSample,
    PoseMeasurementSeries,
)
from reefvision.schemas.pose_biological_measurement import (
    MeasurementDefinition,
    PoseMeasurementRunCreateRequest,
)


EXPECTED_TABLES = {
    "pose_measurement_runs",
    "pose_measurement_series",
    "pose_measurement_samples",
    "pose_event_detection_runs",
    "pose_biological_event_revisions",
}


def _config(path: Path) -> Config:
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return config


def test_models_preserve_sources_and_append_only_events() -> None:
    assert PoseMeasurementRun.__table__.c.source_identity_run_revision.nullable is False
    assert next(iter(PoseMeasurementRun.__table__.c.source_identity_run_id.foreign_keys)).target_fullname == "pose_identity_association_runs.id"
    assert PoseMeasurementSeries.__table__.c.formula_version.nullable is False
    assert PoseMeasurementSample.__table__.c.quality_flags_json.nullable is False
    assert PoseEventDetectionRun.__table__.c.configuration_sha256.nullable is False
    uniques = {
        tuple(c.columns.keys())
        for c in PoseBiologicalEventRevision.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert ("event_series_id", "revision") in uniques
    assert PoseBiologicalEventRevision.__table__.c.is_current.default.arg is True


def test_measurement_request_validates_stable_landmarks() -> None:
    request = PoseMeasurementRunCreateRequest(
        video_id="video-1",
        source_identity_run_id="identity-run-1",
        source_identity_run_revision=2,
        definitions=[
            MeasurementDefinition(
                id="gape",
                name="Gape distance",
                kind="distance",
                landmark_ids=["upper_jaw_tip", "lower_jaw_tip"],
            )
        ],
    )
    assert request.definitions[0].landmark_ids == ["upper_jaw_tip", "lower_jaw_tip"]


def test_0042_round_trip_preserves_phase4_identity_run(tmp_path: Path, monkeypatch: object) -> None:
    path = tmp_path / "phase5.db"
    monkeypatch.setenv("REEFVISION_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    clear_settings_cache()
    config = _config(path)
    command.upgrade(config, "0041")

    with sqlite3.connect(path) as connection:
        project_id, video_id, run_id = "p" * 36, "v" * 36, "r" * 36
        connection.execute(
            "INSERT INTO projects (id,name,slug,storage_root,default_annotation_type,georeference_height_offset_m,created_at,updated_at) VALUES (?,?,?,'p','bbox',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (project_id, "p", "p"),
        )
        connection.execute(
            "INSERT INTO videos (id,project_id,original_filename,managed_path,sha256,media_type,width_px,height_px,frame_count,fps,duration_seconds,metadata_json,status,revision,created_at,updated_at) VALUES (?,?, 'v.mp4','v.mp4',?,'video/mp4',10,10,10,10,1,'{}','imported',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (video_id, project_id, "a" * 64),
        )
        connection.execute(
            "INSERT INTO pose_identity_association_runs (id,project_id,video_id,pose_schema_id,pose_schema_revision,pose_schema_content_hash,algorithm,algorithm_version,parameters_json,parameters_sha256,input_manifest_sha256,source_coordinate_space,source_width,source_height,status,progress_json,revision,created_at,updated_at) VALUES (?,?,?,?,1,?,'hungarian','1','{}',?,?,'source_pixels',10,10,'succeeded','{}',3,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (run_id, project_id, video_id, "fish", "b" * 64, "c" * 64, "d" * 64),
        )
        connection.commit()

    for target in ("0042", "0041", "0042"):
        (command.upgrade if target == "0042" else command.downgrade)(config, target)
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert (EXPECTED_TABLES <= tables) is (target == "0042")
            assert connection.execute("SELECT revision FROM pose_identity_association_runs WHERE id=?", (run_id,)).fetchone() == (3,)
