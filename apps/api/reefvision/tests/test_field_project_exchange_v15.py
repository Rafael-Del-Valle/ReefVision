from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_field_capture_v15 import (
    _batch,
    _capture,
    _image,
    _metadata,
    _project,
    _reconcile,
    _root,
    _seal,
)

MANIFEST = "reefvision-exchange-manifest.json"


def _run(client: TestClient, project: str, graph_id: str) -> dict:
    queued = client.post(
        f"/api/v1/projects/{project}/workflow-runs", json={"graph_record_id": graph_id}
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    process_workflow_run_job(app.state.settings, app.state.session_factory, queued.json()["job_id"])
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
    assert detail["run"]["status"] == "succeeded", detail
    [artifact] = [
        a for a in detail["artifacts"] if a["data_type"] == "field_capture_reconciliation"
    ]
    return artifact["payload_json"]


def _export(client: TestClient, project: str) -> bytes:
    queued = client.post(
        f"/api/v1/projects/{project}/exchange-packages",
        json={"include_media": True, "include_generated_artifacts": True},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        app.state.settings, app.state.session_factory, queued.json()["job_id"]
    )
    archive = client.get(f"/api/v1/exchange-packages/{queued.json()['package']['id']}/download")
    assert archive.status_code == 200, archive.text
    return archive.content


def _transfer(client: TestClient, archive: bytes, label: str) -> dict:
    file = {"file": ("project.reefvision.zip", archive)}
    inspection = client.post("/api/v1/exchange-packages/inspect", files=file)
    assert inspection.json()["compatible"], inspection.text
    response = client.post(
        "/api/v1/exchange-packages/import", files=file, data={"project_name": label}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _fixture(client: TestClient) -> dict:
    project = _project(client, "Field Exchange original")
    root = _root(project)
    image = _image()
    first_batch = _batch(client, root, "First field visit")
    first = _capture(client, root, first_batch, "first.png", image, _metadata())
    _reconcile(client, root, _seal(client, root, first_batch))
    second_batch = _batch(client, root, "Second field visit")
    disagreement = _metadata(known=False)
    # A UUID-looking field note is literal researcher evidence, even through two copies.
    disagreement["notes"] = first["id"]
    second = _capture(client, root, second_batch, "same.png", image, disagreement)
    second_seal = _seal(client, root, second_batch)
    result = _reconcile(client, root, second_seal)
    assert result["rows"][0]["outcome"] == "conflict"
    reviewed = client.post(
        f"{root}/batches/{second_batch}/reviews",
        json={
            "observation_id": second["id"],
            "against_observation_id": first["id"],
            "reviewer": "Synthetic adjudicator",
            "decision": "retain_both",
            "notes": first["id"],
        },
    )
    assert reviewed.status_code == 200, reviewed.text

    video = (
        Path(__file__).resolve().parents[4]
        / "apps/web/tests/e2e/fixtures/synthetic-ordinary-clip.mp4"
    ).read_bytes()
    draft = _batch(client, root, "Draft field recording")
    staged = _capture(client, root, draft, "draft.mp4", video, _metadata(key="clip", known=False))
    graph = {
        "graph_id": "saved-field-exchange",
        "name": "Saved field exchange reconciliation",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "reconcile",
                "node_type": "field_capture_reconcile",
                "parameters": {
                    "batch_id": second_batch,
                    "manifest_sha256": second_seal["manifest_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-reconcile",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "reconcile",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"/api/v1/projects/{project}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    graph_id = saved.json()["id"]
    assert _run(client, project, graph_id) == result
    [run] = client.get(f"/api/v1/projects/{project}/workflow-runs").json()
    return dict(
        project=project,
        first_batch=first_batch,
        first=first,
        second_batch=second_batch,
        second=second,
        second_seal=second_seal,
        draft=draft,
        staged=staged,
        graph=graph_id,
        run=run["id"],
        review=reviewed.json(),
        result=result,
        image=image,
        video=video,
    )


def test_field_exchange_preserves_staged_and_reconciled_evidence_on_two_hops(
    client: TestClient,
) -> None:
    source = _fixture(client)
    current_project = source["project"]
    old_current = None
    for index in (1, 2):
        archived = _export(client, current_project)
        with ZipFile(BytesIO(archived)) as package:
            manifest = json.loads(package.read(MANIFEST))
            assert manifest["format_version"] == "1.5"
            for media in (source["image"], source["video"]):
                physical_members = [
                    name
                    for name in package.namelist()
                    if name.startswith(("media/", "generated/")) and package.read(name) == media
                ]
                assert len(physical_members) == 1, physical_members
        transferred = _transfer(client, archived, f"Field copy {index}")
        current_project = transferred["project_id"]
        options = transferred["package"]["options_json"]
        local = options["origin_id_map"]
        imported_second = local[source["second_batch"]]
        imported_first = local[source["first"]["id"]]
        imported_observation = local[source["second"]["id"]]
        if old_current:
            assert old_current != imported_second
        old_current = imported_second
        root = _root(current_project)
        batch = client.get(f"{root}/batches/{imported_second}").json()
        assert batch["origin_batch_id"] == source["second_batch"]
        assert batch["origin_project_id"] == source["project"]
        assert batch["manifest_sha256"] == source["second_seal"]["manifest_sha256"]
        [capture] = batch["observations"]
        assert capture["id"] == imported_observation
        assert capture["source_observation_id"] == source["second"]["source_observation_id"]
        assert capture["metadata"] == source["second"]["metadata"]
        assert capture["captured_at_utc"] is None
        first_batch = local[source["first_batch"]]
        [known] = client.get(f"{root}/batches/{first_batch}").json()["observations"]
        assert known["metadata"] == source["first"]["metadata"]
        assert known["captured_at_utc"] == source["first"]["captured_at_utc"]
        oldest_report = source["result"]
        report = client.get(f"{root}/batches/{imported_second}/reconciliation").json()
        assert report["report_sha256"] != oldest_report["report_sha256"]
        assert report["rows"][0]["asset_id"] == local[oldest_report["rows"][0]["asset_id"]]
        assert report["rows"][0]["conflicts"][0]["against_observation_id"] == imported_first
        provenance = options["field_reconciliation_origin"][imported_second]
        assert provenance["source_report_sha256"] == oldest_report["report_sha256"]
        assert provenance["local_report_sha256"] == report["report_sha256"]
        assert provenance["source_to_local"][source["second"]["id"]] == imported_observation
        [decision] = client.get(f"{root}/batches/{imported_second}/reviews").json()
        assert decision["observation_id"] == imported_observation
        assert decision["against_observation_id"] == imported_first
        assert decision["notes"] == source["first"]["id"]
        assert decision["decision"] == "retain_both"
        assert decision["reviewer"] == source["review"]["reviewer"]
        assert decision["created_at"] == source["review"]["created_at"]
        cf = client.get(
            f"{root}/batches/{imported_second}/observations/{imported_observation}/content"
        )
        assert cf.content == source["image"]
        draft_id = local[source["draft"]]
        recording_id = local[source["staged"]["id"]]
        draft = client.get(f"{root}/batches/{draft_id}").json()
        assert draft["manifest_sha256"] is None
        recording = client.get(f"{root}/batches/{draft_id}/observations/{recording_id}/content")
        assert recording.content == source["video"]
        historical = client.get(f"/api/v1/workflow-runs/{local[source['run']]}").json()
        [artifact] = [
            item
            for item in historical["artifacts"]
            if item["data_type"] == "field_capture_reconciliation"
        ]
        assert historical["run"]["status"] == "succeeded"
        assert artifact["payload_json"] == report
        assert artifact["payload_sha256"] == canonical_json_sha256(report)
        assert _run(client, current_project, local[source["graph"]]) == report


@pytest.mark.parametrize(
    "alter", ["missing", "changed_source", "foreign_review", "missing_canonical", "foreign_receipt"]
)
def test_field_exchange_rejects_invalid_sources_before_project_creation(
    client: TestClient,
    test_settings: Settings,
    alter: str,
) -> None:
    source = _fixture(client)
    archive = _export(client, source["project"])
    if alter == "foreign_receipt":
        imported = _transfer(client, archive, "Field receipt origin to audit")
        archive = _export(client, imported["project_id"])
    with ZipFile(BytesIO(archive)) as package:
        members = {name: package.read(name) for name in package.namelist()}
    manifest = json.loads(members[MANIFEST])
    if alter == "foreign_receipt":
        provenance = next(
            item
            for item in manifest["field_reconciliation_origin"].values()
            if item["source_batch_id"] == source["second_batch"]
        )
        invented_alias = "f143b7fc-6487-4b3d-a084-016c973138b5"
        asset_id = source["result"]["rows"][0]["asset_id"]
        provenance["source_to_local"][invented_alias] = provenance["source_to_local"].pop(asset_id)
        original = dict(source["result"])
        original["rows"][0]["asset_id"] = invented_alias
        original.pop("report_sha256")
        provenance["source_report_sha256"] = canonical_json_sha256(original)
    elif alter == "missing_canonical":
        item = next(d for d in manifest["media"] if d["kind"] == "image")
        alias = next(
            d
            for d in manifest["media"]
            if d["kind"] == "field_source" and d["path"] == item["path"]
        )
        original = members.pop(item["path"])
        alias["path"] = f"media/field/{item['sha256']}"
        members[alias["path"]] = original
        manifest["media"].remove(item)
    elif alter == "foreign_review":
        section = manifest["sections"]["field_capture_reviews"]
        review = json.loads(members[section["path"]])
        review["against_observation_id"] = "f143b7fc-6487-4b3d-a084-016c973138b5"
        changed = (json.dumps(review, sort_keys=True, separators=(",", ":")) + "\n").encode()
        members[section["path"]] = changed
        section["sha256"] = hashlib.sha256(changed).hexdigest()
    else:
        item = next(
            d
            for d in manifest["media"]
            if d["kind"] == "field_source"
            and d["sha256"] == hashlib.sha256(source["video"]).hexdigest()
        )
        if alter == "missing":
            members.pop(item["path"])
        else:
            original = members[item["path"]]
            members[item["path"]] = original[:-1] + bytes([original[-1] ^ 1])
    members[MANIFEST] = json.dumps(manifest).encode()
    altered = BytesIO()
    with ZipFile(altered, "w") as package:
        for name, content in members.items():
            package.writestr(name, content)
    directories = set((test_settings.resolved_data_dir / "projects").iterdir())
    projects = client.get("/api/v1/projects").json()
    files = {"file": ("invalid.reefvision.zip", altered.getvalue())}
    inspection = client.post("/api/v1/exchange-packages/inspect", files=files)
    assert not inspection.json()["compatible"], inspection.text
    rejection = client.post(
        "/api/v1/exchange-packages/import", files=files, data={"project_name": "Must not persist"}
    )
    assert rejection.status_code == 400, rejection.text
    assert client.get("/api/v1/projects").json() == projects
    assert set((test_settings.resolved_data_dir / "projects").iterdir()) == directories
