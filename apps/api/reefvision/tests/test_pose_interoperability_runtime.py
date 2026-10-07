from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.ml.sleap_nn_provider import SLEAP_IO_SUPPORTED_VERSION
from reefvision.services.pose_interoperability import PoseInteroperabilityService
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_interoperability import _persist_pose_track


def _real_sleap_io() -> Any:
    try:
        installed = version("sleap-io")
    except PackageNotFoundError:
        pytest.skip(f"optional sleap-io {SLEAP_IO_SUPPORTED_VERSION} is not installed")
    if installed != SLEAP_IO_SUPPORTED_VERSION:
        pytest.skip(f"requires sleap-io {SLEAP_IO_SUPPORTED_VERSION}; found {installed}")
    return pytest.importorskip("sleap_io")


def _runtime_labels(tmp_path: Path, sio: Any) -> Any:
    import imageio.v3 as iio

    video_path = tmp_path / "runtime.mp4"
    video_frames = np.zeros((6, 48, 64, 3), dtype=np.uint8)
    for frame_index in range(6):
        video_frames[frame_index, :, :, :] = frame_index * 10
    iio.imwrite(
        video_path,
        video_frames,
        fps=10,
        codec="libx264",
        macro_block_size=1,
    )

    video = sio.Video.from_filename(str(video_path), keep_open=False)
    skeleton = sio.Skeleton(
        nodes=["bell_center", "tentacle__1", "tentacle__2"],
        name="ReefVision canonical pose",
    )
    track = sio.Track(name="reefvision-track-7-runtime")

    frames = []
    for frame_index, offset in ((1, 0.0), (4, 3.0)):
        points = np.asarray(
            [
                [10.0 + offset, 12.0 + offset, 1.0],
                [20.0 + offset, 24.0 + offset, 0.0],
                [30.0 + offset, 32.0 + offset, 1.0],
            ],
            dtype=np.float64,
        )
        instance = sio.PredictedInstance.from_numpy(
            points,
            skeleton=skeleton,
            point_scores=np.asarray([0.95, 0.60, 0.85], dtype=np.float64),
            score=0.90,
            track=track,
            tracking_score=None,
        )
        frames.append(
            sio.LabeledFrame(
                video=video,
                frame_idx=frame_index,
                instances=[instance],
            )
        )

    return sio.Labels(
        labeled_frames=frames,
        videos=[video],
        skeletons=[skeleton],
        tracks=[track],
        provenance={
            "reefvision_pose_interoperability": {
                "schema_version": "reefvision-pose-interoperability-0001",
                "source_video_id": "runtime-video",
                "source_video_sha256": "a" * 64,
                "source_filename": "runtime.mp4",
                "frame_index_base": 0,
                "coordinate_base": 0,
                "pose_schema": {
                    "schema_version": "pose-landmarks-0001",
                    "schema_id": "runtime-schema",
                    "schema_revision": 1,
                    "groups": [
                        {"name": "bell_center", "count": 1},
                        {"name": "tentacle", "count": 2},
                    ],
                    "expanded_labels": [
                        "bell_center",
                        "tentacle",
                        "tentacle",
                    ],
                    "keypoint_count": 3,
                    "allows_repeated_labels": True,
                    "content_hash": "b" * 64,
                },
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
                "tracks": {
                    "reefvision-track-7-runtime": {
                        "video_track_id": "runtime-track",
                        "track_number": 7,
                    }
                },
            }
        },
    )


def _native_or_bundle_bytes(
    tmp_path: Path,
    sio: Any,
    labels: Any,
    exchange_format: str,
) -> tuple[bytes, str]:
    service = object.__new__(PoseInteroperabilityService)

    if exchange_format == "slp":
        output = tmp_path / "runtime.pose.slp"
        sio.save_slp(labels, str(output), embed=False, verbose=False)
        return output.read_bytes(), output.name

    bundle = tmp_path / f"{exchange_format}-bundle"
    bundle.mkdir()
    manifest = service._bundle_manifest(labels, exchange_format)

    if exchange_format == "nwb":
        output = bundle / "runtime.pose.nwb"
        service._save_nwb_predictions(
            sio,
            labels,
            output,
            frame_count=6,
            fps=10.0,
        )
    elif exchange_format == "coco":
        output = bundle / "runtime.pose.coco.json"
        sio.save_coco(labels, str(output), visibility_encoding="ternary")
    elif exchange_format == "dlc_csv":
        output = bundle / "runtime.pose.dlc.csv"
        sio.save_csv(
            labels,
            str(output),
            format="dlc",
            include_score=True,
            scorer="ReefVision",
            save_metadata=False,
        )
    elif exchange_format == "ultralytics_pose":
        output = bundle / "dataset"
        sio.save_ultralytics(
            labels,
            str(output),
            split_ratios={"train": 1.0},
            class_id=0,
            verbose=False,
            use_multiprocessing=False,
        )
        bundle = output
    else:
        raise AssertionError(exchange_format)

    service._write_bundle_manifest(bundle, manifest)
    return service._zip_directory(bundle), f"runtime.{exchange_format}.zip"


@pytest.mark.integration
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.parametrize(
    "exchange_format",
    ["slp", "nwb", "coco", "dlc_csv", "ultralytics_pose"],
)
def test_real_sleap_io_round_trip_preserves_reefvision_pose_identity(
    tmp_path: Path,
    exchange_format: str,
) -> None:
    sio = _real_sleap_io()
    labels = _runtime_labels(tmp_path, sio)
    content, filename = _native_or_bundle_bytes(
        tmp_path,
        sio,
        labels,
        exchange_format,
    )

    service = object.__new__(PoseInteroperabilityService)
    restored_labels = service._load_labels(
        exchange_format,
        content,
        filename,
    )
    imported_schema = service._imported_schema(restored_labels)
    target_video = SimpleNamespace(width_px=64, height_px=48, frame_count=6)

    imported_tracks, warnings = service._import_tracks_from_labels(
        restored_labels,
        imported_schema,
        target_video,  # type: ignore[arg-type]
        exchange_format,
    )

    assert imported_schema.expanded_labels == (
        "bell_center",
        "tentacle",
        "tentacle",
    )
    assert len(imported_tracks) == 1
    assert imported_tracks[0].external_track_name == "reefvision-track-7-runtime"
    assert [frame.frame for frame in imported_tracks[0].keyframes] == [1, 4]
    assert [
        observation.semantic_label
        for observation in imported_tracks[0].keyframes[0].pose_observations or []
    ] == ["bell_center", "tentacle", "tentacle"]
    assert not any("mapped sequentially" in warning for warning in warnings)


@pytest.fixture
def real_service_pose(client: TestClient, tmp_path: Path):
    import imageio.v3 as iio

    path = tmp_path / "service-runtime.mp4"
    frames = np.zeros((6, 128, 208, 3), dtype=np.uint8)
    for index in range(6):
        frames[index, :, :, 0] = index * 20
        frames[index, 10:30, 10:30, 1] = 180
    iio.imwrite(
        path,
        frames,
        fps=10,
        codec="libx264",
        macro_block_size=1,
    )
    project = create_project(client, "Real interoperability service")
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": (path.name, path.read_bytes(), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    video = response.json()
    track_id = _persist_pose_track(client, project, video)
    return project, video, track_id


@pytest.mark.integration
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.parametrize(
    "exchange_format",
    ["slp", "nwb", "coco", "dlc_csv", "ultralytics_pose"],
)
def test_real_service_export_import_round_trip(
    client: TestClient,
    real_service_pose,
    tmp_path: Path,
    exchange_format: str,
) -> None:
    project, video, track_id = real_service_pose
    response = client.get(
        f"/api/v1/videos/{video['id']}/pose-interoperability/export",
        params={"format": exchange_format},
    )
    assert response.status_code == 200, response.text

    if exchange_format == "slp":
        filename = "runtime.pose.slp"
        assert not zipfile.is_zipfile(io.BytesIO(response.content))
    else:
        filename = f"runtime.{exchange_format}.zip"
        assert zipfile.is_zipfile(io.BytesIO(response.content))
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest_names = [
                name
                for name in archive.namelist()
                if name.endswith("reefvision-pose-manifest.json")
            ]
            assert len(manifest_names) == 1
            manifest = json.loads(archive.read(manifest_names[0]))
            assert manifest["schema_version"] == "reefvision-pose-bundle-0001"
            assert manifest["format"] == exchange_format
            assert manifest["frames"][0]["reefvision_frame_index"] == 4

    with client.app.state.session_factory() as session:
        track = session.get(VideoTrack, track_id)
        assert track is not None
        track.deleted_at = datetime.now(UTC)
        session.commit()

    restored = client.post(
        f"/api/v1/videos/{video['id']}/pose-interoperability/import",
        params={
            "format": exchange_format,
            "label_class_id": project["label_classes"][0]["id"],
            "confirm_frame_mapping": True,
        },
        files={
            "file": (
                filename,
                response.content,
                "application/octet-stream",
            )
        },
    )
    assert restored.status_code == 201, restored.text
    payload = restored.json()
    assert payload["used_reefvision_provenance"] is True
    assert payload["track_count"] == 1
    assert payload["keyframe_count"] == 1

    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks").json()
    imported = next(item for item in tracks if item["id"] in payload["created_track_ids"])
    frame = imported["keyframes_json"][0]
    assert frame["frame"] == 4
    assert frame["confidence"] == pytest.approx(0.9, abs=1e-6)
    observations = frame["pose_observations"]
    assert observations[0]["semantic_label"] == "bell_center"
    assert observations[0]["x"] == pytest.approx(15.0, abs=0.001)
    assert observations[1]["semantic_label"] == "tentacle"
    assert observations[1]["occurrence_index"] == 0
    assert observations[1]["x"] == pytest.approx(17.0, abs=0.001)
    assert observations[1]["status"] == "occluded"
    assert observations[2]["semantic_label"] == "tentacle"
    assert observations[2]["occurrence_index"] == 1
    assert observations[2]["status"] == "absent"


@pytest.mark.integration
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.filterwarnings("ignore::ResourceWarning")
def test_real_slp_export_remains_self_contained_after_source_removal(
    client: TestClient,
    real_service_pose,
    tmp_path: Path,
) -> None:
    import sleap_io as sio

    _, video, _ = real_service_pose
    with client.app.state.session_factory() as session:
        asset = session.get(VideoAsset, video["id"])
        assert asset is not None
        source = resolve_managed_project_path(
            client.app.state.settings,
            asset.managed_path,
        )
    expected = sio.Video.from_filename(
        str(source),
        grayscale=False,
        keep_open=False,
    )[4]

    response = client.get(
        f"/api/v1/videos/{video['id']}/pose-interoperability/export",
        params={"format": "slp"},
    )
    assert response.status_code == 200, response.text

    output = tmp_path / "self-contained.slp"
    output.write_bytes(response.content)
    source.unlink()

    labels = sio.load_slp(str(output))
    np.testing.assert_array_equal(labels.videos[0][4], expected)
    np.testing.assert_allclose(
        labels.labeled_frames[0].instances[0].points["xy"][:2],
        [[15, 16], [17, 18]],
    )
