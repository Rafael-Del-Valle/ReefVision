"""Run native frame scratch training and temporal lineage on synthetic recordings."""

from __future__ import annotations

import argparse
import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from seed_temporal_reefpose_live import write_clip


def checked(response: Response, status: int) -> Any:
    assert response.status_code == status, (
        f"{response.request.url}: {response.status_code}: {response.text}"
    )
    return response.json()


CENTERS = [(28 + frame, 28 + frame + (8 if frame % 5 < 2 else 14)) for frame in range(12)]


def manual_track(
    http: TestClient, video: str, label: str, schema: dict[str, Any]
) -> dict[str, Any]:
    keyframes = []
    for frame, (left, right) in enumerate(CENTERS):
        keyframes.append(
            {
                "frame": frame,
                "bbox": [14, 17, 66, 31],
                "timestamp_seconds": frame / 10,
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
                    for landmark, name, x in (("jaw-a", "Jaw A", left), ("jaw-b", "Jaw B", right))
                ],
            }
        )
    payload = {"label_class_id": label, "keyframes": keyframes, "status": "verified"}
    created = checked(http.post(f"/api/v1/videos/{video}/tracks", json=payload), 201)
    return checked(
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


def acquisition(
    http: TestClient, project: str, video: str, track: str, grouping: dict[str, str]
) -> dict[str, Any]:
    checked(
        http.post(
            f"/api/v1/video-tracks/{track}/pose-temporal-associations",
            json={
                "max_gap_frames": 1,
                "max_normalized_displacement": 0.35,
                "ambiguity_margin": 0.10,
                "confirm_after_observations": 2,
            },
        ),
        200,
    )
    request: dict[str, Any] = {
        "name": "Synthetic native frame acquisition",
        "video_id": video,
        "track_ids": [track],
        "selection_unit": "frame",
        "requested_size": 3,
        "minimum_frame_spacing": 2,
    }
    scoped = f"{project}/pose-active-learning-rounds"
    legacy = checked(http.post(scoped, json=request), 201)
    assert "source_grouping" not in legacy["selection_manifest_json"]
    rejected = http.post(scoped, json={**request, "track_ids": [], "grouping": grouping})
    assert rejected.status_code == 422, rejected.text
    created = checked(http.post(scoped, json={**request, "grouping": grouping}), 201)
    assert created["selection_sha256"] != legacy["selection_sha256"]
    old_and_new = checked(http.get(scoped, params={"video_id": video}), 200)
    assert legacy in old_and_new
    for candidate in checked(
        http.get(f"/api/v1/pose-active-learning-rounds/{created['id']}/candidates"), 200
    ):
        assert candidate["provenance_json"]["source_grouping"] == grouping
        reviewed = checked(
            http.put(
                f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
                json={
                    "action": "verify",
                    "reviewed_by": "synthetic-fixture",
                    "note": "Known synthetic pixels and track identity for engineering checks",
                },
            ),
            200,
        )
        assert reviewed["review_status"] == "verified"
    dataset = checked(
        http.post(
            f"/api/v1/pose-active-learning-rounds/{created['id']}/training-dataset",
            json={"name": "Frozen synthetic frame supervision", "created_by": "synthetic-fixture"},
        ),
        201,
    )
    items = checked(http.get(f"/api/v1/pose-training-datasets/{dataset['id']}/items"), 200)
    return {"round": created, "dataset": dataset, "items": items}


def queue_workflow(http: TestClient, project: str, graph: dict[str, Any]) -> dict[str, Any]:
    record = checked(
        http.post(f"{project}/workflow-graphs", json={"graph": graph, "create_new_revision": True}),
        201,
    )
    return checked(
        http.post(f"{project}/workflow-runs", json={"graph_record_id": record["id"]}), 202
    )


def training_graph(dataset: str, device: str) -> dict[str, Any]:
    return {
        "graph_id": "synthetic-frame-training",
        "name": "Scratch-train and register a native frame checkpoint",
        "nodes": [
            {
                "node_id": "dataset",
                "node_type": "pose_training_dataset",
                "parameters": {"dataset_id": dataset},
            },
            {
                "node_id": "train",
                "node_type": "pose_model_training",
                "parameters": {
                    "provider_id": "reefpose",
                    "architecture": "reefpose-s",
                    "device": device,
                    "precision": "fp32",
                    "training_config": {
                        "epochs": 1,
                        "batch": 1,
                        "input_height": 64,
                        "input_width": 96,
                        "base_channels": 4,
                        "fpn_channels": 8,
                        "workers": 0,
                    },
                },
            },
            {"node_id": "register", "node_type": "register_trained_model"},
        ],
        "edges": [
            {
                "edge_id": "dataset-train",
                "source_node_id": "dataset",
                "source_port_id": "dataset",
                "target_node_id": "train",
                "target_port_id": "dataset",
            },
            {
                "edge_id": "train-register",
                "source_node_id": "train",
                "source_port_id": "training",
                "target_node_id": "register",
                "target_port_id": "training",
            },
        ],
    }


def link_reviewed_animal(
    http: TestClient,
    app: FastAPI,
    base: str,
    video: str,
    track: str,
    schema: dict[str, Any],
    code: str,
) -> tuple[str, str, dict[str, Any]]:
    from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job

    identity_job = checked(
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
        app.state.settings, app.state.session_factory, identity_job["id"]
    )
    finished = checked(http.get(f"/api/v1/jobs/{identity_job['id']}"), 200)
    assert finished["status"] == "completed", finished
    identity_run = finished["result_json"]["run_id"]
    identities = checked(http.get(f"/api/v1/pose-identity-runs/{identity_run}/identities"), 200)
    animal = max(identities, key=lambda row: (row["last_frame"] or 0) - row["first_frame"])
    corrected = checked(
        http.post(
            f"/api/v1/pose-identity-runs/{identity_run}/corrections",
            json={
                "action": "accept",
                "target_type": "identity",
                "target_id": animal["id"],
                "actor": "synthetic-fixture",
                "reason": "Known synthetic animal remains visible across this recording",
            },
        ),
        201,
    )
    subject = checked(
        http.post(
            f"{base}/ecology/organisms",
            json={
                "kind": "individual",
                "organism_key": code,
                "reason": "Synthetic fixture animal roster",
                "experimental_unit_type": "tank",
                "experimental_unit_id": f"tank-{code}",
                "study_assignment": {
                    "tank_code": f"tank-{code}",
                    "sampling_unit_type": "individual",
                    "sampling_unit_id": code,
                    "reviewer": "synthetic-fixture",
                    "confirm_review": True,
                },
            },
        ),
        201,
    )
    link = checked(
        http.post(
            f"{base}/ecology/pose-links",
            json={
                "confirm": True,
                "organism_revision_id": subject["id"],
                "association_run_id": identity_run,
                "animal_identity_id": animal["id"],
                "expected_identity_run_revision": corrected["revision"],
                "frame_start": animal["first_frame"],
                "frame_end": animal["last_frame"],
                "expected_pose_schema_sha256": schema["content_hash"],
                "reviewer": "synthetic-fixture",
                "reason": "Matched the known synthetic individual and track",
            },
        ),
        201,
    )
    assert link["status"] == "current", link
    return identity_run, animal["id"], link


def create_temporal_sources(
    http: TestClient,
    app: FastAPI,
    data: Path,
    base: str,
    model: str,
    label: str,
    schema: dict[str, Any],
    device: str,
) -> list[dict[str, Any]]:
    from reefvision.jobs.video_tracking import process_video_tracking_job

    sources = []
    for index, split in enumerate(("train", "validation", "test", "test"), start=1):
        path = data / f"temporal-{split}-{index}.mp4"
        write_clip(path, index, centers=CENTERS)
        video = checked(
            http.post(
                f"{base}/imports/videos",
                files={"file": (path.name, path.read_bytes(), "video/mp4")},
            ),
            201,
        )
        reviewed = manual_track(http, video["id"], label, schema)
        queued = checked(
            http.post(
                f"/api/v1/videos/{video['id']}/tracking-jobs",
                json={
                    "model_id": model,
                    "confidence": 0,
                    "minimum_track_frames": 1,
                    "device": device,
                },
            ),
            200,
        )
        assert process_video_tracking_job(
            app.state.settings, app.state.session_factory, queued["id"]
        )
        status = checked(http.get(f"/api/v1/jobs/{queued['id']}"), 200)
        assert status["status"] == "succeeded", status
        tracks = checked(http.get(f"/api/v1/videos/{video['id']}/tracks"), 200)
        frame = max(
            (row for row in tracks if row["source_model_id"] == model),
            key=lambda row: len(row["keyframes_json"]),
        )
        identity_run, animal_id, _ = link_reviewed_animal(
            http, app, base, video["id"], frame["id"], schema, f"temporal-animal-{index}"
        )
        sources.append(
            {
                "frame_track_id": frame["id"],
                "reviewed_track_id": reviewed["id"],
                "confirm_same_animal": True,
                "identity_observation_run_id": identity_run,
                "animal_identity_id": animal_id,
                "split": split,
                "grouping": {
                    "recording_id": f"temporal-recording-{index}",
                    "animal_id": f"temporal-animal-{index}",
                },
            }
        )
    return sources


def evaluate_temporal(
    http: TestClient, app: FastAPI, base: str, sources: list[dict[str, Any]], device: str
) -> dict[str, Any]:
    from reefvision.jobs.temporal_reefpose import process_temporal_reefpose_job
    from reefvision.jobs.workflow import process_workflow_run_job

    scope = f"{base}/temporal-reefpose"

    def freeze(name: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
        frozen = checked(
            http.post(f"{scope}/datasets", json={"name": name, "sources": selected}), 201
        )
        return checked(http.get(f"{scope}/datasets/{frozen['id']}"), 200)

    def run(config: dict[str, Any]) -> dict[str, Any]:
        queued = checked(http.post(f"{scope}/runs", json=config), 202)
        processed = process_temporal_reefpose_job(
            app.state.settings, app.state.session_factory, queued["job_id"]
        )
        completed = checked(http.get(f"{scope}/runs/{queued['id']}"), 200)
        assert processed and completed["status"] == "succeeded", completed
        return completed

    overlaps = []
    for match in ({"animal_id": "DEVELOPMENT-ANIMAL"}, {"recording_id": "DEVELOPMENT-RECORDING"}):
        altered = [dict(row) for row in sources]
        altered[-1]["grouping"] = {**altered[-1]["grouping"], **match}
        exposed = freeze(f"Exposed by {next(iter(match))}", altered)
        assert exposed["manifest"]["frame_lineage"]["state"] == "exposed", exposed["manifest"][
            "frame_lineage"
        ]
        overlaps.append(exposed["id"])
    for overlap in ("animal_id", "recording_id"):
        inconsistent = [dict(row) for row in sources]
        inconsistent[-1]["grouping"] = {
            **inconsistent[-1]["grouping"],
            overlap: inconsistent[0]["grouping"][overlap],
        }
        rejected = http.post(
            f"{scope}/datasets", json={"name": "Synthetic leakage check", "sources": inconsistent}
        )
        assert rejected.status_code == 400, rejected.text
        assert (
            "cannot cross" in rejected.json()["detail"]
            or "different split" in rejected.json()["detail"]
        )
    selected = freeze("Frozen same checkpoint disjoint fixture", sources)
    assert all(
        source["source_grouping_study"]["link_source_sha256"]
        for source in selected["manifest"]["sources"]
    )
    assert selected["manifest"]["frame_lineage"]["state"] == "held_out", selected["manifest"][
        "frame_lineage"
    ]
    typed = selected["id"]
    training = run(
        {
            "kind": "training",
            "device": device,
            "dataset_id": typed,
            "name": "Synthetic causal temporal",
            "context_mode": "causal",
            "window_length": 3,
            "epochs": 2,
            "channels": 8,
        }
    )
    model = training["result"]["model_id"]
    config = {
        "device": device,
        "temporal_model_id": model,
        "anatomical_events": {
            "landmark_a_id": "jaw-a",
            "landmark_b_id": "jaw-b",
            "open_threshold_px": 12,
            "close_threshold_px": 9,
        },
    }
    result = run({**config, "kind": "evaluation", "dataset_id": typed})
    evaluated = result["result"]
    assert (
        evaluated["evaluation_status"]
        == evaluated["frame_lineage_state"]
        == evaluated["temporal_lineage_state"]
        == "held_out"
    ), evaluated
    unproven = [dict(row) for row in sources]
    unproven[-1].pop("grouping")
    legacy = freeze("Same recordings with test grouping omitted", unproven)
    exploratory = run({**config, "kind": "evaluation", "dataset_id": legacy["id"]})
    assert exploratory["result"]["evaluation_status"] == "exploratory", exploratory
    graph = {
        "graph_id": "synthetic-temporal-comparison",
        "name": "Replay the frozen disjoint temporal comparison",
        "nodes": [
            {
                "node_id": "frozen",
                "node_type": "temporal_reefpose_dataset",
                "parameters": {"saved_dataset_id": typed},
            },
            {
                "node_id": "comparison",
                "node_type": "temporal_reefpose_evaluation",
                "parameters": config,
            },
        ],
        "edges": [
            {
                "edge_id": "dataset-comparison",
                "source_node_id": "frozen",
                "source_port_id": "dataset",
                "target_node_id": "comparison",
                "target_port_id": "dataset",
            }
        ],
    }
    queued = queue_workflow(http, base, graph)
    ok = process_workflow_run_job(app.state.settings, app.state.session_factory, queued["job_id"])
    workflow = checked(http.get(f"/api/v1/workflow-runs/{queued['id']}"), 200)
    assert ok and workflow["run"]["status"] == "succeeded", workflow
    artifacts = {
        artifact["data_type"]: artifact["payload_json"] for artifact in workflow["artifacts"]
    }
    assert artifacts["temporal_reefpose_dataset"]["manifest_sha256"] == selected["manifest_sha256"]
    assert artifacts["temporal_reefpose_evaluation"]["evaluation_status"] == "held_out"
    assert artifacts["temporal_reefpose_evaluation"]["metrics"] == evaluated["metrics"]
    return {
        "dataset": selected,
        "exposed_dataset_ids": overlaps,
        "trained": training,
        "held_out": result,
        "exploratory": exploratory,
        "workflow": workflow,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    raw = parser.parse_args()
    data = raw.data_dir.resolve()
    data.mkdir(parents=True, exist_ok=False)
    os.environ.update(
        REEFVISION_ENV="test",
        REEFVISION_DATA_DIR=str(data),
        REEFVISION_DATABASE_URL=f"sqlite:///{(data / 'reefvision.db').as_posix()}",
        REEFVISION_BACKGROUND_WORKER_ENABLED="false",
        CUBLAS_WORKSPACE_CONFIG=":4096:8",
    )
    from reefvision.config import clear_settings_cache
    from reefvision.jobs.video import process_video_extract_job
    from reefvision.jobs.workflow import process_workflow_run_job
    from reefvision.main import create_app

    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "apps/api/alembic.ini")), "head"
    )
    clear_settings_cache()
    app = create_app()
    with TestClient(app) as http:
        project = checked(
            http.post("/api/v1/projects", json={"name": "Synthetic ReefPose lineage"}), 201
        )
        base = f"/api/v1/projects/{project['id']}"
        label = checked(
            http.post(
                f"{base}/classes",
                json={"name": "animal", "class_index": 0, "display_color": "#39b8c1"},
            ),
            201,
        )
        schema = checked(
            http.post(
                f"{base}/pose-schemas",
                json={
                    "name": "Synthetic anatomy",
                    "landmarks": [
                        {"id": "jaw-a", "name": "Jaw A"},
                        {"id": "jaw-b", "name": "Jaw B"},
                    ],
                    "edges": [{"from_id": "jaw-a", "to_id": "jaw-b"}],
                },
            ),
            201,
        )
        path = data / "frame-development.mp4"
        write_clip(path, 0, centers=CENTERS)
        video = checked(
            http.post(
                f"{base}/imports/videos",
                files={"file": (path.name, path.read_bytes(), "video/mp4")},
            ),
            201,
        )
        assert video["sha256"] == sha256(path.read_bytes()).hexdigest()
        extraction = checked(
            http.post(f"/api/v1/videos/{video['id']}/extract", json={"every_n_frames": 1}), 200
        )
        assert process_video_extract_job(
            app.state.settings, app.state.session_factory, extraction["id"]
        )
        extracted = checked(http.get(f"/api/v1/jobs/{extraction['id']}"), 200)
        assert extracted["status"] == "succeeded"
        track = manual_track(http, video["id"], label["id"], schema)
        group = {"recording_id": "development-recording", "animal_id": "development-animal"}
        _, _, frame_link = link_reviewed_animal(
            http, app, base, video["id"], track["id"], schema, group["animal_id"]
        )
        evidence = acquisition(http, base, video["id"], track["id"], group)
        evidence["scientific_context"] = "synthetic_engineering"
        proof = data / "native-frame-lineage.json"
        proof.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Frozen verified pose data: {proof}", flush=True)
        for item in evidence["items"]:
            provenance = item["acquisition_provenance_json"]
            assert provenance["source_grouping"] == group
            assert (
                provenance["source_grouping_study"]["link_source_sha256"]
                == frame_link["source_sha256"]
            )
        queued = queue_workflow(http, base, training_graph(evidence["dataset"]["id"], raw.device))
        processed = process_workflow_run_job(
            app.state.settings, app.state.session_factory, queued["job_id"]
        )
        run = checked(http.get(f"/api/v1/workflow-runs/{queued['id']}"), 200)
        assert processed and run["run"]["status"] == "succeeded", run
        models = checked(http.get(f"{base}/models"), 200)
        native = next(model for model in models if model["provider_name"] == "reefpose")
        evidence.update(workflow=run, native_frame_model=native)
        proof.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Native trained and registered: {native['id']}", flush=True)
        sources = create_temporal_sources(
            http, app, data, base, native["id"], label["id"], schema, raw.device
        )
        evidence.update(temporal=evaluate_temporal(http, app, base, sources, raw.device))
        proof.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Frozen held-out and exploratory receipts: {proof}", flush=True)


if __name__ == "__main__":
    main()
