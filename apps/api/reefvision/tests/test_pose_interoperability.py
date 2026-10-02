from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import VideoTrack
from reefvision.domain.errors import ValidationError
from reefvision.schemas.videos import VideoTrackKeyframe
from reefvision.services import video_assets as video_assets_module
from reefvision.services.pose_interoperability import PoseInteroperabilityService
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 120,
        "frame_count": 20,
        "fps": 10.0,
        "duration_seconds": 2.0,
    }


def _pose_video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("pose.mp4", io.BytesIO(b"pose-video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _schema() -> dict[str, object]:
    return {
        "schema_version": "pose-landmarks-0001",
        "schema_id": "schema-1",
        "schema_revision": 1,
        "groups": [
            {"name": "bell_center", "count": 1},
            {"name": "tentacle", "count": 2},
        ],
        "expanded_labels": ["bell_center", "tentacle", "tentacle"],
        "keypoint_count": 3,
        "allows_repeated_labels": True,
        "content_hash": "a" * 64,
    }


class _FakeSkeleton:
    def __init__(self, *, nodes: list[str], name: str) -> None:
        self.nodes = nodes
        self.name = name

    @property
    def node_names(self) -> list[str]:
        return list(self.nodes)


class _FakeTrack:
    def __init__(self, *, name: str) -> None:
        self.name = name


class _FakeCategory:
    def __init__(self, *, name: str) -> None:
        self.name = name


class _FakePredictedInstance:
    calls: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def from_numpy(cls, points: np.ndarray, **kwargs: Any) -> SimpleNamespace:
        record = {"points": points.copy(), **kwargs}
        cls.calls.append(record)
        return SimpleNamespace(**record)


class _FakeLabeledFrame:
    def __init__(self, *, video: object, frame_idx: int, instances: list[object]) -> None:
        self.video = video
        self.frame_idx = frame_idx
        self.instances = instances


class _FakeVideo:
    @classmethod
    def from_filename(cls, filename: str, keep_open: bool = False) -> SimpleNamespace:
        return SimpleNamespace(filename=filename, keep_open=keep_open)


class _FakeLabels:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _FakeSio:
    Skeleton = _FakeSkeleton
    Track = _FakeTrack
    Category = _FakeCategory
    PredictedInstance = _FakePredictedInstance
    LabeledFrame = _FakeLabeledFrame
    Video = _FakeVideo
    Labels = _FakeLabels
    last_labels: _FakeLabels | None = None

    @classmethod
    def _remember(cls, labels: _FakeLabels) -> None:
        cls.last_labels = labels

    @classmethod
    def save_slp(cls, labels: _FakeLabels, filename: str, **_: Any) -> None:
        cls._remember(labels)
        Path(filename).write_bytes(b"slp")

    @classmethod
    def save_nwb(cls, labels: _FakeLabels, filename: Path, **_: Any) -> None:
        cls._remember(labels)
        Path(filename).write_bytes(b"nwb")

    @classmethod
    def save_coco(cls, labels: _FakeLabels, filename: str, **_: Any) -> None:
        cls._remember(labels)
        Path(filename).write_text('{"format":"coco"}', encoding="utf-8")

    @classmethod
    def save_csv(cls, labels: _FakeLabels, filename: str, **_: Any) -> None:
        cls._remember(labels)
        Path(filename).write_text("scorer,bodypart,x,y\n", encoding="utf-8")

    @classmethod
    def save_ultralytics(
        cls,
        labels: _FakeLabels,
        dataset_path: str,
        **_: Any,
    ) -> None:
        cls._remember(labels)
        root = Path(dataset_path)
        (root / "labels" / "train").mkdir(parents=True, exist_ok=True)
        (root / "data.yaml").write_text("path: .\n", encoding="utf-8")
        (root / "labels" / "train" / "000000.txt").write_text(
            "0 0.5 0.5 1 1\n",
            encoding="utf-8",
        )


def _persist_pose_track(
    client: TestClient,
    project: dict[str, object],
    video: dict[str, object],
) -> str:
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        track = VideoTrack(
            video_id=str(video["id"]),
            label_class_id=str(label_classes[0]["id"]),
            track_number=1,
            geometry_kind="bbox",
            interpolation="hold",
            status="verified",
            keyframes_json=[
                {
                    "frame": 4,
                    "bbox": [1.0, 2.0, 30.0, 40.0],
                    "confidence": 0.9,
                    "keypoints": [
                        [5.0, 6.0, 0.95],
                        [7.0, 8.0, 0.80],
                        [9.0, 10.0, 0.75],
                    ],
                    "pose_observations": [
                        {
                            "id": "corrected-center",
                            "semantic_label": "bell_center",
                            "occurrence_index": 0,
                            "x": 15.0,
                            "y": 16.0,
                            "confidence": 0.99,
                            "status": "visible",
                            "source": "corrected",
                        },
                        {
                            "id": "occluded-tentacle",
                            "semantic_label": "tentacle",
                            "occurrence_index": 0,
                            "x": 17.0,
                            "y": 18.0,
                            "confidence": 0.60,
                            "status": "occluded",
                            "source": "corrected",
                        },
                        {
                            "id": "absent-tentacle",
                            "semantic_label": "tentacle",
                            "occurrence_index": 1,
                            "x": 0.0,
                            "y": 0.0,
                            "confidence": 0.0,
                            "status": "absent",
                            "source": "corrected",
                        },
                    ],
                }
            ],
            metadata_json={
                "pose_tracking": True,
                "pose_landmark_schema": _schema(),
            },
        )
        session.add(track)
        session.commit()
        session.refresh(track)
        return track.id


def test_repeated_semantic_labels_receive_stable_external_node_names() -> None:
    names, mapping = PoseInteroperabilityService._external_node_names(
        ("bell_center", "tentacle", "tentacle"),
    )

    assert names == ("bell_center", "tentacle__1", "tentacle__2")
    assert mapping == (
        {
            "external_node_name": "bell_center",
            "semantic_label": "bell_center",
            "occurrence_index": 0,
        },
        {
            "external_node_name": "tentacle__1",
            "semantic_label": "tentacle",
            "occurrence_index": 0,
        },
        {
            "external_node_name": "tentacle__2",
            "semantic_label": "tentacle",
            "occurrence_index": 1,
        },
    )


def test_corrected_pose_observations_take_precedence_and_preserve_visibility() -> None:
    keyframe = VideoTrackKeyframe.model_validate(
        {
            "frame": 4,
            "bbox": [1.0, 2.0, 30.0, 40.0],
            "keypoints": [
                [5.0, 6.0, 0.95],
                [7.0, 8.0, 0.80],
                [9.0, 10.0, 0.75],
            ],
            "pose_observations": [
                {
                    "id": "center",
                    "semantic_label": "bell_center",
                    "occurrence_index": 0,
                    "x": 15.0,
                    "y": 16.0,
                    "confidence": 0.99,
                    "status": "visible",
                    "source": "corrected",
                },
                {
                    "id": "tentacle-0",
                    "semantic_label": "tentacle",
                    "occurrence_index": 0,
                    "x": 17.0,
                    "y": 18.0,
                    "confidence": 0.60,
                    "status": "occluded",
                    "source": "corrected",
                },
                {
                    "id": "tentacle-1",
                    "semantic_label": "tentacle",
                    "occurrence_index": 1,
                    "x": 0.0,
                    "y": 0.0,
                    "confidence": 0.0,
                    "status": "out_of_frame",
                    "source": "corrected",
                },
            ],
        }
    )
    names, mapping = PoseInteroperabilityService._external_node_names(
        ("bell_center", "tentacle", "tentacle"),
    )
    context = SimpleNamespace(
        expanded_labels=("bell_center", "tentacle", "tentacle"),
        external_node_names=names,
        node_mapping=mapping,
        schema_metadata=_schema(),
    )

    converted = PoseInteroperabilityService._keyframe_points(
        keyframe,
        context,  # type: ignore[arg-type]
    )
    assert converted is not None
    points, scores = converted

    assert points[0].tolist() == [15.0, 16.0, 1.0]
    assert points[1].tolist() == [17.0, 18.0, 0.0]
    assert np.isnan(points[2, 0])
    assert np.isnan(points[2, 1])
    assert points[2, 2] == 0.0
    assert scores.tolist() == [0.99, 0.60, 0.0]


@pytest.mark.parametrize(
    ("exchange_format", "expected_content_type"),
    [
        ("slp", "application/octet-stream"),
        ("nwb", "application/x-hdf5"),
        ("coco", "application/json"),
        ("dlc_csv", "text/csv; charset=utf-8"),
        ("ultralytics_pose", "application/zip"),
    ],
)
def test_pose_interoperability_exports_canonical_reviewed_pose(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    exchange_format: str,
    expected_content_type: str,
) -> None:
    project = create_project(client, f"Pose interop {exchange_format}")
    video = _pose_video(client, str(project["id"]), monkeypatch)
    _persist_pose_track(client, project, video)

    _FakePredictedInstance.calls.clear()
    _FakeSio.last_labels = None
    monkeypatch.setattr(
        PoseInteroperabilityService,
        "_sleap_io",
        staticmethod(lambda: _FakeSio),
    )

    response = client.get(
        f"/api/v1/videos/{video['id']}/pose-interoperability/export",
        params={"format": exchange_format},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(expected_content_type)
    assert response.headers["x-reefvision-pose-interoperability-format"] == exchange_format
    assert response.headers["x-reefvision-pose-lossy"] == "true"
    assert response.content
    assert _FakeSio.last_labels is not None
    assert _FakeSio.last_labels.skeletons[0].nodes == [
        "bell_center",
        "tentacle__1",
        "tentacle__2",
    ]
    provenance = _FakeSio.last_labels.provenance["reefvision_pose_interoperability"]
    assert provenance["source_video_id"] == video["id"]
    assert provenance["pose_schema"]["content_hash"] == "a" * 64

    exported = _FakePredictedInstance.calls[-1]
    points = exported["points"]
    assert points[0].tolist() == [15.0, 16.0, 1.0]
    assert points[1].tolist() == [17.0, 18.0, 0.0]
    assert np.isnan(points[2, 0])
    assert exported["point_scores"].tolist() == [0.99, 0.60, 0.0]


def _external_predicted_instance(
    *,
    track: object | None,
    coordinates: list[tuple[float, float]],
    visible: list[bool],
    scores: list[float],
    instance_score: float = 0.9,
) -> SimpleNamespace:
    dtype = np.dtype(
        [
            ("xy", "<f8", (2,)),
            ("score", "<f8"),
            ("visible", "bool"),
            ("complete", "bool"),
            ("name", "O"),
        ]
    )
    points = np.empty(len(coordinates), dtype=dtype)
    points["xy"] = np.asarray(coordinates, dtype=np.float64)
    points["score"] = np.asarray(scores, dtype=np.float64)
    points["visible"] = np.asarray(visible, dtype=np.bool_)
    points["complete"] = True
    points["name"] = ["bell_center", "tentacle__1", "tentacle__2"]
    return SimpleNamespace(points=points, track=track, score=instance_score)


def _external_labels(
    video_sha256: str,
    *,
    include_provenance: bool,
    source_sha256: str | None = None,
    tracked: bool = True,
) -> _FakeLabels:
    skeleton = _FakeSkeleton(
        nodes=["bell_center", "tentacle__1", "tentacle__2"],
        name="external",
    )
    external_track = _FakeTrack(name="animal-7") if tracked else None
    first = _external_predicted_instance(
        track=external_track,
        coordinates=[(20.0, 25.0), (30.0, 40.0), (50.0, 60.0)],
        visible=[True, False, True],
        scores=[0.95, 0.60, 0.80],
    )
    second = _external_predicted_instance(
        track=external_track,
        coordinates=[(21.0, 26.0), (31.0, 41.0), (np.nan, np.nan)],
        visible=[True, False, False],
        scores=[0.96, 0.55, 0.0],
    )
    provenance: dict[str, object] = {}
    if include_provenance:
        provenance["reefvision_pose_interoperability"] = {
            "schema_version": "reefvision-pose-interoperability-0001",
            "source_video_id": "source-video",
            "source_video_sha256": source_sha256 or video_sha256,
            "source_filename": "pose.mp4",
            "frame_index_base": 0,
            "coordinate_base": 0,
            "pose_schema": _schema(),
            "node_mapping": [
                {
                    "external_node_name": "bell_center",
                    "semantic_label": "bell_center",
                    "occurrence_index": 0,
                },
                {
                    "external_node_name": "tentacle__1",
                    "semantic_label": "tentacle",
                    "occurrence_index": 0,
                },
                {
                    "external_node_name": "tentacle__2",
                    "semantic_label": "tentacle",
                    "occurrence_index": 1,
                },
            ],
        }
    return _FakeLabels(
        skeletons=[skeleton],
        labeled_frames=[
            _FakeLabeledFrame(video=object(), frame_idx=2, instances=[first]),
            _FakeLabeledFrame(video=object(), frame_idx=3, instances=[second]),
        ],
        provenance=provenance,
    )


def test_pose_interoperability_import_restores_repeated_labels_and_track_grouping(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Pose interop import")
    video = _pose_video(client, str(project["id"]), monkeypatch)
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    labels = _external_labels(str(video["sha256"]), include_provenance=True)
    monkeypatch.setattr(
        PoseInteroperabilityService,
        "_load_labels",
        lambda *_args, **_kwargs: labels,
    )

    response = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={
            "format": "slp",
            "label_class_id": str(label_classes[0]["id"]),
        },
        files={"file": ("pose.slp", io.BytesIO(b"external-pose"), "application/octet-stream")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["track_count"] == 1
    assert payload["keyframe_count"] == 2
    assert payload["used_reefvision_provenance"] is True
    assert payload["warnings"] == []

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks")
    assert tracks.status_code == 200, tracks.text
    imported = [
        item
        for item in tracks.json()
        if item["id"] in set(payload["created_track_ids"])
    ]
    assert len(imported) == 1
    track = imported[0]
    assert track["status"] == "imported_review_required"
    assert track["metadata_json"]["pose_landmark_schema"]["expanded_labels"] == [
        "bell_center",
        "tentacle",
        "tentacle",
    ]
    assert track["metadata_json"]["pose_interoperability_import"]["external_track_name"] == (
        "animal-7"
    )
    assert [item["frame"] for item in track["keyframes_json"]] == [2, 3]
    first_observations = track["keyframes_json"][0]["pose_observations"]
    assert first_observations[1]["semantic_label"] == "tentacle"
    assert first_observations[1]["occurrence_index"] == 0
    assert first_observations[1]["status"] == "occluded"
    second_observations = track["keyframes_json"][1]["pose_observations"]
    assert second_observations[2]["status"] == "absent"


def test_external_pose_import_requires_explicit_frame_mapping_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Unprovenanced pose import")
    video = _pose_video(client, str(project["id"]), monkeypatch)
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    labels = _external_labels(
        str(video["sha256"]),
        include_provenance=False,
        tracked=False,
    )
    monkeypatch.setattr(
        PoseInteroperabilityService,
        "_load_labels",
        lambda *_args, **_kwargs: labels,
    )

    rejected = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={
            "format": "coco",
            "label_class_id": str(label_classes[0]["id"]),
        },
        files={"file": ("pose.json", io.BytesIO(b"external-pose"), "application/json")},
    )
    assert rejected.status_code == 400
    assert "explicit confirmation" in rejected.json()["detail"]

    accepted = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={
            "format": "coco",
            "label_class_id": str(label_classes[0]["id"]),
            "confirm_frame_mapping": "true",
        },
        files={"file": ("pose.json", io.BytesIO(b"external-pose"), "application/json")},
    )
    assert accepted.status_code == 201, accepted.text
    payload = accepted.json()
    assert payload["used_reefvision_provenance"] is False
    assert payload["track_count"] == 2
    assert any("did not infer temporal identity" in item for item in payload["warnings"])
    assert any("distinct semantic landmarks" in item for item in payload["warnings"])


def test_reefvision_pose_import_rejects_source_video_hash_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Pose hash mismatch")
    video = _pose_video(client, str(project["id"]), monkeypatch)
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    labels = _external_labels(
        str(video["sha256"]),
        include_provenance=True,
        source_sha256="f" * 64,
    )
    monkeypatch.setattr(
        PoseInteroperabilityService,
        "_load_labels",
        lambda *_args, **_kwargs: labels,
    )

    response = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={
            "format": "slp",
            "label_class_id": str(label_classes[0]["id"]),
        },
        files={"file": ("pose.slp", io.BytesIO(b"external-pose"), "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "does not match the target video" in response.json()["detail"]


def test_ultralytics_pose_import_rejects_zip_traversal(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.txt", "unsafe")
        archive.writestr("data.yaml", "path: .\n")

    with pytest.raises(ValidationError, match="unsafe archive path"):
        PoseInteroperabilityService._extract_ultralytics_zip(
            payload.getvalue(),
            tmp_path / "dataset",
        )


def test_reefvision_pose_import_rejects_duplicate_live_source_tracks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Pose duplicate source")
    video = _pose_video(client, str(project["id"]), monkeypatch)
    existing_track_id = _persist_pose_track(client, project, video)
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    labels = _external_labels(str(video["sha256"]), include_provenance=True)
    provenance = cast(
        dict[str, object],
        labels.provenance["reefvision_pose_interoperability"],
    )
    provenance["source_video_id"] = video["id"]
    provenance["tracks"] = {
        "animal-7": {
            "video_track_id": existing_track_id,
            "track_number": 1,
        }
    }
    monkeypatch.setattr(
        PoseInteroperabilityService,
        "_load_labels",
        lambda *_args, **_kwargs: labels,
    )

    response = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={
            "format": "slp",
            "label_class_id": str(label_classes[0]["id"]),
        },
        files={"file": ("pose.slp", io.BytesIO(b"external-pose"), "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "duplicate scientific records" in response.json()["detail"]


def test_coco_pose_import_rejects_unsafe_image_paths() -> None:
    payload = json.dumps(
        {
            "images": [{"id": 1, "file_name": "../outside.png"}],
            "annotations": [],
            "categories": [],
        }
    ).encode("utf-8")

    with pytest.raises(ValidationError, match="unsafe archive path"):
        PoseInteroperabilityService._validate_coco_paths(payload)
