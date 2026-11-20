"""Compare native and temporal ReefPose on a frozen synthetic known-answer design.

Run with a fresh disposable path and an active ReefVision development runtime.
The driver emits its design hash, frozen data and model identities, and the
engineering comparison including unmatched or unscorable events.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from verify_reefpose_temporal_lineage_live import checked, queue_workflow, training_graph

DESIGN = {
    "scientific_context": "synthetic_engineering",
    "rendered_size": [96, 64],
    "fps": 10,
    "roles": {
        "frame_train": [[101, 96]],
        "frame_validation": [[203, 48]],
        "temporal_train": [[303, 36], [311, 36]],
        "temporal_validation": [[407, 36]],
        "test": [[503, 24], [509, 24], [521, 24], [541, 24], [557, 24]],
    },
    "grouping": "one unique recording and animal per seed, across all partitions",
    "frame": {
        "seed": 61,
        "epochs": 24,
        "batch": 12,
        "base_channels": 12,
        "fpn_channels": 24,
        "learning_rate": 0.001,
        "input_height": 64,
        "input_width": 96,
        "workers": 0,
        "selection": "minimum loss on separately frozen validation recording",
    },
    "temporal": {
        "seed": 1337,
        "epochs": 12,
        "batch_size": 16,
        "channels": 16,
        "window_length": 5,
        "context_mode": "causal",
        "selection": "minimum loss on separately frozen validation recording",
    },
    "scoring": {
        "landmark_a_id": "jaw-a",
        "landmark_b_id": "jaw-b",
        "open_threshold_px": 12,
        "close_threshold_px": 9,
        "maximum_gap_seconds": 0.25,
        "onset_tolerance_seconds": 0.25,
        "offset_tolerance_seconds": 0.25,
    },
    "inference": {
        "confidence": 0.0,
        "visibility_probability": "default model 0.5",
        "minimum_track_frames": 1,
    },
    "test_rule": (
        "Render test recordings only after both frame and temporal models "
        "are selected and registered. "
        "Run once with frozen design and retain null/unmatched metrics."
    ),
}


def build_source(
    http: TestClient,
    root: Path,
    base: str,
    label: str,
    schema: dict[str, Any],
    seed: int,
    count: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    random = np.random.default_rng(seed)
    clip = root / f"recording-{seed}.mp4"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 64))
    assert writer.isOpened()
    keyframes = []
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
            keyframes.append(
                {
                    "frame": frame,
                    "timestamp_seconds": frame / 10,
                    "bbox": [x - 7, y - 7, gap + 14, 14],
                    "pose_observations": [
                        {
                            "id": f"{landmark}-{frame}",
                            "landmark_id": landmark,
                            "semantic_label": name,
                            "occurrence_index": 0,
                            "x": center,
                            "y": y,
                            "status": "visible",
                            "source": "manual",
                        }
                        for landmark, name, center in (
                            ("jaw-a", "Jaw A", x),
                            ("jaw-b", "Jaw B", x + gap),
                        )
                    ],
                }
            )
    finally:
        writer.release()
    bytes_ = clip.read_bytes()
    video = checked(
        http.post(f"{base}/imports/videos", files={"file": (clip.name, bytes_, "video/mp4")}), 201
    )
    assert video["sha256"] == sha256(bytes_).hexdigest() and video["frame_count"] == count
    payload = {"label_class_id": label, "keyframes": keyframes, "status": "verified"}
    created = checked(http.post(f"/api/v1/videos/{video['id']}/tracks", json=payload), 201)
    track = checked(
        http.put(
            f"/api/v1/video-tracks/{created['id']}",
            json={
                **payload,
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
    group = {"recording_id": f"recording-{seed}", "animal_id": f"animal-{seed}"}
    return video, track, group


def freeze_frame(
    http: TestClient, base: str, video: dict, track: dict, group: dict, requested: int
) -> dict:
    checked(
        http.post(
            f"/api/v1/video-tracks/{track['id']}/pose-temporal-associations",
            json={
                "max_gap_frames": 2,
                "max_normalized_displacement": 1.0,
                "confirm_after_observations": 2,
            },
        ),
        200,
    )
    picked = checked(
        http.post(
            f"{base}/pose-active-learning-rounds",
            json={
                "name": group["recording_id"],
                "video_id": video["id"],
                "track_ids": [track["id"]],
                "grouping": group,
                "requested_size": requested,
                "minimum_frame_spacing": 0,
            },
        ),
        201,
    )
    candidates = checked(
        http.get(f"/api/v1/pose-active-learning-rounds/{picked['id']}/candidates"), 200
    )
    assert len(candidates) == requested, len(candidates)
    for candidate in candidates:
        reviewed = checked(
            http.put(
                f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
                json={
                    "action": "verify",
                    "reviewed_by": "synthetic-known-answer",
                    "note": "The landmark is the center of the corresponding rendered marker",
                },
            ),
            200,
        )
        assert reviewed["review_status"] == "verified"
    return checked(
        http.post(
            f"/api/v1/pose-active-learning-rounds/{picked['id']}/training-dataset",
            json={
                "name": group["recording_id"],
                "created_by": "synthetic-known-answer",
            },
        ),
        201,
    )


def reviewed_identity(
    http: TestClient, app: FastAPI, base: str, video: str, track: str, schema: dict, code: str
) -> tuple[str, str]:
    from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job

    job = checked(
        http.post(
            f"{base}/pose-identity-runs",
            json={
                "video_id": video,
                "source_track_ids": [track],
                "pose_schema_id": schema["id"],
                "pose_schema_revision": schema["revision"],
                "pose_schema_content_hash": schema["content_hash"],
                "device": "cpu",
                "parameters": {"minimum_detection_confidence": 0, "acceptance_threshold": 0.95},
            },
        ),
        202,
    )
    assert process_pose_identity_tracking_job(
        app.state.settings, app.state.session_factory, job["id"]
    )
    complete = checked(http.get(f"/api/v1/jobs/{job['id']}"), 200)
    assert complete["status"] == "completed", complete
    run = complete["result_json"]["run_id"]
    path = f"/api/v1/pose-identity-runs/{run}"
    identities = checked(http.get(f"{path}/identities"), 200)
    active = [row for row in identities if row["lifecycle_state"] == "active"]
    assert active, identities
    target = max(active, key=lambda row: (row["last_frame"] or 0) - row["first_frame"])
    for fragment in identities:
        if fragment["id"] == target["id"]:
            continue
        checked(
            http.post(
                f"{path}/corrections",
                json={
                    "action": "merge",
                    "target_type": "identity",
                    "target_id": fragment["id"],
                    "destination_identity_id": target["id"],
                    "actor": "synthetic-known-answer",
                    "reason": "One generated individual is present throughout this recording",
                },
            ),
            201,
        )
    reviewed = checked(
        http.post(
            f"{path}/corrections",
            json={
                "action": "accept",
                "target_type": "identity",
                "target_id": target["id"],
                "actor": "synthetic-known-answer",
                "reason": "Reviewed the complete known rendering",
            },
        ),
        201,
    )
    observations = checked(http.get(f"{path}/observations"), 200)
    picked = [
        row["frame_index"] for row in observations if row["animal_identity_id"] == target["id"]
    ]
    assert picked and len(set(picked)) == len(picked)
    organism = checked(
        http.post(
            f"{base}/ecology/organisms",
            json={
                "kind": "individual",
                "organism_key": code,
                "reason": "Synthetic rendered fixture roster",
                "experimental_unit_type": "tank",
                "experimental_unit_id": f"tank-{code}",
                "study_assignment": {
                    "tank_code": f"tank-{code}",
                    "sampling_unit_type": "individual",
                    "sampling_unit_id": code,
                    "reviewer": "synthetic-known-answer",
                    "confirm_review": True,
                },
            },
        ),
        201,
    )
    linked = checked(
        http.post(
            f"{base}/ecology/pose-links",
            json={
                "confirm": True,
                "organism_revision_id": organism["id"],
                "association_run_id": run,
                "animal_identity_id": target["id"],
                "expected_identity_run_revision": reviewed["revision"],
                "frame_start": min(picked),
                "frame_end": max(picked),
                "expected_pose_schema_sha256": schema["content_hash"],
                "reviewer": "synthetic-known-answer",
                "reason": "Known individual from deterministic rendering",
            },
        ),
        201,
    )
    assert linked["status"] == "current", linked
    return run, target["id"]


def sequence(
    http: TestClient,
    app: FastAPI,
    root: Path,
    base: str,
    label: str,
    schema: dict[str, Any],
    checkpoint: str,
    seed: int,
    count: int,
    split: str,
    device: str,
) -> dict[str, Any]:
    from reefvision.jobs.video_tracking import process_video_tracking_job

    video, known, group = build_source(http, root, base, label, schema, seed, count)
    queued = checked(
        http.post(
            f"/api/v1/videos/{video['id']}/tracking-jobs",
            json={
                "model_id": checkpoint,
                "device": device,
                "confidence": 0,
                "minimum_track_frames": 1,
            },
        ),
        200,
    )
    assert process_video_tracking_job(app.state.settings, app.state.session_factory, queued["id"])
    report = checked(http.get(f"/api/v1/jobs/{queued['id']}"), 200)
    assert report["status"] == "succeeded", report
    tracks = checked(http.get(f"/api/v1/videos/{video['id']}/tracks"), 200)
    track = max(
        (item for item in tracks if item["source_model_id"] == checkpoint),
        key=lambda item: len(item["keyframes_json"]),
    )
    run, animal = reviewed_identity(
        http, app, base, video["id"], track["id"], schema, group["animal_id"]
    )
    print("Frozen source", seed, split, video["sha256"], len(track["keyframes_json"]), flush=True)
    return {
        "frame_track_id": track["id"],
        "reviewed_track_id": known["id"],
        "confirm_same_animal": True,
        "identity_observation_run_id": run,
        "animal_identity_id": animal,
        "grouping": group,
        "split": split,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    options = parser.parse_args()
    root, device = options.data_dir.resolve(), options.device
    root.mkdir(parents=True, exist_ok=False)
    write_design = json.dumps(DESIGN, sort_keys=True, indent=2).encode()
    (root / "frozen-design.json").write_bytes(write_design)
    plan_sha = sha256(write_design).hexdigest()
    (root / "frozen-design.sha256").write_text(plan_sha + "\n", encoding="utf-8")
    print("Known-answer frozen before training", plan_sha, flush=True)
    os.environ.update(
        REEFVISION_ENV="test",
        REEFVISION_DATA_DIR=str(root),
        REEFVISION_DATABASE_URL=f"sqlite:///{(root / 'reefvision.db').as_posix()}",
        REEFVISION_BACKGROUND_WORKER_ENABLED="false",
        CUBLAS_WORKSPACE_CONFIG=":4096:8",
    )

    from reefvision.config import clear_settings_cache
    from reefvision.jobs.temporal_reefpose import process_temporal_reefpose_job
    from reefvision.jobs.workflow import process_workflow_run_job
    from reefvision.main import create_app

    repo = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(repo / "apps/api/alembic.ini")), "head")
    clear_settings_cache()
    app = create_app()
    with TestClient(app) as http:
        project = checked(
            http.post(
                "/api/v1/projects",
                json={"name": "Separate synthetic predeclared ReefPose benchmark"},
            ),
            201,
        )
        base = f"/api/v1/projects/{project['id']}"
        label = checked(
            http.post(
                f"{base}/classes",
                json={"name": "animal", "class_index": 0, "display_color": "#39b8c1"},
            ),
            201,
        )["id"]
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
        frozen = []
        for role in ("frame_train", "frame_validation"):
            seed, count = DESIGN["roles"][role][0]
            media, landmarks, group = build_source(http, root, base, label, schema, seed, count)
            reviewed_identity(
                http, app, base, media["id"], landmarks["id"], schema, group["animal_id"]
            )
            dataset = freeze_frame(http, base, media, landmarks, group, count)
            frozen.append(dataset)
            print("Frozen frame", role, dataset["id"], dataset["item_count"], flush=True)
        graph = training_graph(frozen[0]["id"], device)
        graph["nodes"].append(
            {
                "node_id": "selection",
                "node_type": "pose_training_dataset",
                "parameters": {"dataset_id": frozen[1]["id"]},
            }
        )
        graph["edges"].append(
            {
                "edge_id": "selection-train",
                "source_node_id": "selection",
                "source_port_id": "dataset",
                "target_node_id": "train",
                "target_port_id": "validation_dataset",
            }
        )
        config = graph["nodes"][1]["parameters"]
        config["initialization_mode"] = "random"
        config["require_validation_dataset"] = True
        config["random_seed"] = DESIGN["frame"]["seed"]
        config["training_config"].update(
            {
                key: value
                for key, value in DESIGN["frame"].items()
                if key not in {"seed", "selection"}
            }
        )
        queued = queue_workflow(http, base, graph)
        worked = process_workflow_run_job(
            app.state.settings, app.state.session_factory, queued["job_id"]
        )
        frame_run = checked(http.get(f"/api/v1/workflow-runs/{queued['id']}"), 200)
        assert worked and frame_run["run"]["status"] == "succeeded", frame_run
        models = checked(http.get(f"{base}/models"), 200)
        checkpoint = next(item for item in models if item["provider_name"] == "reefpose")
        assert checkpoint["metadata_json"]["source_pose_training_dataset_id"] == frozen[0]["id"]
        assert checkpoint["metadata_json"]["source_pose_validation_dataset_id"] == frozen[1]["id"]
        receipt = {
            "frozen_design_sha256": plan_sha,
            "frame_training_datasets": frozen,
            "frame_model": checkpoint,
            "frame_workflow": frame_run,
        }
        output = root / "known-answer-receipt.json"

        def save() -> None:
            output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

        save()
        print("Registered selected native frame checkpoint", checkpoint["sha256"], flush=True)
        temporal = f"{base}/temporal-reefpose"
        development = [
            sequence(
                http, app, root, base, label, schema, checkpoint["id"], seed, count, split, device
            )
            for role, split in (("temporal_train", "train"), ("temporal_validation", "validation"))
            for seed, count in DESIGN["roles"][role]
        ]
        calibration = checked(
            http.post(
                f"{temporal}/datasets",
                json={
                    "name": "No test media available: temporal training and selection",
                    "sources": development,
                },
            ),
            201,
        )

        def run(payload: dict) -> dict:
            queued = checked(http.post(f"{temporal}/runs", json=payload), 202)
            dispatched = process_temporal_reefpose_job(
                app.state.settings, app.state.session_factory, queued["job_id"]
            )
            completed = checked(http.get(f"{temporal}/runs/{queued['id']}"), 200)
            assert dispatched and completed["status"] == "succeeded", completed
            return completed

        learned = run(
            {
                "kind": "training",
                "device": device,
                "dataset_id": calibration["id"],
                "name": "Predeclared causal refinement",
                **{key: value for key, value in DESIGN["temporal"].items() if key != "selection"},
            }
        )
        receipt.update(temporal_development=calibration, temporal_training=learned)
        save()
        print("Temporal checkpoint selected. Test recordings are now generated.", flush=True)
        test = [
            sequence(
                http, app, root, base, label, schema, checkpoint["id"], seed, count, "test", device
            )
            for seed, count in DESIGN["roles"]["test"]
        ]
        evaluation_data = checked(
            http.post(
                f"{temporal}/datasets",
                json={
                    "name": "Same frame+temporal test clips",
                    "sources": development + test,
                },
            ),
            201,
        )
        assert evaluation_data["frame_lineage_state"] == "held_out", evaluation_data
        result = run(
            {
                "kind": "evaluation",
                "device": device,
                "dataset_id": evaluation_data["id"],
                "temporal_model_id": learned["result"]["model_id"],
                "anatomical_events": DESIGN["scoring"],
            }
        )
        assert result["result"]["evaluation_status"] == "held_out", result
        frozen_eval = checked(http.get(f"{temporal}/datasets/{evaluation_data['id']}"), 200)
        receipt.update(frozen_evaluation=frozen_eval, comparison=result)
        save()
        print("Known-answer report", output, flush=True)


if __name__ == "__main__":
    main()
