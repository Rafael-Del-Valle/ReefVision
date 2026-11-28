from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, ModelRuntimeSelection, ProjectExchangePackage
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.models import ModelService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_model_inference import (
    FakeDetectorRegistrationProvider,
    FakeDetectorWorkerProvider,
    approve_generated_checkpoint,
    register_model,
)
from reefvision.tests.test_scientific_project_exchange import import_archive, rewrite


@pytest.fixture
def local_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixtureRegistration(FakeDetectorRegistrationProvider):
        provider_name = "ultralytics"

    monkeypatch.setattr(ModelService, "_provider_for_purpose", lambda *_: FixtureRegistration())
    monkeypatch.setattr(
        "reefvision.jobs.inference.detection_provider_for_name",
        lambda _: FakeDetectorWorkerProvider(),
    )
    monkeypatch.setattr(
        "reefvision.ml.reviewed_runtime.get_model_provider",
        lambda *_: SimpleNamespace(availability_status="ready", package_version="fixture-provider"),
    )
    monkeypatch.setattr(
        "reefvision.ml.reviewed_runtime.cached_runtime_provider_statuses",
        lambda: SimpleNamespace(
            value=[
                SimpleNamespace(
                    runtime_id="pytorch",
                    available=True,
                    package_version="fixture-runtime",
                    cuda_available=False,
                )
            ]
        ),
    )


def test_preview_confirm_queue_reopen_and_reject_replaced_weights(
    client: TestClient, local_detector: None
) -> None:
    project = create_project(client)["id"]
    image = import_one(client, project)["successful"][0]["image_id"]
    model = register_model(
        client, project, purpose="detector", filename="fixture.pt", display_name="Fixture detector"
    )
    base = f"/api/v1/projects/{project}"
    choices = base + "/model-runtime-selections"
    draft = {
        "model_id": model["id"],
        "runtime_id": "pytorch",
        "device": "cpu",
        "prompt": "confidence 0.47, iou 0.38",
    }
    response = client.post(choices + "/preview", json=draft)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["snapshot"]["checkpoint_sha256"] == model["sha256"]
    assert preview["snapshot"]["settings"] == {
        "confidence_threshold": 0.47,
        "iou_threshold": 0.38,
        "device": "cpu",
    }
    assert client.get(choices).json() == []
    confirm = {"draft": draft, "reviewed_sha256": preview["content_sha256"]}
    assert client.post(choices, json={**confirm, "reviewed_sha256": "0" * 64}).status_code == 409
    saved = client.post(choices, json=confirm)
    assert saved.status_code == 201, saved.text
    pin = saved.json()
    assert client.post(choices, json=confirm).json()["id"] == pin["id"]
    assert client.get(choices).json() == [pin]
    assert client.get(choices + "/" + pin["id"]).json() == pin
    assert (
        client.post(choices + "/preview", json={**draft, "runtime_id": "onnxruntime"}).status_code
        == 400
    )
    assert (
        client.post(choices + "/preview", json={**draft, "prompt": "install weights"}).status_code
        == 400
    )
    other = create_project(client, "Other")["id"]
    assert (
        client.get(f"/api/v1/projects/{other}/model-runtime-selections/{pin['id']}").status_code
        == 404
    )
    assert client.delete("/api/v1/models/" + model["id"]).status_code == 409
    infer = {"model_id": model["id"], "image_ids": [image], "runtime_selection_id": pin["id"]}
    assert (
        client.post(base + "/inference-jobs", json={**infer, "device": "cuda"}).status_code == 409
    )
    app = cast(FastAPI, client.app)
    queued = client.post(base + "/inference-jobs", json=infer)
    assert queued.status_code == 200, queued.text
    with app.state.session_factory() as session:
        job = session.get(Job, queued.json()["id"])
        assert job.request_json["runtime_selection_sha256"] == pin["content_sha256"]
        assert job.request_json["confidence_threshold"] == 0.47
        assert job.request_json["device"] == "cpu"
    assert process_inference_job(app.state.settings, app.state.session_factory, queued.json()["id"])
    parameters = {"selection_id": pin["id"], "selection_sha256": pin["content_sha256"]}
    graph = {
        "graph_id": "reviewed-runtime",
        "name": "Replay reviewed model runtime",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "reviewed_model_runtime", "parameters": parameters},
            {"node_id": "images", "node_type": "project_images"},
            {"node_id": "infer", "node_type": "detection_inference"},
        ],
        "edges": [
            {
                "edge_id": "pm",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            },
            {
                "edge_id": "pi",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            },
            {
                "edge_id": "id",
                "source_node_id": "images",
                "source_port_id": "images",
                "target_node_id": "infer",
                "target_port_id": "images",
            },
            {
                "edge_id": "md",
                "source_node_id": "m",
                "source_port_id": "model",
                "target_node_id": "infer",
                "target_port_id": "model",
            },
        ],
    }
    saved_graph = client.post(base + "/workflow-graphs", json={"graph": graph})
    assert saved_graph.status_code == 201, saved_graph.text

    def replay() -> dict[str, Any]:
        queued = client.post(
            base + "/workflow-runs", json={"graph_record_id": saved_graph.json()["id"]}
        ).json()
        process_workflow_run_job(app.state.settings, app.state.session_factory, queued["job_id"])
        return client.get("/api/v1/workflow-runs/" + queued["id"]).json()

    outputs = [replay(), replay()]
    assert all(run["run"]["status"] == "succeeded" for run in outputs)
    pins = [
        next(a for a in run["artifacts"] if a["data_type"] == "reviewed_model_reference")
        for run in outputs
    ]
    assert pins[0]["payload_sha256"] == pins[1]["payload_sha256"]
    for result in outputs:
        proposals = next(
            a["payload_json"]
            for a in result["artifacts"]
            if a["data_type"] == "detection_proposals"
        )
        assert (
            proposals["detections"][0]["provenance"]["runtime_selection_sha256"]
            == pin["content_sha256"]
        )
        job = client.get("/api/v1/jobs/" + proposals["inference_job_id"]).json()
        assert (
            job["request_json"]["confidence_threshold"] == 0.47
            and job["request_json"]["device"] == "cpu"
        )
    assert pins[0]["payload_json"]["runtime_selection_sha256"] == pin["content_sha256"]
    queued = client.post(base + "/inference-jobs", json=infer).json()
    resolve_managed_project_path(app.state.settings, model["managed_path"]).write_bytes(
        b"replaced fixture"
    )
    assert not process_inference_job(app.state.settings, app.state.session_factory, queued["id"])
    assert (
        "checkpoint" in client.get("/api/v1/jobs/" + queued["id"]).json()["error_message"].lower()
    )
    assert replay()["run"]["status"] == "failed"
    assert client.get(choices).json() == [pin]


def test_exchange_restores_runtime_receipt_model_and_mapped_classes_across_two_copies(
    client: TestClient, local_detector: None
) -> None:
    app = cast(FastAPI, client.app)
    project = create_project(client)["id"]
    model = register_model(
        client, project, purpose="detector", filename="fixture.pt", display_name="Portable fixture"
    )
    image = import_one(client, project)["successful"][0]["image_id"]
    base = "/api/v1/projects/" + project
    draft = {"model_id": model["id"], "runtime_id": "pytorch", "device": "cpu"}
    preview = client.post(base + "/model-runtime-selections/preview", json=draft).json()
    saved = client.post(
        base + "/model-runtime-selections",
        json={"draft": draft, "reviewed_sha256": preview["content_sha256"]},
    ).json()
    assert saved["snapshot"]["class_mapping"]
    original = saved["content_sha256"]
    for index in range(2):
        queued = client.post(
            base + "/exchange-packages", json={"include_media": True, "include_model_weights": True}
        ).json()
        assert process_project_exchange_export_job(
            app.state.settings, app.state.session_factory, queued["job_id"]
        )
        raw = client.get(
            "/api/v1/exchange-packages/" + queued["package"]["id"] + "/download"
        ).content
        if index == 0:

            def change(manifest: dict[str, Any], sections: dict[str, list[dict[str, Any]]]) -> None:
                row = sections["model_runtime_selections"][0]
                row["snapshot_json"]["settings"]["confidence_threshold"] = 0.99

            damaged = import_archive(client, rewrite(raw, change))
            assert damaged.status_code == 400 and "receipt" in damaged.text.lower(), damaged.text
        result = import_archive(client, raw)
        assert result.status_code == 201, result.text
        report = result.json()
        local = report["package"]["options_json"]["id_map"]
        base = "/api/v1/projects/" + report["project_id"]
        copied = client.get(base + "/model-runtime-selections/" + local[saved["id"]]).json()
        assert copied["snapshot"] == saved["snapshot"] and copied["content_sha256"] == original
        assert copied["model_id"] == local[saved["model_id"]]
        image = local[image]
        approve_generated_checkpoint(
            client, report["project_id"], copied["model_id"], model["sha256"]
        )
        job = client.post(
            base + "/inference-jobs",
            json={
                "model_id": copied["model_id"],
                "runtime_selection_id": copied["id"],
                "image_ids": [image],
            },
        )
        assert job.status_code == 200, job.text
        assert process_inference_job(
            app.state.settings, app.state.session_factory, job.json()["id"]
        )
        # The row's aliases must match the independently retained import map.
        # A self-consistent but forged mapping cannot authorize a live execution.
        with app.state.session_factory() as session:
            selected = session.get(ModelRuntimeSelection, copied["id"])
            assert selected is not None
            aliases = dict(selected.source_id_map_json)
            for field in ("source_project_id", "source_model_id"):
                source_id = copied["snapshot"][field]
                selected.source_id_map_json = {
                    **aliases,
                    source_id: image,
                }
                session.commit()
                rejected = client.post(
                    base + "/inference-jobs",
                    json={
                        "model_id": copied["model_id"],
                        "runtime_selection_id": copied["id"],
                        "image_ids": [image],
                    },
                )
                assert rejected.status_code == 409, rejected.text
                assert "source project or model linkage" in rejected.json()["detail"]
            selected.source_id_map_json = aliases
            session.commit()
        saved = copied


def test_historical_receipt_keeps_original_digest_and_requires_a_new_execution_review(
    client: TestClient,
    local_detector: None,
) -> None:
    app = cast(FastAPI, client.app)
    project = create_project(client)["id"]
    model = register_model(
        client,
        project,
        purpose="detector",
        filename="historic.pt",
        display_name="Historic fixture",
    )
    image = import_one(client, project)["successful"][0]["image_id"]
    base = f"/api/v1/projects/{project}"
    address = f"{base}/model-runtime-selections"
    draft = {"model_id": model["id"], "runtime_id": "pytorch", "device": "cpu"}
    current = client.post(f"{address}/preview", json=draft).json()
    snapshot = {
        key: value
        for key, value in current["snapshot"].items()
        if key not in {"class_mapping", "applied_image_settings"}
    }
    digest = canonical_json_sha256(snapshot)
    with app.state.session_factory() as session:
        selection = ModelRuntimeSelection(
            project_id=project,
            model_id=model["id"],
            snapshot_json=snapshot,
            content_sha256=digest,
        )
        session.add(selection)
        session.commit()
        selection_id = selection.id
    local_model = model["id"]
    for copy in range(3):
        reopened = client.get(f"{address}/{selection_id}")
        assert reopened.status_code == 200, reopened.text
        receipt = reopened.json()
        assert receipt["snapshot"] == snapshot and receipt["content_sha256"] == digest
        assert receipt["requires_re_review"] is True
        assert client.get(address).json() == [receipt]
        assert canonical_json_sha256(receipt["snapshot"]) == digest
        failed = client.post(
            f"{base}/inference-jobs",
            json={
                "model_id": local_model,
                "image_ids": [image],
                "runtime_selection_id": selection_id,
            },
        )
        assert failed.status_code == 409 and "review" in failed.json()["detail"].lower()
        if copy == 2:
            break
        queued = client.post(
            f"{base}/exchange-packages", json={"include_media": True, "include_model_weights": True}
        ).json()
        assert process_project_exchange_export_job(
            app.state.settings,
            app.state.session_factory,
            queued["job_id"],
        )
        files = client.get(f"/api/v1/exchange-packages/{queued['package']['id']}/download").content
        inspected = client.post(
            "/api/v1/exchange-packages/inspect",
            files={"file": ("historical.zip", files)},
        )
        assert inspected.status_code == 200 and inspected.json()["compatible"], inspected.text
        if copy == 0:

            def alter_original_id(
                _: dict[str, Any],
                rows: dict[str, list[dict[str, Any]]],
            ) -> None:
                (archived,) = rows["model_runtime_selections"]
                archived["snapshot_json"]["source_project_id"] = model["id"]
                archived["content_sha256"] = canonical_json_sha256(archived["snapshot_json"])

            tampered = import_archive(client, rewrite(files, alter_original_id))
            assert tampered.status_code == 400 and "receipt" in tampered.text.lower()
        restored = import_archive(client, files)
        assert restored.status_code == 201, restored.text
        row = restored.json()
        alias = row["package"]["options_json"]["id_map"]
        if copy == 0:
            # Early Project Exchange persisted only its immediate ID map.
            with app.state.session_factory() as session:
                package = session.get(ProjectExchangePackage, row["package"]["id"])
                assert package is not None
                package.options_json = {
                    key: value
                    for key, value in package.options_json.items()
                    if key != "origin_id_map"
                }
                session.commit()
        selection_id, local_model, image = (
            alias[key] for key in (selection_id, local_model, image)
        )
        base = f"/api/v1/projects/{row['project_id']}"
        address = f"{base}/model-runtime-selections"

    draft["model_id"] = local_model
    preview = client.post(f"{address}/preview", json=draft)
    assert preview.status_code == 200, preview.text
    fresh_preview = preview.json()
    assert fresh_preview["content_sha256"] != digest
    fresh = client.post(
        address, json={"draft": draft, "reviewed_sha256": fresh_preview["content_sha256"]}
    )
    assert fresh.status_code == 201 and fresh.json()["requires_re_review"] is False, fresh.text
    assert client.get(f"{address}/{selection_id}").json()["snapshot"] == snapshot
    request = {
        "model_id": local_model,
        "image_ids": [image],
        "runtime_selection_id": fresh.json()["id"],
    }
    pending = client.post(f"{base}/inference-jobs", json=request)
    assert pending.status_code == 400 and "approve" in pending.json()["detail"].lower()
    approve_generated_checkpoint(client, row["project_id"], local_model, model["sha256"])
    ready = client.post(f"{base}/inference-jobs", json=request)
    assert ready.status_code == 200, ready.text
    assert process_inference_job(app.state.settings, app.state.session_factory, ready.json()["id"])
