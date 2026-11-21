"""Prepare generated ReefPose appearance controls in a fresh, disposable profile."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from verify_reefpose_temporal_lineage_live import (
    CENTERS,
    acquisition,
    checked,
    link_reviewed_animal,
    manual_track,
    queue_workflow,
    training_graph,
    write_clip,
)


def study_clip(path: Path, pattern: int) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 64))
    assert writer.isOpened()
    try:
        for frame in range(12):
            image = np.full((64, 96, 3), 10 + pattern, np.uint8)
            cv2.rectangle(image, (11, 10), (39, 33), (25, 158, 215), -1)
            cv2.rectangle(image, (55, 29), (82, 54), (198, 70, 24), -1)
            cv2.line(image, (13, 12), (36, 30), (235, 170, 30), 2)
            cv2.circle(image, (68, 42), 7, (180, 220, 80), 2)
            image[1, 1] = (frame * 9, pattern * 3, frame * 4)
            writer.write(image)
    finally:
        writer.release()


def seed(http: TestClient, root: Path, device: str = "cpu") -> dict[str, Any]:
    from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job
    from reefvision.jobs.video import process_video_extract_job
    from reefvision.jobs.workflow import process_workflow_run_job

    app = http.app
    state = app.state
    project = checked(
        http.post("/api/v1/projects", json={"name": "Synthetic appearance review"}), 201
    )
    base = f"/api/v1/projects/{project['id']}"
    label = checked(
        http.post(
            base + "/classes", json={"name": "animal", "class_index": 0, "display_color": "#347879"}
        ),
        201,
    )
    schema = checked(
        http.post(
            base + "/pose-schemas",
            json={
                "name": "Fixture animal",
                "landmarks": [{"id": "jaw-a", "name": "Jaw A"}, {"id": "jaw-b", "name": "Jaw B"}],
                "edges": [{"from_id": "jaw-a", "to_id": "jaw-b"}],
            },
        ),
        201,
    )

    def upload(path: Path) -> dict[str, Any]:
        data = path.read_bytes()
        video = checked(
            http.post(base + "/imports/videos", files={"file": (path.name, data, "video/mp4")}), 201
        )
        assert video["sha256"] == hashlib.sha256(data).hexdigest()
        return video

    training_path = root / "frame-training.mp4"
    write_clip(training_path, 0, centers=CENTERS)
    training = upload(training_path)
    extraction = checked(
        http.post(f"/api/v1/videos/{training['id']}/extract", json={"every_n_frames": 1}), 200
    )
    assert process_video_extract_job(state.settings, state.session_factory, extraction["id"])
    track = manual_track(http, training["id"], label["id"], schema)
    group = {"recording_id": "fit-camera", "animal_id": "fit-animal"}
    link_reviewed_animal(http, app, base, training["id"], track["id"], schema, group["animal_id"])
    evidence = acquisition(http, base, training["id"], track["id"], group)
    queued = queue_workflow(http, base, training_graph(evidence["dataset"]["id"], device))
    assert process_workflow_run_job(state.settings, state.session_factory, queued["job_id"])
    native_run = checked(http.get(f"/api/v1/workflow-runs/{queued['id']}"), 200)
    assert native_run["run"]["status"] == "succeeded", native_run
    model = next(
        m for m in checked(http.get(base + "/models"), 200) if m["provider_name"] == "reefpose"
    )
    records = []
    subjects = []
    for index in range(4):
        split = "development" if index < 2 else "test"
        path = root / f"{split}-{index}.mp4"
        study_clip(path, index + 1)
        video = upload(path)
        reviewed = {}
        for title, box in (("striped", [11, 10, 29, 24]), ("spotted", [55, 29, 28, 26])):
            x, y, w, h = box
            annotations = [
                {
                    "frame": f,
                    "bbox": box,
                    "timestamp_seconds": f / 10,
                    "pose_observations": [
                        {
                            "id": f"{landmark}-{f}",
                            "landmark_id": landmark,
                            "semantic_label": name,
                            "occurrence_index": 0,
                            "x": x + dx,
                            "y": y + h / 2,
                            "status": "visible",
                            "source": "manual",
                        }
                        for landmark, name, dx in (
                            ("jaw-a", "Jaw A", w / 3),
                            ("jaw-b", "Jaw B", 2 * w / 3),
                        )
                    ],
                }
                for f in (0, 5, 11)
            ]
            track_body = {
                "label_class_id": label["id"],
                "keyframes": annotations,
                "status": "verified",
            }
            create = checked(
                http.post(f"/api/v1/videos/{video['id']}/tracks", json=track_body), 201
            )
            pose_track = checked(
                http.put(
                    "/api/v1/video-tracks/" + create["id"],
                    json={
                        **track_body,
                        "base_revision": create["revision"],
                        "pose_schema_binding": {
                            "schema_id": schema["id"],
                            "schema_revision": schema["revision"],
                            "content_hash": schema["content_hash"],
                        },
                    },
                ),
                200,
            )
            payload = {
                "video_id": video["id"],
                "source_track_ids": [pose_track["id"]],
                "pose_schema_id": schema["id"],
                "pose_schema_revision": schema["revision"],
                "pose_schema_content_hash": schema["content_hash"],
                "device": "cpu",
                "parameters": {
                    "max_gap_frames": 12,
                    "minimum_detection_confidence": 0,
                    "acceptance_threshold": 0.95,
                },
            }
            job = checked(http.post(base + "/pose-identity-runs", json=payload), 202)
            assert process_pose_identity_tracking_job(
                state.settings, state.session_factory, job["id"]
            )
            original = checked(http.get("/api/v1/jobs/" + job["id"]), 200)["result_json"]["run_id"]
            identity_base = "/api/v1/pose-identity-runs/" + original
            ident = checked(http.get(identity_base + "/identities"), 200)[0]
            checked(
                http.post(
                    identity_base + "/corrections",
                    json={
                        "action": "accept",
                        "target_type": "identity",
                        "target_id": ident["id"],
                        "actor": "generated fixture",
                        "reason": f"The {title} animal's box matches the generated pixels.",
                    },
                ),
                201,
            )
            observations = checked(http.get(identity_base + "/observations"), 200)
            reviewed[title] = [
                o["id"]
                for o in observations
                if o["is_current"] and o["verification_state"] == "scientist_confirmed"
            ]
        subjects.append(
            {
                "id": video["id"],
                "filename": path.name,
                "sha256": video["sha256"],
                "observations": reviewed,
            }
        )
        animals = [f"{split}-striped", f"{split}-spotted"]
        poses = [
            {"individual_id": a, "frame": f, "bbox": box, "state": "scored"}
            for a, box in zip(animals, ([11, 10, 29, 24], [55, 29, 28, 26]), strict=True)
            for f in (0, 11)
        ]
        annotations = [
            {
                "rater_id": r,
                "blinded": True,
                "source": "Generated independent reference control",
                "poses": poses,
            }
            for r in ("fixture-a", "fixture-b")
        ]
        records.append(
            {
                "video_id": video["id"],
                "video_sha256": video["sha256"],
                "schema_id": schema["id"],
                "schema_revision": schema["revision"],
                "schema_sha256": schema["content_hash"],
                "group_id": f"camera-{index}",
                "split": split,
                "individuals": [{"id": a, "species": "generated"} for a in animals],
                "annotations": annotations,
                "exhaustive_identity_coverage": True,
            }
        )
    reference = checked(
        http.post(
            base + "/reefpose-references",
            json={
                "name": "Generated disjoint fish recordings",
                "data_kind": "synthetic",
                "recordings": records,
            },
        ),
        201,
    )
    return {
        "project_id": project["id"],
        "project_name": project["name"],
        "model_id": model["id"],
        "model_sha256": model["sha256"],
        "source_dataset_sha256": evidence["dataset"]["manifest_sha256"],
        "training_workflow_id": queued["id"],
        "reference_id": reference["id"],
        "reference_sha256": reference["manifest_sha256"],
        "rater": "fixture-a",
        "videos": subjects,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    path = args.profile.resolve()
    path.mkdir(parents=True, exist_ok=False)
    os.environ.update(
        REEFVISION_DATA_DIR=str(path),
        REEFVISION_DATABASE_URL=f"sqlite:///{(path / 'reefvision.db').as_posix()}",
        REEFVISION_BACKGROUND_WORKER_ENABLED="false",
        CUBLAS_WORKSPACE_CONFIG=":4096:8",
    )
    from reefvision.config import clear_settings_cache
    from reefvision.main import create_app

    clear_settings_cache()
    config = Config(str(Path(__file__).resolve().parents[1] / "apps/api/alembic.ini"))
    command.upgrade(config, "head")
    app = create_app()
    with TestClient(app) as http:
        receipt = seed(http, path, args.device)
        from reefvision.tests.test_reviewer_lab_v15 import role_fixture

        _, _, roles = role_fixture(http, receipt["project_id"])
        # Disposable attribution keys for the generated GUI control only.
        receipt["fixture_roles"] = {
            name: roles[name][1]["Authorization"].removeprefix("Bearer ")
            for name in ("Reviewer A", "Reviewer B", "Adjudicator")
        }
    (path / "appearance-fixture.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(path / "appearance-fixture.json")
