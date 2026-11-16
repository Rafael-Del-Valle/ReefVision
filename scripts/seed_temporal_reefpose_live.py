"""Prepare an isolated synthetic project with native frame predictions and manual targets."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from reefvision.ml.reefpose.checkpoints import save_checkpoint
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS
from reefvision.ml.reefpose.schema import AnatomySchema, LandmarkDefinition, SkeletonEdge


def write_clip(path: Path, index: int) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 64))
    if not writer.isOpened():
        raise RuntimeError("The local OpenCV runtime could not write the synthetic MP4")
    try:
        for frame in range(12):
            data = np.zeros((64, 96, 3), dtype=np.uint8)
            data[:, :, 0] = 20 * (index + 1)
            cv2.circle(data, (28 + frame, 32), 8, (130, 180, 190), -1)
            cv2.circle(data, (40 + frame, 32), 4, (200, 200, 200), -1)
            writer.write(data)
    finally:
        writer.release()


def install_frame_model(
    client: TestClient, project: str, schema: dict[str, Any], root: Path
) -> str:
    from sqlalchemy import select

    from reefvision.db.models import ModelRegistration, PoseLandmarkSchemaRevision
    from reefvision.services.pose_schemas import definition_for_revision

    anatomy = AnatomySchema(
        schema["id"],
        "Synthetic anatomy",
        schema["revision"],
        (LandmarkDefinition("jaw-a", "Jaw A"), LandmarkDefinition("jaw-b", "Jaw B")),
        (SkeletonEdge("jaw-a", "jaw-b"),),
    )
    torch.manual_seed(13)
    model = ReefPoseS(
        ReefPoseConfig(num_keypoints=2, input_height=64, input_width=96, base_channels=4)
    )
    with torch.no_grad():
        model.visibility_head[-1].bias.fill_(3)
    checkpoint = root / "synthetic-frame.pt"
    save_checkpoint(
        checkpoint,
        model=model,
        schema=anatomy,
        epoch=0,
        global_step=0,
        training_config={"class_label": "animal"},
    )
    response = client.post(
        f"/api/v1/projects/{project}/models/register",
        data={
            "purpose": "detector",
            "provider_name": "reefpose",
            "display_name": "Synthetic frame ReefPose",
        },
        files={"file": (checkpoint.name, checkpoint.read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    identifier = response.json()["id"]
    # The scientific schema is registered through the public schema API. Synthetic
    # fixture setup attaches its exact revision, as native training registration does.
    with client.app.state.session_factory() as session:
        row = session.get(ModelRegistration, identifier)
        revision = session.scalar(
            select(PoseLandmarkSchemaRevision).where(
                PoseLandmarkSchemaRevision.schema_id == schema["id"],
                PoseLandmarkSchemaRevision.revision == schema["revision"],
            )
        )
        assert row is not None and revision is not None
        row.metadata_json = {
            **row.metadata_json,
            "pose_landmark_schema": {
                "schema_id": schema["id"],
                "schema_revision": schema["revision"],
                "content_hash": schema["content_hash"],
                "expanded_labels": revision.expanded_labels_json,
                "definition": definition_for_revision(revision),
                **definition_for_revision(revision),
            },
        }
        session.commit()
    return str(identifier)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    args = parser.parse_args()
    root = args.data_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(REEFVISION_DATA_DIR=str(root), REEFVISION_BACKGROUND_WORKER_ENABLED="false")

    from reefvision.config import clear_settings_cache
    from reefvision.jobs.video_tracking import process_video_tracking_job
    from reefvision.main import create_app

    config = Config(str(Path(__file__).resolve().parents[1] / "apps" / "api" / "alembic.ini"))
    command.upgrade(config, "head")
    clear_settings_cache()
    app = create_app()
    with TestClient(app) as http:
        created = http.post(
            "/api/v1/projects", json={"name": "Synthetic temporal ReefPose", "template": "blank"}
        )
        assert created.status_code == 201, created.text
        project = created.json()["id"]
        base = f"/api/v1/projects/{project}"
        label = http.post(
            f"{base}/classes", json={"name": "animal", "class_index": 0, "display_color": "#39b8c1"}
        )
        assert label.status_code == 201, label.text
        label_id = label.json()["id"]
        anatomy = http.post(
            f"{base}/pose-schemas",
            json={
                "name": "Synthetic anatomy",
                "landmarks": [{"id": "jaw-a", "name": "Jaw A"}, {"id": "jaw-b", "name": "Jaw B"}],
                "edges": [{"from_id": "jaw-a", "to_id": "jaw-b"}],
            },
        )
        assert anatomy.status_code == 201, anatomy.text
        schema = anatomy.json()
        model_id = install_frame_model(http, project, schema, root)
        sources = []
        for index, split in enumerate(("train", "validation", "test")):
            path = root / f"synthetic-{split}.mp4"
            write_clip(path, index)
            uploaded = http.post(
                f"{base}/imports/videos",
                files={"file": (path.name, io.BytesIO(path.read_bytes()), "video/mp4")},
            )
            assert uploaded.status_code == 201, uploaded.text
            video = uploaded.json()["id"]
            queued = http.post(
                f"/api/v1/videos/{video}/tracking-jobs",
                json={
                    "model_id": model_id,
                    "confidence": 0,
                    "minimum_track_frames": 1,
                    "device": args.device,
                },
            )
            assert queued.status_code == 200, queued.text
            job = queued.json()["id"]
            assert process_video_tracking_job(app.state.settings, app.state.session_factory, job)
            status = http.get(f"/api/v1/jobs/{job}").json()
            assert status["status"] == "succeeded", status
            frame_tracks = http.get(f"/api/v1/videos/{video}/tracks").json()
            assert frame_tracks, status
            frame_track = max(frame_tracks, key=lambda item: len(item["keyframes_json"]))
            predictions = {item["frame"]: item for item in frame_track["keyframes_json"]}
            reviewed = []
            for frame in range(12):
                point_a = 28 + frame * 0.55
                point_b = point_a + (8 if frame % 5 < 2 else 14) + (index if frame > 6 else 0)
                item = {
                    "frame": frame,
                    "bbox": [14, 14, 56, 35],
                    "timestamp_seconds": predictions.get(frame, {}).get(
                        "timestamp_seconds", frame / 10
                    ),
                    "pose_observations": [
                        {
                            "id": f"{landmark}-{frame}",
                            "landmark_id": landmark,
                            "semantic_label": name,
                            "occurrence_index": 0,
                            "x": x,
                            "y": 32,
                            "status": "visible",
                            "source": "manual",
                        }
                        for landmark, name, x in (
                            ("jaw-a", "Jaw A", point_a),
                            ("jaw-b", "Jaw B", point_b),
                        )
                    ],
                }
                if item["timestamp_seconds"] is None:
                    item["timestamp_seconds"] = frame / 10
                reviewed.append(item)
            manual = http.post(
                f"/api/v1/videos/{video}/tracks",
                json={"label_class_id": label_id, "keyframes": reviewed, "status": "verified"},
            )
            assert manual.status_code == 201, manual.text
            track = manual.json()
            saved = http.put(
                f"/api/v1/video-tracks/{track['id']}",
                json={
                    "base_revision": track["revision"],
                    "label_class_id": label_id,
                    "keyframes": reviewed,
                    "status": "verified",
                    "pose_schema_binding": {
                        "schema_id": schema["id"],
                        "schema_revision": schema["revision"],
                        "content_hash": schema["content_hash"],
                    },
                },
            )
            assert saved.status_code == 200, saved.text
            sources.append(
                {
                    "split": split,
                    "video_id": video,
                    "video_name": path.name,
                    "frame_track_id": frame_track["id"],
                    "reviewed_track_id": track["id"],
                    "source_job_id": job,
                }
            )
        fixture = root / "temporal-fixture.json"
        fixture.write_text(
            json.dumps({"project_id": project, "model_id": model_id, "sources": sources}, indent=2),
            encoding="utf-8",
        )
        print(fixture)


if __name__ == "__main__":
    main()
