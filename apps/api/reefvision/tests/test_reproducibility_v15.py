"""Exercise portable reproducibility proof through ordinary Exchange and Workflow Builder."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from uuid import uuid4
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.paired_models_v15 import process_comparison
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.tests.test_model_comparison_stills_v15 import (
    _confirm_runtime,
    _dataset,
    _register,
)
from reefvision.tests.test_model_comparison_stills_v15 import (
    reviewed_runtime as reviewed_runtime_fixture,
)
from reefvision.tests.test_reviewer_lab_v15 import judgement, make_round, role_fixture, successful
from reefvision.tests.test_study_design_v15 import _declaration

reviewed_runtime = reviewed_runtime_fixture
REPRO = "/api/v1/reproducibility-packages"


def test_export_requires_project_owned_frozen_evidence(client: TestClient) -> None:
    project = client.post(
        "/api/v1/projects", json={"name": "Reproducibility fixture", "template": "blank"}
    )
    assert project.status_code == 201, project.text
    new_id = str(uuid4())
    response = client.post(
        f"/api/v1/projects/{project.json()['id']}/reproducibility-packages",
        json={
            "study_design_id": new_id,
            "reviewer_report_id": new_id,
            "comparison_id": new_id,
        },
    )
    assert response.status_code == 404, response.text
    assert "study design" in response.json()["detail"].lower()


def _fixture(client: TestClient) -> tuple[str, dict[str, str], list[str]]:
    project, class_id, images, dataset = _dataset(client)
    endpoint = f"/api/v1/projects/{project}"
    for index, treatment in enumerate(("reference", "comparison")):
        tank = f"Tank-{index + 1}"
        successful(
            client.post(
                f"{endpoint}/ecology/organisms",
                json={
                    "kind": "colony",
                    "organism_key": treatment,
                    "experimental_unit_type": "tank",
                    "experimental_unit_id": tank,
                    "reason": "Research package fixture enrollment",
                    "study_assignment": {
                        "tank_code": tank,
                        "treatment_code": treatment,
                        "reviewer": "Experiment reviewer",
                        "confirm_review": True,
                    },
                },
            ),
            201,
        )
    today = datetime.now(UTC).date()
    declaration = _declaration("prospective")
    declaration["organism_keys"] = ["reference", "comparison"]
    declaration["contrast"].update(
        baseline_date=(today + timedelta(days=1)).isoformat(),
        followup_date=(today + timedelta(days=2)).isoformat(),
    )
    study = successful(
        client.post(
            f"{endpoint}/ecology/study-designs",
            json={"declaration": declaration},
        ),
        201,
    )

    _, lab, roles = role_fixture(client, project)
    plan = make_round(client, lab, roles, [{"type": "image", "id": images["first"]}])
    round_url = f"{lab}/rounds/{plan['id']}"
    subject_url = f"{round_url}/subjects/{plan['subjects'][0]['id']}"
    for name in ("Reviewer A", "Reviewer B"):
        successful(
            client.post(
                f"{subject_url}/decision",
                headers=roles[name][1],
                json=judgement(plan, "usable", "Original suitability reviewed independently"),
            ),
            201,
        )
    review = successful(client.post(f"{round_url}/seal", headers=roles["Manager"][1]), 201)
    models = [
        _register(client, project, dataset, class_id, "detect", label)
        for label in ("left", "right")
    ]
    left, right = [
        {"id": pin["runtime_selection_id"], "sha256": pin["runtime_selection_sha256"]}
        for pin in (_confirm_runtime(client, project, model) for model in models)
    ]
    comparison = successful(
        client.post(
            f"{endpoint}/paired-model-comparisons",
            json={
                "task": "detector",
                "left": left,
                "right": right,
                "sources": [{"id": dataset["id"], "sha256": dataset["manifest_sha256"]}],
            },
        ),
        202,
    )
    app = cast(FastAPI, client.app)
    assert process_comparison(app.state.settings, app.state.session_factory, comparison["id"])
    response = successful(client.get(f"{endpoint}/paired-model-comparisons/{comparison['id']}"))
    assert response["status"] == "succeeded", response
    return (
        project,
        {
            "study_design_id": study["id"],
            "reviewer_report_id": review["id"],
            "comparison_id": comparison["id"],
        },
        [headers["Authorization"].split()[-1] for _, headers in roles.values()],
    )


def _export(
    client: TestClient,
    project: str,
    selection: dict[str, Any],
    *,
    with_weights: bool,
    with_media: bool,
) -> tuple[dict[str, Any], bytes]:
    endpoint = f"/api/v1/projects/{project}/reproducibility-packages"
    body = {**selection, "include_model_weights": with_weights, "include_media": with_media}
    queued = successful(client.post(endpoint, json=body), 202)
    identifier = queued["package"]["id"]
    assert queued["package"]["status"] == "queued"
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        app.state.settings, app.state.session_factory, queued["job_id"]
    ), successful(client.get(f"{REPRO}/{identifier}"))
    package = successful(client.get(f"{REPRO}/{identifier}"))
    assert package["status"] == "complete"
    assert package in client.get(endpoint).json()
    raw = client.get(f"{REPRO}/{identifier}/download")
    assert raw.status_code == 200 and raw.content
    assert ".reproducibility.zip" in raw.headers["Content-Disposition"]
    return package, raw.content


def _save_graph(client: TestClient, project: str, proof: str) -> str:
    graph = {
        "graph_id": "research-fixture-proof",
        "name": "Frozen package proof",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "proof",
                "node_type": "research_reproducibility_package",
                "parameters": {"proof_sha256": proof},
            },
        ],
        "edges": [
            {
                "edge_id": "project-proof",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "proof",
                "target_port_id": "project",
            }
        ],
    }
    return str(
        successful(
            client.post(f"/api/v1/projects/{project}/workflow-graphs", json={"graph": graph}), 201
        )["id"]
    )


def _replay(client: TestClient, project: str, graph: str, body: dict[str, Any]) -> str:
    queued = successful(
        client.post(
            f"/api/v1/projects/{project}/workflow-runs",
            json={"graph_record_id": graph},
        ),
        202,
    )
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, queued["job_id"])
    run = successful(client.get(f"/api/v1/workflow-runs/{queued['id']}"))
    assert run["run"]["status"] == "succeeded", run
    (artifact,) = [
        row for row in run["artifacts"] if row["data_type"] == "research_reproducibility_proof"
    ]
    assert artifact["payload_json"] == body
    return str(artifact["payload_sha256"])


def _zip_body(raw: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(raw)) as zip_file:
        return {name: zip_file.read(name) for name in zip_file.namelist()}


def _upload(raw: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("fixture.reproducibility.zip", raw, "application/zip")}


def _archive_with_replacement(
    parts: dict[str, bytes],
    manifest: dict[str, Any],
    path: str,
    body: bytes,
) -> bytes:
    parts[path] = body
    for descriptor in manifest["entries"]:
        if descriptor["path"] == path:
            descriptor["size_bytes"] = len(body)
            descriptor["sha256"] = sha256(body).hexdigest()
    parts["manifest.json"] = canonical_json_bytes(manifest)
    result = BytesIO()
    with ZipFile(result, "w") as target:
        for name, payload in parts.items():
            target.writestr(name, payload)
    return result.getvalue()


def _modified_methods(raw: bytes) -> bytes:
    parts = _zip_body(raw)
    manifest = json.loads(parts["manifest.json"])
    path = "evidence/methods.json"
    methods = json.loads(parts[path])
    methods["review_criterion"] = "Artificially substituted analysis methods"
    manifest["proof"]["section_sha256"]["methods"] = canonical_json_sha256(methods)
    manifest["proof"]["proof_sha256"] = canonical_json_sha256(
        {key: value for key, value in manifest["proof"].items() if key != "proof_sha256"}
    )
    return _archive_with_replacement(parts, manifest, path, canonical_json_bytes(methods))


def _modified_native_inventory(raw: bytes) -> bytes:
    parts = _zip_body(raw)
    manifest = json.loads(parts["manifest.json"])
    path = "project.reefvision.zip"
    native = BytesIO(parts[path])
    with ZipFile(native, "a") as changed:
        changed.writestr("unlisted.json", b"{}")
    return _archive_with_replacement(parts, manifest, path, native.getvalue())


def test_real_evidence_reopens_in_two_copies_and_tampering_is_preflighted(
    client: TestClient,
    reviewed_runtime: None,
) -> None:
    project, entitlements, keys = _fixture(client)
    app = cast(FastAPI, client.app)
    duplicate_checkpoint = (
        app.state.settings.resolved_data_dir
        / "projects"
        / project
        / "training-artifacts"
        / "best.pt"
    )
    duplicate_checkpoint.parent.mkdir()
    duplicate_checkpoint.write_bytes(b"Unselected checkpoint bytes")
    first, first_raw = _export(client, project, entitlements, with_weights=True, with_media=True)
    source_manifest = first["manifest"]
    proof = source_manifest["proof"]
    proof_digest = first["proof_sha256"]
    assert not source_manifest["omitted_sources"]
    parts = _zip_body(first_raw)
    native = _zip_body(parts["project.reefvision.zip"])
    for key in keys:
        assert not any(
            secret in payload
            for secret in (key.encode(), sha256(key.encode()).hexdigest().encode())
            for name, payload in native.items()
            if name.endswith((".json", ".jsonl"))
        )
    assert json.loads(parts["evidence/comparison.json"])["snapshot"]["summary"]["group_count"] == 2
    assert len(json.loads(parts["evidence/environment.json"])["models"]) == 2

    graph = _save_graph(client, project, proof_digest)
    artifact_sha = _replay(client, project, graph, proof)
    assert _replay(client, project, graph, proof) == artifact_sha

    package, raw = _export(client, project, entitlements, with_weights=False, with_media=True)
    assert package["proof_sha256"] == proof_digest
    verified = successful(client.post(f"{REPRO}/inspect", files=_upload(raw)))
    assert verified["compatible"], verified
    assert verified["manifest_sha256"] == canonical_json_sha256(package["manifest"])
    assert len(verified["manifest"]["omitted_sources"]) == 2
    omitted_zip = _zip_body(_zip_body(raw)["project.reefvision.zip"])
    assert not any(name.endswith(".pt") for name in omitted_zip)
    assert b"Unselected checkpoint bytes" not in omitted_zip.values()
    assert all(
        "model inference" in item["requires_relink_for"]
        for item in verified["manifest"]["omitted_sources"]
    )

    before = client.get("/api/v1/projects").json()
    for damaged, diagnostic in (
        (_modified_methods(raw), "differs from the underlying frozen evidence"),
        (_modified_native_inventory(raw), "undeclared"),
    ):
        inspected = successful(client.post(f"{REPRO}/inspect", files=_upload(damaged)))
        assert not inspected["compatible"]
        assert any(diagnostic in error for error in inspected["errors"])
        rejected = client.post(f"{REPRO}/import", files=_upload(damaged))
        assert rejected.status_code == 400 and diagnostic in rejected.json()["detail"]
        assert client.get("/api/v1/projects").json() == before

    for copy in range(2):
        restored = successful(client.post(f"{REPRO}/import", files=_upload(raw)), 201)
        assert restored["proof_sha256"] == proof_digest
        current = restored["project_id"]
        assert current != project
        options = restored["package"]["options_json"]
        origin = options["origin_id_map"]
        row = successful(client.get(f"{REPRO}/{restored['reproducibility_package_id']}"))
        assert row["direction"] == "import" and row["project_id"] == current
        assert client.get(f"{REPRO}/{row['id']}/download").content == raw
        assert _replay(client, current, origin[graph], proof) == artifact_sha
        assert (
            client.get(
                f"/api/v1/projects/{current}/reviewer-lab/session",
                headers={"Authorization": f"Bearer {keys[0]}"},
            ).status_code
            == 401
        )
        project = current
        if copy == 0:
            local = {key: origin[value] for key, value in entitlements.items()}
            package, raw = _export(client, project, local, with_weights=False, with_media=False)
            assert package["proof_sha256"] == proof_digest
            omissions = package["manifest"]["omitted_sources"]
            assert {entry["kind"] for entry in omissions} == {"image", "model"}
