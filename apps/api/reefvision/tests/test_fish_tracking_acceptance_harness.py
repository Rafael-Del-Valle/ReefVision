from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = Path(__file__).resolve().parents[4] / "scripts" / "acceptance_fish_tracking.py"
    spec = importlib.util.spec_from_file_location("acceptance_fish_tracking", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_truth(path: Path, tracks: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "reefvision-tracking-ground-truth-0001",
                "video_sha256": "a" * 64,
                "tracks": tracks,
            }
        ),
        encoding="utf-8",
    )


def test_ground_truth_parser_accepts_verified_bbox_tracks(harness, tmp_path: Path) -> None:
    path = tmp_path / "truth.json"
    _write_truth(
        path,
        [
            {
                "track_number": 1,
                "class_name": "Fish",
                "keyframes": [
                    {"frame": 0, "bbox": [10, 20, 30, 40]},
                    {"frame": 5, "bbox": [15, 22, 30, 40]},
                ],
            }
        ],
    )

    payload = harness.load_ground_truth(path)

    assert payload["schema_version"] == "reefvision-tracking-ground-truth-0001"
    assert payload["tracks"][0]["class_name"] == "Fish"
    assert payload["tracks"][0]["keyframes"][1]["frame"] == 5


def test_ground_truth_parser_rejects_nonascending_frames(harness, tmp_path: Path) -> None:
    path = tmp_path / "truth.json"
    _write_truth(
        path,
        [
            {
                "track_number": 1,
                "class_name": "Fish",
                "keyframes": [
                    {"frame": 5, "bbox": [10, 20, 30, 40]},
                    {"frame": 4, "bbox": [15, 22, 30, 40]},
                ],
            }
        ],
    )

    with pytest.raises(RuntimeError, match="unique ascending frames"):
        harness.load_ground_truth(path)


def test_ground_truth_parser_rejects_invalid_bbox(harness, tmp_path: Path) -> None:
    path = tmp_path / "truth.json"
    _write_truth(
        path,
        [
            {
                "track_number": 1,
                "class_name": "Fish",
                "keyframes": [{"frame": 0, "bbox": [10, 20, -30, 40]}],
            }
        ],
    )

    with pytest.raises(RuntimeError, match="positive size"):
        harness.load_ground_truth(path)


def test_benchmark_payload_uses_source_jobs_for_both_trackers(harness) -> None:
    payload = harness._benchmark_payload(
        ground_truth_track_ids=["truth-track"],
        job_ids={"ByteTrack": "byte-job", "BoT-SORT": "bot-job"},
        iou_threshold=0.5,
    )

    assert payload["ground_truth_track_ids"] == ["truth-track"]
    assert payload["candidates"] == [
        {"name": "ByteTrack", "source_job_id": "byte-job"},
        {"name": "BoT-SORT", "source_job_id": "bot-job"},
    ]
