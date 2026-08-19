"""Benchmark ReefVision ByteTrack and BoT-SORT against manually scored real footage.

The caller supplies:
- a real video,
- a trusted Ultralytics detection checkpoint whose class names match the manual truth,
- a JSON ground-truth sidecar using ``reefvision-tracking-ground-truth-0001``.

The harness imports all three into isolated ReefVision state, creates verified manual
tracks, runs the production video-tracking job twice with identical detector settings
except for the tracker configuration, benchmarks both runs through ReefVision's own
tracking-evaluation service, restarts the application, and verifies the benchmark is
reproducible from persisted tracks.

A completed benchmark is software/scientific execution evidence; poor MOTA, recall,
precision, or identity metrics remain valid scientific results rather than software
failures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import Job, VideoTrack
from reefvision.jobs.video_tracking import process_video_tracking_job
from reefvision.main import create_app
from reefvision.ml.providers import UltralyticsDetectionProvider

SCHEMA_VERSION = "reefvision-tracking-ground-truth-0001"
TRACKERS = {
    "ByteTrack": "bytetrack.yaml",
    "BoT-SORT": "botsort.yaml",
}


def require(response: Any, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"API {response.request.method} {response.url}: {response.text}")
    return dict(response.json())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_bbox(raw: Any, *, context: str) -> list[float]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise RuntimeError(f"{context} bbox must contain [x, y, width, height]")
    try:
        values = [float(value) for value in raw]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{context} bbox contains non-numeric values") from exc
    x, y, width, height = values
    if any(not math.isfinite(value) for value in values):
        raise RuntimeError(f"{context} bbox contains non-finite values")
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise RuntimeError(f"{context} bbox requires nonnegative origin and positive size")
    return values


def load_ground_truth(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ground-truth JSON could not be read: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"Ground truth must use schema_version {SCHEMA_VERSION!r}")
    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise RuntimeError("Ground truth must contain at least one manually scored track")

    normalized_tracks: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for index, raw_track in enumerate(tracks):
        if not isinstance(raw_track, dict):
            raise RuntimeError(f"Ground-truth track {index} must be an object")
        class_name = str(raw_track.get("class_name", "")).strip()
        if not class_name:
            raise RuntimeError(f"Ground-truth track {index} is missing class_name")
        try:
            track_number = int(raw_track.get("track_number"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Ground-truth track {index} has invalid track_number") from exc
        if track_number < 1 or track_number in seen_numbers:
            raise RuntimeError("Ground-truth track numbers must be unique positive integers")
        seen_numbers.add(track_number)
        raw_keyframes = raw_track.get("keyframes")
        if not isinstance(raw_keyframes, list) or not raw_keyframes:
            raise RuntimeError(f"Ground-truth track {track_number} has no keyframes")
        keyframes: list[dict[str, Any]] = []
        seen_frames: set[int] = set()
        previous_frame = -1
        for raw_keyframe in raw_keyframes:
            if not isinstance(raw_keyframe, dict):
                raise RuntimeError(f"Track {track_number} keyframe must be an object")
            try:
                frame = int(raw_keyframe.get("frame"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Track {track_number} contains invalid frame") from exc
            if frame < 0 or frame in seen_frames or frame <= previous_frame:
                raise RuntimeError(
                    f"Track {track_number} keyframes must use unique ascending frames"
                )
            seen_frames.add(frame)
            previous_frame = frame
            keyframes.append(
                {
                    "frame": frame,
                    "bbox": _validated_bbox(
                        raw_keyframe.get("bbox"),
                        context=f"Track {track_number} frame {frame}",
                    ),
                }
            )
        normalized_tracks.append(
            {
                "track_number": track_number,
                "class_name": class_name,
                "keyframes": keyframes,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "video_sha256": (
            str(payload["video_sha256"]).strip().casefold()
            if payload.get("video_sha256")
            else None
        ),
        "notes": str(payload.get("notes", "")).strip() or None,
        "tracks": normalized_tracks,
    }


def _benchmark_payload(
    *,
    ground_truth_track_ids: list[str],
    job_ids: dict[str, str],
    iou_threshold: float,
) -> dict[str, Any]:
    return {
        "ground_truth_track_ids": ground_truth_track_ids,
        "candidates": [
            {"name": name, "source_job_id": job_ids[name]}
            for name in ("ByteTrack", "BoT-SORT")
        ],
        "iou_threshold": iou_threshold,
        "class_aware": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--detector-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--biological-context", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--evaluation-iou", type=float, default=0.5)
    parser.add_argument("--minimum-track-frames", type=int, default=2)
    args = parser.parse_args()

    video_path = args.video.resolve()
    truth_path = args.ground_truth.resolve()
    checkpoint_path = args.detector_checkpoint.resolve()
    output = args.output.resolve()
    state = args.state.resolve() if args.state else output / "reefvision-data"
    for required in (video_path, truth_path, checkpoint_path):
        if not required.is_file():
            raise RuntimeError(f"Required acceptance input does not exist: {required}")
    if output.exists():
        raise RuntimeError(f"Acceptance output already exists: {output}")
    output.mkdir(parents=True)
    state.mkdir(parents=True, exist_ok=False)

    truth = load_ground_truth(truth_path)
    video_hash = sha256(video_path)
    declared_hash = truth.get("video_sha256")
    if declared_hash and declared_hash != video_hash:
        raise RuntimeError(
            "Manual ground truth video_sha256 does not match the supplied source video"
        )

    detector_metadata = UltralyticsDetectionProvider().inspect_model(checkpoint_path)
    detector_labels = [str(label) for label in detector_metadata.class_labels]
    labels_by_casefold = {label.strip().casefold(): label for label in detector_labels}
    truth_classes = {str(track["class_name"]).strip().casefold() for track in truth["tracks"]}
    missing_classes = sorted(truth_classes - set(labels_by_casefold))
    if missing_classes:
        raise RuntimeError(
            "Ground truth uses class names absent from detector checkpoint: "
            + ", ".join(missing_classes)
        )

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; requested tracking acceptance cannot pass")

    settings = Settings(
        env="acceptance",
        data_dir=state,
        database_url=f"sqlite:///{(state / 'reefvision.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
        allow_unsafe_pickled_models=True,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    started = time.perf_counter()

    project: dict[str, Any]
    video: dict[str, Any]
    registered_model: dict[str, Any]
    ground_truth_track_ids: list[str] = []
    job_ids: dict[str, str] = {}
    job_results: dict[str, dict[str, Any]] = {}
    tracker_durations: dict[str, float] = {}
    benchmark: dict[str, Any]

    with TestClient(app) as client:
        project = require(
            client.post(
                "/api/v1/projects",
                json={"name": "Real fish tracking acceptance", "template": "blank"},
            ),
            201,
        )
        class_ids: dict[str, str] = {}
        for class_index, class_name in enumerate(detector_labels):
            label = require(
                client.post(
                    f"/api/v1/projects/{project['id']}/classes",
                    json={
                        "class_index": class_index,
                        "display_order": class_index,
                        "name": class_name,
                        "description": "Imported detector class for tracking acceptance",
                        "display_color": "#4C9A8A",
                    },
                ),
                201,
            )
            class_ids[class_name.strip().casefold()] = label["id"]

        registered_model = require(
            client.post(
                f"/api/v1/projects/{project['id']}/models/register",
                files={
                    "file": (
                        checkpoint_path.name,
                        checkpoint_path.read_bytes(),
                        "application/octet-stream",
                    )
                },
                data={
                    "purpose": "detector",
                    "provider_name": "ultralytics",
                    "display_name": "Real tracking acceptance detector",
                    "notes": f"Trusted local checkpoint SHA-256 {sha256(checkpoint_path)}",
                },
            ),
            200,
        )
        mapping = dict(registered_model.get("class_map_json") or {}).get("mapping", {})
        if any(mapping.get(label) is None for label in detector_labels):
            raise RuntimeError("Registered detector did not map every model class into the project")

        video = require(
            client.post(
                f"/api/v1/projects/{project['id']}/imports/videos",
                files={
                    "file": (
                        video_path.name,
                        video_path.read_bytes(),
                        "video/mp4",
                    )
                },
            ),
            201,
        )
        if video["sha256"] != video_hash:
            raise RuntimeError("Managed video checksum does not match source video")

        for track in truth["tracks"]:
            keyframes = list(track["keyframes"])
            if keyframes[-1]["frame"] >= int(video["frame_count"]):
                raise RuntimeError(
                    f"Ground-truth track {track['track_number']} references frame outside video"
                )
            class_key = str(track["class_name"]).strip().casefold()
            created = require(
                client.post(
                    f"/api/v1/videos/{video['id']}/tracks",
                    json={
                        "label_class_id": class_ids[class_key],
                        "track_number": track["track_number"],
                        "geometry_kind": "bbox",
                        "keyframes": keyframes,
                        "interpolation": "linear",
                        "status": "verified",
                    },
                ),
                201,
            )
            ground_truth_track_ids.append(created["id"])

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        for name, tracker_file in TRACKERS.items():
            queued = require(
                client.post(
                    f"/api/v1/videos/{video['id']}/tracking-jobs",
                    json={
                        "model_id": registered_model["id"],
                        "tracker": tracker_file,
                        "confidence": args.confidence,
                        "iou": args.iou,
                        "device": args.device,
                        "minimum_track_frames": args.minimum_track_frames,
                    },
                ),
                200,
            )
            job_ids[name] = queued["id"]
            tracker_started = time.perf_counter()
            ok = process_video_tracking_job(settings, app.state.session_factory, queued["id"])
            tracker_durations[name] = time.perf_counter() - tracker_started
            with app.state.session_factory() as session:
                job = session.get(Job, queued["id"])
                if job is None:
                    raise RuntimeError(f"{name} tracking job disappeared")
                job_results[name] = {
                    "status": job.status,
                    "error_message": job.error_message,
                    **dict(job.result_json),
                }
            if not ok or job_results[name]["status"] != "succeeded":
                raise RuntimeError(
                    f"{name} production tracking failed: {job_results[name]['error_message']}"
                )
            if job_results[name].get("unmapped_labels"):
                raise RuntimeError(
                    f"{name} produced unmapped detector labels: "
                    f"{job_results[name]['unmapped_labels']}"
                )

        benchmark = require(
            client.post(
                f"/api/v1/videos/{video['id']}/tracking-benchmark",
                json=_benchmark_payload(
                    ground_truth_track_ids=ground_truth_track_ids,
                    job_ids=job_ids,
                    iou_threshold=args.evaluation_iou,
                ),
            ),
            200,
        )
        result_names = {item["name"] for item in benchmark["results"]}
        if result_names != set(TRACKERS):
            raise RuntimeError("Tracking benchmark did not return both tracker candidates")
        with app.state.session_factory() as session:
            source_track_counts = {
                name: len(
                    list(
                        session.scalars(
                            select(VideoTrack).where(
                                VideoTrack.video_id == video["id"],
                                VideoTrack.source_job_id == job_id,
                                VideoTrack.deleted_at.is_(None),
                            )
                        )
                    )
                )
                for name, job_id in job_ids.items()
            }

    app.state.engine.dispose()

    restart_app = create_app(settings)
    restart_started = time.perf_counter()
    with TestClient(restart_app) as restart_client:
        restart_benchmark = require(
            restart_client.post(
                f"/api/v1/videos/{video['id']}/tracking-benchmark",
                json=_benchmark_payload(
                    ground_truth_track_ids=ground_truth_track_ids,
                    job_ids=job_ids,
                    iou_threshold=args.evaluation_iou,
                ),
            ),
            200,
        )
    restart_duration = time.perf_counter() - restart_started
    restart_app.state.engine.dispose()

    benchmark_stable = (
        restart_benchmark["winner"] == benchmark["winner"]
        and restart_benchmark["ground_truth_track_ids"] == benchmark["ground_truth_track_ids"]
        and [item["name"] for item in restart_benchmark["results"]]
        == [item["name"] for item in benchmark["results"]]
    )
    acceptance = "PASS" if benchmark_stable else "FAIL"
    peak_vram = torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0
    report = {
        "acceptance": acceptance,
        "commit_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Real video tracking benchmark against manually scored ground truth; "
            "metric quality is reported, not thresholded into a scientific success claim"
        ),
        "inputs": {
            "video": str(video_path),
            "video_sha256": video_hash,
            "ground_truth": str(truth_path),
            "ground_truth_sha256": sha256(truth_path),
            "ground_truth_schema": SCHEMA_VERSION,
            "detector_checkpoint": str(checkpoint_path),
            "detector_sha256": sha256(checkpoint_path),
            "detector_labels": detector_labels,
            "biological_context": args.biological_context,
            "manual_track_count": len(ground_truth_track_ids),
            "manual_observation_count": sum(
                len(track["keyframes"]) for track in truth["tracks"]
            ),
        },
        "reefvision": {
            "project_id": project["id"],
            "video_id": video["id"],
            "model_id": registered_model["id"],
            "ground_truth_track_ids": ground_truth_track_ids,
        },
        "tracking_settings": {
            "confidence": args.confidence,
            "iou": args.iou,
            "evaluation_iou": args.evaluation_iou,
            "device": args.device,
            "minimum_track_frames": args.minimum_track_frames,
        },
        "hardware": {
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "ultralytics": __import__("ultralytics").__version__,
            "peak_allocated_vram_bytes": peak_vram,
        },
        "jobs": {
            name: {
                "job_id": job_ids[name],
                "tracker": TRACKERS[name],
                "duration_seconds": tracker_durations[name],
                "persisted_track_count": source_track_counts[name],
                "result": job_results[name],
            }
            for name in TRACKERS
        },
        "benchmark": benchmark,
        "restart": {
            "passed": benchmark_stable,
            "duration_seconds": restart_duration,
            "benchmark": restart_benchmark,
        },
        "total_duration_seconds": time.perf_counter() - started,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if acceptance == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
