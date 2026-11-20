"""Temporal workflow integration with frozen video tracking and human pose evidence."""

from __future__ import annotations

from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job, LabelClass, ModelRegistration, VideoAsset, VideoTrack
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


def _setup(client: TestClient) -> tuple[str, list[dict[str, Any]]]:
    project = client.post("/api/v1/projects", json={"name": "Temporal fixture"}).json()
    project_id = project["id"]
    schema_response = client.post(
        f"/api/v1/projects/{project_id}/pose-schemas",
        json={
            "name": "Animal",
            "landmarks": [{"id": "base", "name": "Base"}, {"id": "tip", "name": "Tip"}],
            "edges": [{"from_id": "base", "to_id": "tip"}],
        },
    )
    assert schema_response.status_code == 201, schema_response.text
    schema = schema_response.json()
    bind = {
        "schema_id": schema["id"],
        "schema_revision": schema["revision"],
        "content_hash": schema["content_hash"],
    }
    with client.app.state.session_factory() as session:
        label = LabelClass(
            project_id=project_id,
            class_index=0,
            display_order=0,
            name="animal",
            display_color="#123456",
        )
        model_path = f"projects/{project_id}/models/{uuid4()}.pt"
        frame_checkpoint = b"Opaque frozen frame fixture checkpoint"
        path = resolve_managed_project_path(client.app.state.settings, model_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(frame_checkpoint)
        model = ModelRegistration(
            project_id=project_id,
            purpose="pose",
            display_name="Frame",
            source_filename="frame.pt",
            managed_path=model_path,
            sha256=sha256(frame_checkpoint).hexdigest(),
            file_size_bytes=len(frame_checkpoint),
            framework="reefpose",
            provider_name="reefpose",
            provider_version="1",
            task="pose",
            metadata_json={"pose_landmark_schema": bind},
        )
        session.add_all([label, model])
        session.flush()
        sources = []
        for index, split in enumerate(("train", "validation", "test")):
            video = VideoAsset(
                project_id=project_id,
                original_filename=f"{index}.mp4",
                managed_path=f"projects/{project_id}/videos/{index}.mp4",
                sha256=str(index) * 64,
                media_type="video/mp4",
                width_px=100,
                height_px=80,
                frame_count=9,
                fps=5,
                duration_seconds=2,
            )
            session.add(video)
            session.flush()
            job = Job(
                project_id=project_id,
                job_type="video_tracking",
                status="succeeded",
                request_json={"video_id": video.id, "model_id": model.id},
            )
            session.add(job)
            session.flush()

            def frame(n: int, source: str, x: float) -> dict[str, Any]:
                return {
                    "frame": n,
                    "timestamp_seconds": n * 0.2 + (0.03 if n == 2 else 0),
                    "bbox": [5, 5, 50, 40],
                    "pose_observations": [
                        {
                            "id": f"fixture:{n}",
                            "landmark_id": "base",
                            "semantic_label": "base",
                            "occurrence_index": 0,
                            "x": x,
                            "y": 10,
                            "confidence": 0.7 if source == "model" else None,
                            "source": source,
                        },
                        {
                            "id": f"fixture:{n}:tip",
                            "landmark_id": "tip",
                            "semantic_label": "tip",
                            "occurrence_index": 0,
                            "x": x + 15,
                            "y": 10,
                            "confidence": 0.6 if source == "model" else None,
                            "source": source,
                        },
                    ],
                }

            tracks = [
                VideoTrack(
                    video_id=video.id,
                    label_class_id=label.id,
                    track_number=1,
                    keyframes_json=[frame(n, "model", 10 + n) for n in (0, 2, 3)],
                    source_model_id=model.id,
                    source_job_id=job.id,
                    status="machine_generated",
                    metadata_json={"pose_landmark_schema": bind},
                ),
                VideoTrack(
                    video_id=video.id,
                    label_class_id=label.id,
                    track_number=2,
                    keyframes_json=[
                        frame(0, "manual", 11),
                        frame(1, "manual", 12),
                        frame(3, "model", 90),
                    ],
                    status="verified",
                    metadata_json={"source": "human", "pose_landmark_schema": bind},
                ),
            ]
            session.add_all(tracks)
            session.flush()
            job.result_json = {
                "pose_track_hashes": {
                    tracks[0].id: canonical_json_sha256(tracks[0].keyframes_json)
                },
                "pose_input_hashes": {"model_sha256": model.sha256, "video_sha256": video.sha256},
                "pose_inference_protocol": {"confidence": 0.25, "provider": "reefpose"},
            }
            sources.append(
                {
                    "frame_track_id": tracks[0].id,
                    "reviewed_track_id": tracks[1].id,
                    "confirm_same_animal": True,
                    "split": split,
                }
            )
        session.commit()
    return f"/api/v1/projects/{project_id}/temporal-reefpose", sources


def test_temporal_dataset_freezes_only_human_targets(client: TestClient) -> None:
    path, sources = _setup(client)
    response = client.post(f"{path}/datasets", json={"name": "Frozen", "sources": sources})
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]
    result = client.get(f"{path}/datasets/{dataset_id}").json()
    frames = result["manifest"]["sources"][0]["frames"]
    assert [item["frame_index"] for item in frames] == [0, 1, 2, 3]
    assert frames[1]["frame_points"] is None
    assert frames[1]["target_points"][0]["x"] == 12
    assert frames[2]["timestamp_seconds"] == 0.43000000000000005
    assert frames[3]["target_points"] is None
    assert result["manifest"]["frame_lineage"]["state"] == "unverified"
    with client.app.state.session_factory() as session:
        track = session.get(VideoTrack, sources[0]["reviewed_track_id"])
        track.keyframes_json = []
        track.revision += 1
        session.commit()
    assert client.get(f"{path}/datasets/{dataset_id}").json() == result


def test_temporal_dataset_rejects_group_split_leakage(client: TestClient) -> None:
    path, sources = _setup(client)
    for source in sources:
        source["group_key"] = "same animal"
    response = client.post(f"{path}/datasets", json={"name": "Leaky", "sources": sources})
    assert response.status_code == 400, response.text
    assert "split" in response.text.lower()


@pytest.mark.parametrize("shared_dimension", [None, "animal_id", "recording_id"])
def test_temporal_split_groups_respect_typed_source_aliases(
    client: TestClient, shared_dimension: str | None
) -> None:
    path, sources = _setup(client)
    for index, source in enumerate(sources):
        source["grouping"] = {"recording_id": f"Recording-{index}", "animal_id": f"Animal-{index}"}
    if shared_dimension:
        first_group = sources[0]["grouping"][shared_dimension]
        # The full-width character is the same alias under the declared normalization.
        full_width_first = chr(ord(first_group[0]) + 0xFEE0)
        sources[2]["grouping"][shared_dimension] = f"{full_width_first}{first_group[1:].upper()}"

    result = client.post(f"{path}/datasets", json={"name": "Typed splits", "sources": sources})
    if shared_dimension:
        assert result.status_code == 400, result.text
        assert "cannot cross dataset splits" in result.text
        assert client.get(f"{path}/datasets").json() == []
    else:
        assert result.status_code == 201, result.text
        manifest = client.get(f"{path}/datasets/{result.json()['id']}").json()["manifest"]
        assert [row["source_grouping"] for row in manifest["sources"]] == [
            source["grouping"] for source in sources
        ]
        assert len({row["group_key"] for row in manifest["sources"]}) == 3


@pytest.mark.parametrize(
    ("training_history", "test_grouping", "expected"),
    [
        ("declared", {"recording_id": "recording-test", "animal_id": "animal-test"}, "held_out"),
        ("declared", {"recording_id": "recording-test", "animal_id": "ANIMAL-DEV"}, "exposed"),
        ("declared", {"recording_id": "RECORDING-DEV", "animal_id": "animal-test"}, "exposed"),
        ("legacy", {"recording_id": "recording-test", "animal_id": "animal-test"}, "unverified"),
        (
            "unknown_parent",
            {"recording_id": "recording-test", "animal_id": "animal-test"},
            "unverified",
        ),
    ],
)
def test_frozen_frame_ancestry_sets_test_eligibility(
    client: TestClient, training_history: str, test_grouping: dict[str, str], expected: str
) -> None:
    path, sources = _setup(client)
    project_path = path.removesuffix("/temporal-reefpose")
    training_track_id = sources[0]["reviewed_track_id"]
    with client.app.state.session_factory() as session:
        training_track = session.get(VideoTrack, training_track_id)
        assert training_track is not None
        video = session.get(VideoAsset, training_track.video_id)
        assert video is not None
        video_id = video.id
        video_hash = video.sha256
        # Current tags may expose overlap, but cannot retroactively prove an old declaration.
        video.metadata_json = {"group_key": "current-catalogue-tag"}
        training_track.keyframes_json = training_track.keyframes_json[:2]
        session.commit()

    temporal = client.post(
        f"/api/v1/video-tracks/{training_track_id}/pose-temporal-associations", json={}
    )
    assert temporal.status_code == 200, temporal.text
    declaration = {"recording_id": "recording-dev", "animal_id": "animal-dev"}
    payload: dict[str, Any] = {
        "name": "Reviewed development frames",
        "video_id": video_id,
        "track_ids": [training_track_id],
        "selection_unit": "frame",
        "requested_size": 1,
    }
    if training_history != "legacy":
        payload["grouping"] = declaration
    acquisition = client.post(f"{project_path}/pose-active-learning-rounds", json=payload)
    assert acquisition.status_code == 201, acquisition.text
    round_id = acquisition.json()["id"]
    round_path = f"/api/v1/pose-active-learning-rounds/{round_id}"
    [candidate] = client.get(f"{round_path}/candidates").json()
    review = client.put(
        f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
        json={"action": "verify", "reviewed_by": "Fixture reviewer"},
    )
    assert review.status_code == 200, review.text
    freeze = client.post(f"{round_path}/training-dataset", json={"name": "Frozen reviewed poses"})
    assert freeze.status_code == 201, freeze.text
    dataset = freeze.json()
    [item] = client.get(f"/api/v1/pose-training-datasets/{dataset['id']}/items").json()
    assert item["video_sha256"] == video_hash
    assert item["acquisition_provenance_json"].get("source_grouping") == payload.get("grouping")

    # The fixture models a registered checkpoint and binds the actual saved dataset.
    # No model weights or accelerator are needed to verify the persisted split decision.
    with client.app.state.session_factory() as session:
        prediction = session.get(VideoTrack, sources[2]["frame_track_id"])
        assert prediction is not None
        model = session.get(ModelRegistration, prediction.source_model_id)
        assert model is not None
        metadata = {
            **(model.metadata_json or {}),
            "source_pose_training_dataset_id": dataset["id"],
            "source_pose_training_dataset_manifest_sha256": dataset["manifest_sha256"],
            "source_pose_validation_mode": "none",
        }
        if training_history == "unknown_parent":
            metadata["source_initial_pose_model_id"] = str(uuid4())
            metadata["source_initial_pose_model_sha256"] = "c" * 64
        model.metadata_json = metadata
        session.commit()

    frozen = client.post(
        f"{path}/datasets",
        json={
            "name": "Validation evidence",
            "sources": [{**sources[2], "grouping": test_grouping}],
        },
    )
    assert frozen.status_code == 201, frozen.text
    reopened = client.get(f"{path}/datasets/{frozen.json()['id']}").json()
    lineage = reopened["manifest"]["frame_lineage"]
    assert lineage["state"] == expected
    assert lineage["datasets"] == [
        {"id": dataset["id"], "sha256": dataset["manifest_sha256"], "role": "training"}
    ]
    assert lineage["recordings"][0]["sha256"] == video_hash
    assert "group:current-catalogue-tag" in lineage["recordings"][0]["groups"]
    if training_history == "legacy":
        assert "declared_groups" not in lineage
    else:
        assert lineage["declared_groups"] is True
        assert {"group:animal:animal-dev", "group:recording:recording-dev"} <= set(
            lineage["recordings"][0]["groups"]
        )
    if training_history == "unknown_parent":
        assert lineage["complete"] is False


def test_temporal_dataset_requires_explicit_subject_pairing(client: TestClient) -> None:
    path, sources = _setup(client)
    sources[0].pop("confirm_same_animal")
    response = client.post(f"{path}/datasets", json={"name": "Unpaired", "sources": sources})
    assert response.status_code == 422, response.text
    assert "same animal" in response.text.lower()


def test_training_retries_from_atomic_epoch_checkpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reefvision.jobs.temporal_reefpose import process_temporal_reefpose_job
    from reefvision.ml.reefpose import temporal

    path, sources = _setup(client)
    dataset = client.post(f"{path}/datasets", json={"name": "Frozen", "sources": sources}).json()
    submitted = client.post(
        f"{path}/runs",
        json={
            "kind": "training",
            "dataset_id": dataset["id"],
            "name": "Resumed",
            "epochs": 2,
            "batch_size": 2,
            "channels": 4,
            "window_length": 3,
            "device": "cpu",
        },
    )
    assert submitted.status_code == 202, submitted.text
    run = submitted.json()
    job_id, app = run["job_id"], client.app
    actual = temporal.train_temporal
    observed_epochs = []

    def stop_after_checkpoint(*args: Any, **kwargs: Any) -> Any:
        original_callback = kwargs["on_epoch"]

        def cancel(epoch: int, metrics: dict[str, Any], state: dict[str, Any]) -> None:
            original_callback(epoch, metrics, state)
            observed_epochs.append(epoch)
            cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
            assert cancelled.json()["status"] == "cancel_requested"

        return actual(*args, **{**kwargs, "on_epoch": cancel})

    monkeypatch.setattr(temporal, "train_temporal", stop_after_checkpoint)
    assert process_temporal_reefpose_job(app.state.settings, app.state.session_factory, job_id)
    interrupted = client.get(f"{path}/runs/{run['id']}").json()
    assert interrupted["status"] == "cancelled" and interrupted["progress_current"] == 1
    assert observed_epochs == [1]

    def verify_resume(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["resume"]["epoch"] == 1
        callback = kwargs["on_epoch"]

        def record(epoch: int, metrics: dict[str, Any], state: dict[str, Any]) -> None:
            observed_epochs.append(epoch)
            callback(epoch, metrics, state)

        return actual(*args, **{**kwargs, "on_epoch": record})

    monkeypatch.setattr(temporal, "train_temporal", verify_resume)
    assert client.post(f"/api/v1/jobs/{job_id}/retry").json()["status"] == "queued"
    assert process_temporal_reefpose_job(app.state.settings, app.state.session_factory, job_id)
    result = client.get(f"{path}/runs/{run['id']}").json()
    assert result["status"] == "succeeded", result
    assert observed_epochs == [1, 2]


def test_temporal_checkpoint_refinement_review_and_heldout_evaluation(client: TestClient) -> None:
    path, sources = _setup(client)
    dataset = client.post(f"{path}/datasets", json={"name": "Frozen", "sources": sources}).json()
    training = client.post(
        f"{path}/runs",
        json={
            "kind": "training",
            "dataset_id": dataset["id"],
            "name": "Tiny CPU refiner",
            "epochs": 2,
            "batch_size": 2,
            "channels": 4,
            "window_length": 3,
            "device": "cpu",
        },
    )
    assert training.status_code == 202, training.text
    job_id = training.json()["job_id"]
    cancel = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancel.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/jobs/{job_id}/retry").json()["status"] == "queued"
    from reefvision.jobs.worker import process_next_thumbnail_job

    def finish(queued: dict[str, Any]) -> dict[str, Any]:
        assert process_next_thumbnail_job(
            client.app.state.settings, client.app.state.session_factory
        )
        result = client.get(f"{path}/runs/{queued['id']}").json()
        assert result["status"] == "succeeded", result
        return result

    trained = finish(training.json())
    temporal_model_id = trained["result"]["model_id"]
    assert len(trained["result"]["metrics_history"]) == 2
    choices = client.get(f"{path}/inputs").json()
    assert choices["temporal_models"][0]["id"] == temporal_model_id
    inference = client.post(
        f"{path}/runs",
        json={
            "kind": "inference",
            "temporal_model_id": temporal_model_id,
            "source": {"frame_track_id": sources[2]["frame_track_id"]},
            "chunk_size": 1,
            "device": "cpu",
        },
    )
    assert inference.status_code == 202, inference.text
    prediction = finish(inference.json())
    run_path = f"{path}/runs/{prediction['id']}"
    evidence = client.get(f"{run_path}/frames?limit=2").json()
    assert evidence["total"] == 3
    assert evidence["items"][0]["frame_points"][0]["x"] == 10
    assert evidence["items"][0]["review_source"] is None
    assert prediction["identity_run_id"] is None
    request = {
        "base_revision": 0,
        "confirmed": True,
        "frames": [{"frame_index": 0, "source": "refined"}],
    }
    review = client.post(f"{run_path}/reviews", json=request)
    assert review.status_code == 201, review.text
    assert review.json()["accepted_frame_count"] == 1
    assert client.post(f"{run_path}/reviews", json=request).status_code == 409
    assert client.get(f"{run_path}/frames?limit=1").json()["items"][0]["review_source"] == "refined"
    _measurement_reuses_reviewed_revision(client, path, run_path, prediction, review.json())
    evaluation = client.post(
        f"{path}/runs",
        json={
            "kind": "evaluation",
            "dataset_id": dataset["id"],
            "temporal_model_id": temporal_model_id,
            "bootstrap_samples": 0,
            "device": "cpu",
            "anatomical_events": {
                "landmark_a_id": "base",
                "landmark_b_id": "tip",
                "open_threshold_px": 20,
                "close_threshold_px": 10,
            },
        },
    )
    assert evaluation.status_code == 202, evaluation.text
    evaluated = finish(evaluation.json())
    assert evaluated["result"]["evaluation_status"] == "exploratory"
    assert evaluated["result"]["frame_lineage_state"] == "unverified"
    assert evaluated["result"]["metrics"]["anatomical_events"] is not None
    _exchange_review(client, path, dataset, prediction, review.json())


def _measurement_reuses_reviewed_revision(
    client: TestClient,
    path: str,
    run_path: str,
    inference: dict[str, Any],
    review: dict[str, Any],
) -> None:
    from reefvision.jobs.pose_biological_measurement import process_pose_biological_measurement_job

    project_id = path.split("/")[-2]
    measurement = client.post(
        f"/api/v1/projects/{project_id}/pose-measurement-runs",
        json={
            "video_id": inference["result"]["source_video_id"],
            "source_identity_run_id": review["identity_run_id"],
            "source_identity_run_revision": review["revision"],
            "identity_ids": [review["identity_id"]],
            "verification_mode": "scientific",
            "definitions": [
                {
                    "id": "offset",
                    "name": "Displacement",
                    "kind": "displacement",
                    "landmark_ids": ["base"],
                }
            ],
        },
    )
    assert measurement.status_code == 202, measurement.text
    app = client.app
    assert process_pose_biological_measurement_job(
        app.state.settings, app.state.session_factory, measurement.json()["id"]
    )
    detail = client.get(f"/api/v1/jobs/{measurement.json()['id']}").json()
    assert detail["status"] == "completed", detail
    measurement_id = detail["result_json"]["run_id"]
    series = client.get(f"/api/v1/pose-measurement-runs/{measurement_id}/series").json()
    event_request = {
        "measurement_run_id": measurement_id,
        "cycles": [
            {"measurement_series_id": series[0]["id"], "open_threshold": 3, "close_threshold": 1}
        ],
    }
    event = client.post(f"/api/v1/projects/{project_id}/pose-event-runs", json=event_request)
    assert event.status_code == 202, event.text
    assert process_pose_biological_measurement_job(
        app.state.settings, app.state.session_factory, event.json()["id"]
    )
    corrected = client.post(
        f"{run_path}/reviews",
        json={
            "base_revision": 1,
            "confirmed": True,
            "frames": [
                {
                    "frame_index": 0,
                    "source": "refined",
                    "corrections": [{"landmark_id": "base", "x": 12, "y": 10}],
                }
            ],
        },
    )
    assert corrected.status_code == 201, corrected.text
    stale = client.post(f"/api/v1/projects/{project_id}/pose-event-runs", json=event_request)
    assert stale.status_code == 400, stale.text
    assert "stale" in stale.json()["detail"]
    historical = client.get(f"/api/v1/pose-measurement-runs/{measurement_id}").json()
    assert historical["status"] == "completed" and historical["source_identity_run_revision"] == 1
    assert historical["source_stale"] is True
    assert historical["pose_output_provenance"]["review_revision"] == 1


def _exchange_review(
    client: TestClient,
    path: str,
    dataset: dict[str, Any],
    prediction: dict[str, Any],
    review: dict[str, Any],
) -> None:
    from reefvision.jobs.project_exchange import process_project_exchange_export_job
    from reefvision.tests.test_scientific_project_exchange import import_archive, rewrite

    project_id = path.split("/")[-2]
    queued = client.post(
        f"/api/v1/projects/{project_id}/exchange-packages",
        json={"include_media": False, "include_model_weights": True},
    )
    assert queued.status_code == 202, queued.text
    job = queued.json()
    assert process_project_exchange_export_job(
        client.app.state.settings, client.app.state.session_factory, job["job_id"]
    )
    exported = client.get(f"/api/v1/exchange-packages/{job['package']['id']}/download")
    assert exported.status_code == 200, exported.text

    def change_target(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        frozen = sections["temporal_reefpose_datasets"][0]
        frozen["manifest_json"]["sources"][0]["frames"][0]["target_points"][0]["x"] = 50
        frozen["manifest_sha256"] = canonical_json_sha256(frozen["manifest_json"])

    tampered = import_archive(client, rewrite(exported.content, change_target))
    assert tampered.status_code == 400, tampered.text
    assert "targets differ from reviewed landmarks" in tampered.text
    imported = import_archive(client, exported.content)
    assert imported.status_code == 201, imported.text
    new_path = f"/api/v1/projects/{imported.json()['project_id']}/temporal-reefpose"
    new_datasets = client.get(f"{new_path}/datasets").json()
    assert len(new_datasets) == 1 and new_datasets[0]["id"] != dataset["id"]
    new_run = next(
        row for row in client.get(f"{new_path}/runs").json() if row["kind"] == "inference"
    )
    assert new_run["id"] != prediction["id"]
    assert new_run["identity_id"] != review["identity_id"]
    assert not new_run["source_stale"]
    imported_frames = client.get(f"{new_path}/runs/{new_run['id']}/frames").json()
    assert imported_frames["items"][0]["review_source"] == "refined"
    from reefvision.jobs.temporal_reefpose import process_temporal_reefpose_job

    refit = client.post(f"{new_path}/runs", json=new_run["configuration"])
    assert refit.status_code == 202, refit.text
    assert process_temporal_reefpose_job(
        client.app.state.settings, client.app.state.session_factory, refit.json()["job_id"]
    )
    repeated = client.get(f"{new_path}/runs/{refit.json()['id']}").json()
    assert repeated["status"] == "succeeded", repeated


def test_temporal_nodes_connect_and_replay_a_saved_evaluation(client: TestClient) -> None:
    from reefvision.tests.test_project_exchange_reefpose_workflow import _execute

    path, sources = _setup(client)
    project_id = path.split("/")[-2]
    graph = {
        "graph_id": "temporal-sequence-workflow",
        "name": "Temporal sequence workflow",
        "nodes": [
            {
                "node_id": "freeze",
                "node_type": "temporal_reefpose_dataset",
                "parameters": {"name": "Frozen connected", "sources": sources},
            },
            {
                "node_id": "train",
                "node_type": "temporal_reefpose_training",
                "parameters": {
                    "name": "Connected model",
                    "epochs": 1,
                    "window_length": 3,
                    "channels": 4,
                    "batch_size": 2,
                    "device": "cpu",
                },
            },
            {
                "node_id": "evaluate",
                "node_type": "temporal_reefpose_evaluation",
                "parameters": {"device": "cpu", "bootstrap_samples": 0},
            },
        ],
        "edges": [
            {
                "edge_id": f"{source}-{target}",
                "source_node_id": source,
                "source_port_id": port,
                "target_node_id": target,
                "target_port_id": port,
            }
            for source, port, target in (
                ("freeze", "dataset", "train"),
                ("freeze", "dataset", "evaluate"),
                ("train", "model", "evaluate"),
            )
        ],
    }
    endpoint = f"/api/v1/projects/{project_id}/workflow-graphs"
    saved = client.post(endpoint, json={"graph": graph})
    assert saved.status_code == 201, saved.text
    completed = _execute(client, project_id, saved.json()["id"])
    assert completed["run"]["status"] == "succeeded", completed
    report = next(
        row["payload_json"]
        for row in completed["artifacts"]
        if row["data_type"] == "temporal_reefpose_evaluation"
    )

    graph["nodes"] = [
        {
            "node_id": "evaluate",
            "node_type": "temporal_reefpose_evaluation",
            "parameters": {"saved_run_id": report["run_id"]},
        }
    ]
    graph["edges"] = []
    replay_graph = client.post(endpoint, json={"graph": graph, "create_new_revision": True})
    assert replay_graph.status_code == 201, replay_graph.text
    replay = _execute(client, project_id, replay_graph.json()["id"])
    assert replay["run"]["status"] == "succeeded", replay
    assert replay["artifacts"][0]["payload_json"] == report
