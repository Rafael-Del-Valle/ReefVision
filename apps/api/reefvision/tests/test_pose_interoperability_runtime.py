from __future__ import annotations

import io
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PIL import Image

from reefvision.ml.sleap_nn_provider import SLEAP_IO_SUPPORTED_VERSION
from reefvision.services.pose_interoperability import PoseInteroperabilityService


def _real_sleap_io() -> Any:
    try:
        installed = version("sleap-io")
    except PackageNotFoundError:
        pytest.skip(
            f"optional sleap-io {SLEAP_IO_SUPPORTED_VERSION} is not installed"
        )
    if installed != SLEAP_IO_SUPPORTED_VERSION:
        pytest.skip(
            f"requires sleap-io {SLEAP_IO_SUPPORTED_VERSION}; found {installed}"
        )
    return pytest.importorskip("sleap_io")


def _runtime_labels(tmp_path: Path, sio: Any) -> Any:
    image_paths: list[str] = []
    for frame_index in range(6):
        path = tmp_path / f"frame_{frame_index:04d}.png"
        Image.new(
            "RGB",
            (64, 48),
            (frame_index * 10, frame_index * 10, frame_index * 10),
        ).save(path)
        image_paths.append(str(path))

    video = sio.Video.from_filename(image_paths, keep_open=False)
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
        sio.save_nwb(labels, output, nwb_format="predictions")
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
