"""Seed three generated, disjoint recordings through the exact disposable API."""

from __future__ import annotations

import argparse
import json
import math
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np


def checked(response: httpx.Response, status: int) -> Any:
    if response.status_code != status:
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path}: "
            f"{response.status_code} {response.text[:1000]}"
        )
    return response.json()


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def render(output: Path, seed: int, count: int) -> list[dict]:
    """Render the same moving jaw marker controls as the source known-answer benchmark."""
    random = np.random.default_rng(seed)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 64))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not generate the fixture recording")
    frames = []
    try:
        phase = float(random.uniform(0, 2 * math.pi))
        for frame in range(count):
            cycle = (frame + seed % 5) % 10
            gap = round(12 - 5 * math.cos(2 * math.pi * cycle / 10))
            x = round(32 + 13 * math.sin(phase + frame / 7) + 3 * math.sin(frame / 2))
            y = round(33 + 13 * math.cos(phase + frame / 9))
            brightness = int(random.integers(12, 38))
            image = random.integers(brightness, brightness + 13, (64, 96, 3), dtype=np.uint8)
            cv2.line(image, (x, y), (x + gap, y), (74, 72, 70), 2)
            cv2.circle(image, (x, y), 5, (45, 228, 245), -1)
            cv2.circle(image, (x + gap, y), 4, (230, 240, 78), -1)
            writer.write(image)
            frames.append(
                {
                    "frame": frame,
                    "timestamp_seconds": frame / 10,
                    "bbox": [x - 7, y - 7, gap + 14, 14],
                    "pose_observations": [
                        {
                            "id": f"{key}-{frame}",
                            "landmark_id": key,
                            "semantic_label": name,
                            "occurrence_index": 0,
                            "x": point,
                            "y": y,
                            "status": "visible",
                            "source": "manual",
                        }
                        for key, name, point in (("jaw-a", "Jaw A", x), ("jaw-b", "Jaw B", x + gap))
                    ],
                }
            )
    finally:
        writer.release()
    return frames


def freeze_reviewed_dataset(
    http: httpx.Client,
    project: str,
    video: dict,
    frames: list[dict],
    label_id: str,
    schema: dict,
    seed: int,
) -> dict:
    route = f"/videos/{video['id']}/tracks"
    track_body = {"label_class_id": label_id, "keyframes": frames, "status": "verified"}
    created = checked(http.post(route, json=track_body), 201)
    track_route = f"/video-tracks/{created['id']}"
    track = checked(
        http.put(
            track_route,
            json={
                **track_body,
                "base_revision": created["revision"],
                "pose_schema_binding": {
                    "schema_id": schema["id"],
                    "schema_revision": schema["revision"],
                    "content_hash": schema["content_hash"],
                },
            },
        ),
        200,
    )
    checked(
        http.post(
            f"{track_route}/pose-temporal-associations",
            json={
                "max_gap_frames": 2,
                "max_normalized_displacement": 1.0,
                "confirm_after_observations": 2,
            },
        ),
        200,
    )
    name = f"recording-{seed}"
    review_round = checked(
        http.post(
            f"{project}/pose-active-learning-rounds",
            json={
                "name": name,
                "video_id": video["id"],
                "track_ids": [track["id"]],
                "grouping": {"recording_id": name, "animal_id": f"animal-{seed}"},
                "requested_size": len(frames),
                "minimum_frame_spacing": 0,
            },
        ),
        201,
    )
    round_route = f"/pose-active-learning-rounds/{review_round['id']}"
    candidates = checked(http.get(f"{round_route}/candidates"), 200)
    if len(candidates) != len(frames):
        raise RuntimeError("Generated dataset did not expose all reviewed frames")
    for candidate in candidates:
        review = checked(
            http.put(
                f"/pose-active-learning-candidates/{candidate['id']}/review",
                json={
                    "action": "verify",
                    "reviewed_by": "synthetic-known-answer",
                    "note": "Fixture points are the centers of the rendered markers",
                },
            ),
            200,
        )
        if review["review_status"] != "verified":
            raise RuntimeError("Fixture candidate failed to become verified")
    dataset = checked(
        http.post(
            f"{round_route}/training-dataset",
            json={
                "name": name,
                "created_by": "synthetic-known-answer",
            },
        ),
        201,
    )
    return {key: dataset[key] for key in ("id", "name", "manifest_sha256", "item_count")}


def verify_profile(
    http: httpx.Client, profile: Path, marker: str, version: str, schema: str
) -> None:
    actual_marker = (
        (profile / ".reefvision-clean-install-acceptance").read_text(encoding="utf-8-sig").strip()
    )
    runtime = checked(http.get("/system/version"), 200)
    migration = checked(http.get("/system/migrations/status"), 200)
    if (
        actual_marker != marker
        or runtime["application_version"] != version
        or runtime["current_schema_revision"] != schema
        or runtime["expected_schema_revision"] != schema
        or runtime["safe_mode"]
        or migration["schema_status"] != "up_to_date"
        or Path(runtime["data_dir"]).resolve(strict=True) != profile
        or Path(runtime["database_path"]).resolve(strict=True) != profile / "reefvision.db"
    ):
        raise RuntimeError(
            "The API does not own the exact disposable fixture profile, version and schema"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (
        not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}/api/v1", args.api)
        or not re.fullmatch(r"[a-f0-9]{40}", args.source)
        or not args.marker
    ):
        parser.error("An exact source, isolated fixture marker and IPv4 loopback API are required")
    profile = args.profile.resolve(strict=True)
    output = args.output.resolve()
    if output == profile or output.is_relative_to(profile):
        parser.error("Fixture generation output must be a separate scratch directory")
    with httpx.Client(base_url=args.api, trust_env=False, timeout=30) as http:
        verify_profile(http, profile, args.marker, args.version, args.schema)
        output.mkdir(exist_ok=False)
        project = checked(
            http.post("/projects", json={"name": f"Generated Guided ReefPose {args.marker[:12]}"}),
            201,
        )
        base = f"/projects/{project['id']}"
        label = checked(
            http.post(
                f"{base}/classes",
                json={
                    "name": "animal",
                    "class_index": 0,
                    "display_color": "#39b8c1",
                },
            ),
            201,
        )
        schema = checked(
            http.post(
                f"{base}/pose-schemas",
                json={
                    "name": "Rendered jaw markers",
                    "landmarks": [
                        {"id": "jaw-a", "name": "Jaw A"},
                        {"id": "jaw-b", "name": "Jaw B"},
                    ],
                    "edges": [{"from_id": "jaw-a", "to_id": "jaw-b"}],
                },
            ),
            201,
        )
        datasets = []
        sources = []
        for seed, count, split in ((101, 96, "train"), (203, 48, "validation"), (503, 24, "test")):
            clip = output / f"recording-{seed}.mp4"
            frames = render(clip, seed, count)
            content = clip.read_bytes()
            video = checked(
                http.post(
                    f"{base}/imports/videos", files={"file": (clip.name, content, "video/mp4")}
                ),
                201,
            )
            if video["sha256"] != sha256(content).hexdigest() or video["frame_count"] != count:
                raise RuntimeError("The imported original bytes or frame count changed")
            recording = {
                key: video[key] for key in ("id", "original_filename", "sha256", "frame_count")
            }
            sources.append({"split": split, "recording": recording})
            if split != "test":
                datasets.append(
                    freeze_reviewed_dataset(http, base, video, frames, label["id"], schema, seed)
                )
        truth = {
            "sources": [
                {
                    **sources[-1],
                    "frames": [
                        {
                            "frame_index": frame["frame"],
                            "target_points": [
                                {key: point[key] for key in ("landmark_id", "x", "y")}
                                for point in frame["pose_observations"]
                            ],
                        }
                        for frame in frames
                    ],
                }
            ]
        }
        truth_hash = sha256(
            json.dumps(truth, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        save_json(
            output / "oracle.json",
            {"frozen_evaluation": {"manifest": truth, "manifest_sha256": truth_hash}},
        )
        save_json(
            output / "fixture.json",
            {
                "source_commit": args.source,
                "profile_marker": args.marker,
                "project": {key: project[key] for key in ("id", "name")},
                "datasets": datasets,
                "test_video": sources[-1]["recording"],
                "generated_sources": sources,
                "source_oracle_sha256": truth_hash,
            },
        )


if __name__ == "__main__":
    main()
