"""Project Exchange must preserve paired comparison receipts and prove their evidence."""

import json
from copy import deepcopy
from io import BytesIO
from typing import Any, cast
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, PredictionProposal, Project
from reefvision.domain.errors import ConflictError
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.services.model_comparison_stills_v15 import _prediction_fields
from reefvision.services.paired_models_v15 import process_comparison, replay, summarize_groups
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_model_comparison_stills_v15 import (
    _confirm_runtime,
    _dataset,
    _register,
)
from reefvision.tests.test_model_comparison_stills_v15 import (
    reviewed_runtime as reviewed_runtime_fixture,
)
from reefvision.tests.test_model_comparison_video_v15 import VideoFixture
from reefvision.tests.test_model_comparison_video_v15 import video_comparison as video_fixture
from reefvision.tests.test_paired_growth_contrast import _run_graph
from reefvision.tests.test_reproducibility_v15 import (
    REPRO,
    _archive_with_replacement,
    _export,
    _upload,
    _zip_body,
)
from reefvision.tests.test_reproducibility_v15 import _fixture as _reproducibility_fixture
from reefvision.tests.test_scientific_project_exchange import import_archive, rewrite

reviewed_runtime = reviewed_runtime_fixture
video_comparison = video_fixture


def _archive(client: TestClient, project: str, *, weights: bool = True) -> bytes:
    app = cast(FastAPI, client.app)
    queued = client.post(
        f"/api/v1/projects/{project}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": weights,
            "include_generated_artifacts": False,
        },
    )
    assert queued.status_code == 202, queued.text
    export = queued.json()
    assert process_project_exchange_export_job(
        app.state.settings, app.state.session_factory, export["job_id"]
    )
    download = client.get(f"/api/v1/exchange-packages/{export['package']['id']}/download")
    assert download.status_code == 200, download.text
    return download.content


def _compare(client: TestClient, task: str) -> tuple[str, str, dict[str, Any]]:
    app = cast(FastAPI, client.app)
    project, cls, _, version = _dataset(client)
    tasks = ("detect", "detect") if task == "detector" else ("segment", "semantic_segment")
    model_a, model_b = [
        _register(client, project, version, cls, kind, side)
        for kind, side in zip(tasks, ("left", "right"), strict=True)
    ]
    # Exchange exports only project-owned files, including these benign worker fixtures.
    with app.state.session_factory() as session:
        project_row = session.get(Project, project)
        for model in (model_a, model_b):
            old = app.state.settings.resolved_data_dir / model.managed_path
            managed = f"{project_row.storage_root}/models/{model.id}.pt"
            destination = app.state.settings.resolved_data_dir / managed
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(old.read_bytes())
            session.get(ModelRegistration, model.id).managed_path = managed
        session.commit()
    choices = [_confirm_runtime(client, project, model) for model in (model_a, model_b)]
    left, right = [
        {"id": pin["runtime_selection_id"], "sha256": pin["runtime_selection_sha256"]}
        for pin in choices
    ]
    root = f"/api/v1/projects/{project}/paired-model-comparisons"
    queued = client.post(
        root,
        json={
            "task": task,
            "left": left,
            "right": right,
            "sources": [{"id": version["id"], "sha256": version["manifest_sha256"]}],
        },
    )
    assert queued.status_code == 202, queued.text
    job = queued.json()["id"]
    assert process_comparison(app.state.settings, app.state.session_factory, job)
    receipt = client.get(f"{root}/{job}").json()
    assert receipt["status"] == "succeeded", receipt
    return project, job, receipt["result_json"]


@pytest.mark.parametrize("task", ["detector", "mask"])
def test_paired_models_preserve_original_report_and_execute_copied_projects(
    client: TestClient,
    test_settings: Settings,
    reviewed_runtime: None,
    task: str,
) -> None:
    app = cast(FastAPI, client.app)
    project, job, original = _compare(client, task)
    graph = {
        "graph_id": f"paired-{task}-exchange",
        "name": "Exact paired comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "paired",
                "node_type": "paired_model_comparison",
                "parameters": {
                    "comparison_id": job,
                    "comparison_sha256": original["content_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "source",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "paired",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"/api/v1/projects/{project}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    graph_id = saved.json()["id"]
    initial = _run_graph(client, project, graph_id)
    assert initial["run"]["status"] == "succeeded", initial
    raw = _archive(client, project)
    for _ in range(2):
        imported = import_archive(client, raw)  # type: ignore[no-untyped-call]
        assert imported.status_code == 201, imported.text
        result = imported.json()
        local = result["project_id"]
        ids = result["package"]["options_json"]["origin_id_map"]
        mapped_job = ids[job]
        url = f"/api/v1/projects/{local}/paired-model-comparisons"
        report = client.get(f"{url}/{mapped_job}").json()["result_json"]
        assert report["snapshot"] == original["snapshot"]
        assert report["content_sha256"] == original["content_sha256"]
        with app.state.session_factory() as session:
            assert replay(session, test_settings, local, mapped_job, report["content_sha256"]) == {
                "snapshot": original["snapshot"],
                "content_sha256": original["content_sha256"],
            }
        historic = client.get(f"/api/v1/workflow-runs/{ids[initial['run']['id']]}").json()
        historic_report = next(
            a for a in historic["artifacts"] if a["data_type"] == "paired_model_report"
        )
        assert historic_report["payload_json"]["snapshot"] == original["snapshot"]
        rerun = _run_graph(client, local, ids[graph_id])
        assert rerun["run"]["status"] == "succeeded", rerun
        raw = _archive(client, local)


@pytest.mark.parametrize("case", ["rehashed-score", "foreign-alias", "missing-png"])
def test_corrupted_paired_archive_rejected_before_import(
    client: TestClient,
    test_settings: Settings,
    reviewed_runtime: None,
    case: str,
) -> None:
    project, job, _ = _compare(client, "mask" if case == "missing-png" else "detector")
    raw = _archive(client, project)

    def tamper(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        result = next(row for row in sections["jobs"] if row["id"] == job)["result_json"]
        snapshot = result["snapshot"]
        if case == "missing-png":
            entries = _manifest["generated_artifacts"]
            index = next(
                index for index, entry in enumerate(entries) if entry["path"].endswith(".png")
            )
            entries.pop(index)
            return
        if case == "foreign-alias":
            result["source_id_map"][snapshot["models"][0]["model_id"]] = str(uuid4())
            return
        scored = next(
            obs
            for group in snapshot["evidence"]["groups"]
            for obs in group["observations"]
            if obs["metrics"]
        )
        metric = next(row for row in scored["metrics"] if row["left"] is not None)
        metric["left"] += 21
        snapshot["summary"] = summarize_groups(snapshot["evidence"]["groups"])
        result["content_sha256"] = canonical_json_sha256(snapshot)

    before = deepcopy(client.get("/api/v1/projects").json())
    dirs = set((test_settings.resolved_data_dir / "projects").iterdir())
    rejected = import_archive(client, rewrite(raw, tamper))  # type: ignore[no-untyped-call]
    assert rejected.status_code == 400, rejected.text
    assert "paired" in rejected.text.casefold()
    assert client.get("/api/v1/projects").json() == before
    assert set((test_settings.resolved_data_dir / "projects").iterdir()) == dirs


def test_historical_result_survives_without_weights_but_live_replay_is_refused(
    client: TestClient,
    test_settings: Settings,
    reviewed_runtime: None,
) -> None:
    project, job, original = _compare(client, "mask")
    app = cast(FastAPI, client.app)
    copied = import_archive(client, _archive(client, project, weights=False))  # type: ignore[no-untyped-call]
    assert copied.status_code == 201, copied.text
    result = copied.json()
    target = result["project_id"]
    mapped = result["package"]["options_json"]["origin_id_map"][job]
    export = client.get(f"/api/v1/projects/{target}/paired-model-comparisons/{mapped}/export")
    assert export.status_code == 200, export.text
    assert export.json()["snapshot"] == original["snapshot"]
    assert export.json()["content_sha256"] == original["content_sha256"]
    with app.state.session_factory() as session, pytest.raises(ConflictError, match="checkpoint"):
        replay(session, test_settings, target, mapped, original["content_sha256"])


def test_paired_video_comparison_scores_restore_and_replay_twice(
    client: TestClient,
    test_settings: Settings,
    reviewed_runtime: None,
    video_comparison: VideoFixture,
) -> None:
    app, project, scoring_jobs, models, _ = video_comparison
    path = f"/api/v1/projects/{project}/paired-model-comparisons"
    with app.state.session_factory() as session:
        selected = [
            _confirm_runtime(client, project, session.get(ModelRegistration, identifier))
            for identifier in models
        ]
    pins = [
        {"id": item["runtime_selection_id"], "sha256": item["runtime_selection_sha256"]}
        for item in selected
    ]
    reports = []
    for task in ("pose", "tracking", "event"):
        options = client.get(path + "/sources", params={"task": task})
        hashes = {item["id"]: item["sha256"] for item in options.json()}
        queued = client.post(
            path,
            json={
                "task": task,
                "left": pins[0],
                "right": pins[1],
                "sources": [
                    {"id": identifier, "sha256": hashes[identifier]} for identifier in scoring_jobs
                ],
            },
        )
        assert queued.status_code == 202, queued.text
        identifier = queued.json()["id"]
        assert process_comparison(test_settings, app.state.session_factory, identifier)
        result = client.get(f"{path}/{identifier}").json()
        assert result["status"] == "succeeded", result
        reports.append((identifier, result["result_json"]))
    raw = _archive(client, project)
    for _ in range(2):
        imported = import_archive(client, raw)  # type: ignore[no-untyped-call]
        assert imported.status_code == 201, imported.text
        target = imported.json()["project_id"]
        ids = imported.json()["package"]["options_json"]["origin_id_map"]
        with app.state.session_factory() as session:
            for identifier, original in reports:
                restored = replay(
                    session, test_settings, target, ids[identifier], original["content_sha256"]
                )
                assert restored == {
                    "snapshot": original["snapshot"],
                    "content_sha256": original["content_sha256"],
                }
        raw = _archive(client, target)


def _record_pre_id_comparison(
    session: Session, job_id: str, test_settings: Settings, missing: str | None = None
) -> tuple[dict[str, Any], str]:
    job = session.get(Job, job_id)
    assert job is not None and job.result_json is not None
    snapshot = deepcopy(job.result_json["snapshot"])
    evidence = snapshot["evidence"]
    children = evidence.pop("inference_job_ids")
    for index, child_id in enumerate(children):
        child = session.get(Job, child_id)
        model = session.get(ModelRegistration, child.request_json["model_id"])
        proposals = session.scalars(
            select(PredictionProposal).where(PredictionProposal.inference_job_id == child_id)
        ).all()
        pre_id_choice = {
            key: child.request_json[key]
            for key in (
                "model_id",
                "runtime_selection_id",
                "runtime_selection_sha256",
                "device",
                "confidence_threshold",
                "iou_threshold",
            )
        } | {"checkpoint_sha256": model.sha256}
        evidence["source_sha256"][4 + index] = canonical_json_sha256(
            {
                "choice": pre_id_choice,
                "predictions": sorted(
                    canonical_json_sha256(_prediction_fields(row)) for row in proposals
                ),
                "invalid_images": [],
            }
        )
        if missing == "raster" and index == 1:
            mask = next(row for row in proposals if row.mask_path)
            (test_settings.resolved_data_dir / mask.mask_path).unlink()
        if missing == "ambiguous" and index == 0:
            duplicate_id = str(uuid4())
            session.add(
                Job(
                    id=duplicate_id,
                    **{
                        col.name: getattr(child, col.name)
                        for col in Job.__table__.columns
                        if col.name not in {"id", "deduplication_key"}
                    },
                )
            )
            session.flush()
            for proposal in proposals:
                session.add(
                    PredictionProposal(
                        inference_job_id=duplicate_id,
                        **{
                            col.name: getattr(proposal, col.name)
                            for col in PredictionProposal.__table__.columns
                            if col.name not in {"id", "inference_job_id"}
                        },
                    )
                )
        if missing == "job" and index == 0:
            for proposal in proposals:
                session.delete(proposal)
            session.delete(child)
    digest = canonical_json_sha256(snapshot)
    job.result_json = {"snapshot": snapshot, "content_sha256": digest, "source_id_map": {}}
    session.commit()
    return snapshot, digest


@pytest.mark.parametrize(
    ("task", "missing"),
    [
        ("detector", None),
        ("detector", "job"),
        ("detector", "ambiguous"),
        ("mask", None),
        ("mask", "raster"),
    ],
)
def test_pre_inference_id_report_preserves_history_and_requires_proof(
    client: TestClient,
    test_settings: Settings,
    reviewed_runtime: None,
    task: str,
    missing: str | None,
) -> None:
    project, job_id, _ = _compare(client, task)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        snapshot, digest = _record_pre_id_comparison(session, job_id, test_settings, missing)
        if missing is None:
            assert (
                replay(session, test_settings, project, job_id, digest)["content_sha256"] == digest
            )
    raw = _archive(client, project)
    for _ in range(2):
        imported = import_archive(client, raw)  # type: ignore[no-untyped-call]
        assert imported.status_code == 201, imported.text
        target = imported.json()["project_id"]
        mapped = imported.json()["package"]["options_json"]["origin_id_map"][job_id]
        report = client.get(
            f"/api/v1/projects/{target}/paired-model-comparisons/{mapped}/export"
        ).json()
        assert report["snapshot"] == snapshot
        assert report["content_sha256"] == digest
        assert report["verification_status"] == "unverified_legacy"
        current = f"/api/v1/projects/{target}/paired-model-comparisons/{mapped}"
        assert client.get(current).json()["result_json"] == report
        sheet = client.get(current + "/export?format=csv").text
        assert "verification_status,verification_message" in sheet.splitlines()[0]
        assert "unverified_legacy" in sheet and report["verification_message"] in sheet
        with app.state.session_factory() as session:
            if missing is None:
                assert (
                    replay(session, test_settings, target, mapped, digest)["snapshot"] == snapshot
                )
            else:
                with pytest.raises(
                    ConflictError,
                    match=r"original evaluation jobs|cannot be verified|worker outputs",
                ):
                    replay(session, test_settings, target, mapped, digest)
        raw = _archive(client, target)


@pytest.mark.parametrize("stage", ["queue", "worker"])
def test_verified_research_package_refuses_unverified_legacy_comparison(
    client: TestClient, reviewed_runtime: None, stage: str
) -> None:
    project, selection, _ = _reproducibility_fixture(client)
    job_id = selection["comparison_id"]
    root = f"/api/v1/projects/{project}"
    endpoint = f"{root}/reproducibility-packages"
    pending = None
    if stage == "worker":
        response = client.post(endpoint, json=selection)
        assert response.status_code == 202, response.text
        pending = response.json()
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        row = session.get(Job, job_id)
        result = deepcopy(row.result_json)
        result["snapshot"]["evidence"].pop("inference_job_ids")
        result["content_sha256"] = canonical_json_sha256(result["snapshot"])
        row.result_json = result
        session.commit()

    historical = client.get(f"{root}/paired-model-comparisons/{job_id}/export")
    assert historical.status_code == 200, historical.text
    assert historical.json()["verification_status"] == "unverified_legacy"
    if pending is None:
        rejected = client.post(endpoint, json=selection)
        assert rejected.status_code == 409, rejected.text
        assert "create a new comparison" in rejected.json()["detail"].lower()
        assert client.get(endpoint).json() == []
    else:
        assert not process_project_exchange_export_job(
            app.state.settings, app.state.session_factory, pending["job_id"]
        )
        identifier = pending["package"]["id"]
        package = client.get(f"{REPRO}/{identifier}").json()
        assert package["status"] == "failed", package
        assert "create a new comparison" in package["error_message"].lower()
        assert client.get(f"{REPRO}/{identifier}/download").status_code == 409


def test_legacy_bundle_requires_original_outputs_even_with_rehashed_zip(
    client: TestClient, test_settings: Settings, reviewed_runtime: None
) -> None:
    project, selection, _ = _reproducibility_fixture(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        _, digest = _record_pre_id_comparison(session, selection["comparison_id"], test_settings)
    package, raw = _export(client, project, selection, with_media=True, with_weights=False)
    assert package["manifest"]["proof"]["evidence"]["comparison"]["content_sha256"] == digest
    verified = client.post(f"{REPRO}/inspect", files=_upload(raw)).json()
    assert verified["compatible"], verified
    reopened = client.post(f"{REPRO}/import", files=_upload(raw))
    assert reopened.status_code == 201, reopened.text
    assert reopened.json()["proof_sha256"] == package["proof_sha256"]

    def remove_original_outputs(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        jobs = sections["jobs"]
        omitted = next(
            row["id"]
            for row in jobs
            if row["job_type"] == "inference" and row["request_json"].get("evaluation_only")
        )
        sections["jobs"] = [row for row in jobs if row["id"] != omitted]
        sections["prediction_proposals"] = [
            row for row in sections["prediction_proposals"] if row["inference_job_id"] != omitted
        ]

    parts = _zip_body(raw)
    manifest = json.loads(parts["manifest.json"])
    path = "project.reefvision.zip"
    nested = rewrite(parts[path], remove_original_outputs)  # type: ignore[no-untyped-call]
    assert import_archive(client, nested).status_code == 201  # type: ignore[no-untyped-call]
    with ZipFile(BytesIO(nested)) as archive:
        manifest["exchange_manifest_sha256"] = canonical_json_sha256(
            json.loads(archive.read("reefvision-exchange-manifest.json"))
        )
    incomplete = _archive_with_replacement(parts, manifest, path, nested)
    before = client.get("/api/v1/projects").json()
    incompatible = client.post(f"{REPRO}/inspect", files=_upload(incomplete)).json()
    assert not incompatible["compatible"], incompatible
    assert "create a new comparison" in incompatible["errors"][0].lower()
    denied = client.post(f"{REPRO}/import", files=_upload(incomplete))
    assert denied.status_code == 400, denied.text
    assert client.get("/api/v1/projects").json() == before
