"""Fast validation/atomicity tests independent of installed optional runtimes."""

from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reefvision.db.models import PoseLandmarkSchema, VideoAsset, VideoTrack
from reefvision.domain.errors import ValidationError
from reefvision.services import pose_interoperability as module
from reefvision.services.pose_interoperability import PoseInteroperabilityService as Service
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_interoperability import (
    _external_labels,
    _FakeSio,
    _persist_pose_track,
    _pose_video,
)


def test_missing_runtime_is_actionable_and_capability_is_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(_name):
        raise PackageNotFoundError("sleap-io")

    monkeypatch.setattr(module, "version", missing)
    response = client.get("/api/v1/pose-interoperability/runtime")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "reefvision[interoperability]" in response.json()["installation"]
    with pytest.raises(ValidationError, match=r"pip install.*interoperability"):
        Service._sleap_io()


@pytest.mark.parametrize("problem", ["version", "import"])
def test_incompatible_or_broken_runtime_is_actionable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, problem
) -> None:
    monkeypatch.setattr(module, "version", lambda _: "0.1.0" if problem == "version" else "0.9.2")

    def broken(_):
        raise ImportError("incomplete runtime")

    monkeypatch.setattr(module, "import_module", broken)
    response = client.get("/api/v1/pose-interoperability/runtime")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "pip install" in response.json()["reason"]


@pytest.mark.parametrize(
    "failure",
    [
        "frame",
        "fractional_frame",
        "coordinates",
        "duplicate_nodes",
        "repeated_mapping",
        "duplicate_instance",
        "skeleton",
    ],
)
def test_invalid_import_is_atomic_and_identifies_source(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, failure
) -> None:
    project = create_project(client, "Invalid import")
    video = _pose_video(client, project["id"], monkeypatch)
    labels = _external_labels(video["sha256"], include_provenance=True)
    if failure == "frame":
        labels.labeled_frames[1].frame_idx = 200
    elif failure == "fractional_frame":
        labels.labeled_frames[1].frame_idx = 3.5
    elif failure == "coordinates":
        labels.labeled_frames[1].instances[0].points["xy"][0, 0] = 201
    elif failure == "duplicate_nodes":
        labels.skeletons[0].nodes[1] = "bell_center"
    elif failure == "repeated_mapping":
        labels.provenance["reefvision_pose_interoperability"]["node_mapping"][2][
            "occurrence_index"
        ] = 0
    elif failure == "duplicate_instance":
        labels.labeled_frames[1].instances *= 2
    elif failure == "skeleton":
        labels.skeletons *= 2
    monkeypatch.setattr(Service, "_load_labels", lambda *_a, **_kw: labels)
    response = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={"format": "slp", "label_class_id": project["label_classes"][0]["id"]},
        files={"file": ("broken.slp", b"data", "application/octet-stream")},
    )
    assert response.status_code == 400, response.text
    assert "broken.slp" in response.json()["detail"]
    assert "Nothing was imported" in response.json()["detail"]
    assert "atomic" in response.json()["detail"]
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(VideoTrack)) == 0
        assert session.scalar(select(func.count()).select_from(PoseLandmarkSchema)) == 0


def test_invalid_extension_rejected_before_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected():
        pytest.fail("runtime must not be accessed for an invalid extension")

    monkeypatch.setattr(Service, "_sleap_io", staticmethod(unexpected))
    with pytest.raises(ValidationError, match="extension"):
        Service(None, None)._load_labels("slp", b"data", "wrong.csv")


def test_corrupt_zip_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="valid ZIP"):
        Service._extract_ultralytics_zip(b"corrupt", tmp_path)


def test_partial_write_failure_rolls_back_schema_and_tracks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Rollback")
    video = _pose_video(client, project["id"], monkeypatch)
    labels = _external_labels(video["sha256"], include_provenance=True)
    monkeypatch.setattr(Service, "_load_labels", lambda *_a, **_kw: labels)
    original = Service._resolve_import_schema

    def fail_after_schema(self, *args):
        original(self, *args)
        self.session.flush()
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(Service, "_resolve_import_schema", fail_after_schema)
    response = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={"format": "slp", "label_class_id": project["label_classes"][0]["id"]},
        files={"file": ("broken.slp", b"data", "application/octet-stream")},
    )
    assert response.status_code == 400, response.text
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(VideoTrack)) == 0
        assert session.scalar(select(func.count()).select_from(PoseLandmarkSchema)) == 0


@pytest.mark.parametrize("problem", ["missing_media", "changed_media", "dimensions"])
def test_export_rejects_invalid_source_media(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, problem
) -> None:
    project = create_project(client, "Invalid source")
    video = _pose_video(client, project["id"], monkeypatch)
    _persist_pose_track(client, project, video)
    monkeypatch.setattr(Service, "_sleap_io", staticmethod(lambda: _FakeSio))
    with client.app.state.session_factory() as session:
        asset = session.get(VideoAsset, video["id"])
        path = resolve_managed_project_path(client.app.state.settings, asset.managed_path)
        if problem == "missing_media":
            path.unlink()  # Synthetic test media under the isolated pytest directory.
        elif problem == "changed_media":
            path.write_bytes(b"changed synthetic source")
        else:
            asset.width_px = 0
            session.commit()
    response = client.get(
        f"/api/v1/videos/{video['id']}/pose-interoperability/export", params={"format": "slp"}
    )
    assert response.status_code == 400, response.text
    assert {"missing_media": "missing", "changed_media": "checksum", "dimensions": "dimensional"}[
        problem
    ] in response.json()["detail"]


def test_unsupported_export_format_fails_before_database_access() -> None:
    with pytest.raises(ValidationError, match="Unsupported pose interoperability format"):
        Service(None, None).export("video", "invalid")
