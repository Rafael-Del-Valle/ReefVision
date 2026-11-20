"""Portable frozen study designs retain original identity and remain executable."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.services import ecology_identity, study_design
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_paired_growth_contrast import (
    _revise_planned_identity,
    _run_graph,
    _study,
)
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_study_design_v15 import (
    _declaration,
    _freeze,
    _path,
    _save_workflow,
    _source,
)


def _manifest(raw: bytes) -> dict[str, Any]:
    with ZipFile(BytesIO(raw)) as archive:
        return json.loads(archive.read(MANIFEST))


def _report(run: dict[str, Any]) -> dict[str, Any]:
    [artifact] = [row for row in run["artifacts"] if row["data_type"] == "study_design_report"]
    return artifact


def test_two_project_copies_keep_exact_study_report_and_remap_live_replay(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project, _, analysis, _ = _study(client, reviewed_assignments=True)
    declaration = _declaration()
    declaration["review_note"] = analysis["id"]
    declaration["treatments"][0]["label"] = project
    original = _freeze(client, project, {"declaration": declaration, **_source(analysis)})
    original_export = client.get(f"{_path(project)}/{original['id']}/design.json")
    assert original_export.status_code == 200, original_export.text
    graph = _save_workflow(client, project, original["id"], original["content_sha256"])
    run = _run_graph(client, project, graph)
    assert run["run"]["status"] == "succeeded", run
    artifact = _report(run)
    source_record = artifact["payload_json"]
    assert source_record == {
        "content_sha256": original["content_sha256"],
        "snapshot": original["snapshot"],
    }

    raw = export_archive(client, test_settings, project)  # type: ignore[no-untyped-call]
    for _ in range(2):
        manifest = _manifest(raw)
        assert manifest["format_version"] == "1.5"
        assert manifest["sections"]["study_design_revisions"]["count"] == 1
        imported = import_archive(client, raw)  # type: ignore[no-untyped-call]
        assert imported.status_code == 201, imported.text
        response = imported.json()
        target = response["project_id"]
        mapping = response["package"]["options_json"]["origin_id_map"]
        live_revision = mapping[original["id"]]
        saved = client.get(f"{_path(target)}/{live_revision}").json()
        assert saved["id"] != original["id"]
        assert saved["design_id"] == mapping[original["design_id"]]
        assert saved["growth_analysis_id"] == mapping[analysis["id"]]
        assert saved["snapshot"] == original["snapshot"]
        assert saved["content_sha256"] == original["content_sha256"]
        reopened_export = client.get(f"{_path(target)}/{live_revision}/design.json")
        assert reopened_export.content == original_export.content
        assert reopened_export.headers["X-ReefVision-Content-SHA256"] == original["content_sha256"]
        assert saved["source_id_map"] == {
            key: mapping[key]
            for key in (
                project,
                original["id"],
                original["design_id"],
                analysis["id"],
                *(member["identity_id"] for member in original["snapshot"]["roster"]),
            )
        }
        archived = client.get(f"/api/v1/workflow-runs/{mapping[run['run']['id']]}").json()
        assert _report(archived)["payload_json"] == source_record
        assert _report(archived)["payload_sha256"] == artifact["payload_sha256"]
        exact_node = next(node for node in archived["nodes"] if node["node_id"] == "study")
        assert exact_node["parameters_json"]["design_revision_id"] == live_revision
        assert (
            exact_node["result_json"]["outputs"][0]["payload_sha256"] == artifact["payload_sha256"]
        )
        provenance = archived["run"]["result_json"]
        assert (
            canonical_json_sha256(provenance["provenance_manifest"])
            == provenance["provenance_sha256"]
        )
        replay = _run_graph(client, target, mapping[graph])
        assert replay["run"]["status"] == "succeeded", replay
        assert _report(replay)["payload_json"] == source_record
        raw = export_archive(client, test_settings, target)  # type: ignore[no-untyped-call]

    # Author a project-local revision without changing the portable receipt.
    updated = _freeze(
        client,
        target,
        {
            "declaration": {**declaration, "title": "Copied study revision"},
            "growth_analysis_id": mapping[analysis["id"]],
            "growth_source_sha256": analysis["content_sha256"],
            "supersedes_revision_id": live_revision,
            "supersedes_sha256": original["content_sha256"],
        },
    )
    assert updated["design_id"] == saved["design_id"]
    assert updated["revision"] == 2
    assert updated["snapshot"]["project_id"] == target
    assert updated["snapshot"]["supersedes_revision_id"] == live_revision
    assert client.get(f"{_path(target)}/{live_revision}/design.json").json() == original["snapshot"]
    _revise_planned_identity(client, target)
    stale = _run_graph(client, target, mapping[graph])
    assert stale["run"]["status"] == "failed"
    assert "identity revision changed" in stale["run"]["error_message"]
    stale_archive = export_archive(client, test_settings, target)  # type: ignore[no-untyped-call]
    preserved = import_archive(client, stale_archive)  # type: ignore[no-untyped-call]
    assert preserved.status_code == 201, preserved.text
    preserved_mapping = preserved.json()["package"]["options_json"]["origin_id_map"]
    restored = client.get(f"/api/v1/workflow-runs/{preserved_mapping[run['run']['id']]}").json()
    assert _report(restored)["payload_json"] == source_record


def test_imported_prospective_plan_can_bind_later_reviewed_growth(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EnrollmentClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            timestamp = cls(2026, 10, 29, tzinfo=UTC)
            return timestamp.astimezone(tz) if tz is not None else timestamp.replace(tzinfo=None)

    original: dict[str, Any] = {}
    declaration = _declaration("prospective")

    def declare(project: str) -> None:
        with monkeypatch.context() as phase:
            phase.setattr(study_design, "utc_now", lambda: datetime(2026, 10, 31, tzinfo=UTC))
            original.update(_freeze(client, project, {"declaration": declaration}))

    with monkeypatch.context() as clock:
        clock.setattr(ecology_identity, "utc_now", lambda: EnrollmentClock.now(UTC))
        clock.setattr(ecology_identity, "datetime", EnrollmentClock)
        project, _, analysis, _ = _study(
            client, reviewed_assignments=True, before_observations=declare
        )
    raw = export_archive(client, test_settings, project)  # type: ignore[no-untyped-call]
    imported = import_archive(client, raw)  # type: ignore[no-untyped-call]
    assert imported.status_code == 201, imported.text
    response = imported.json()
    target = response["project_id"]
    mapping = response["package"]["options_json"]["origin_id_map"]
    live = mapping[original["id"]]
    result = client.post(
        f"{_path(target)}/{live}/bind",
        json={
            "design_sha256": original["content_sha256"],
            "growth_analysis_id": mapping[analysis["id"]],
            "growth_source_sha256": analysis["content_sha256"],
        },
    )
    assert result.status_code == 201, result.text
    bound = result.json()
    assert bound["revision"] == 2
    assert bound["snapshot"]["declared_at"] == original["snapshot"]["declared_at"]
    assert bound["snapshot"]["binding"]["paired_report"]["mean_difference"] == pytest.approx(5)
    assert client.get(f"{_path(target)}/{live}/design.json").json() == original["snapshot"]
    archive = export_archive(client, test_settings, target)  # type: ignore[no-untyped-call]
    reopened = import_archive(client, archive)  # type: ignore[no-untyped-call]
    assert reopened.status_code == 201, reopened.text


@pytest.mark.parametrize(
    "mutation",
    [
        "forged-paired-mean",
        "wrong-roster-identity",
        "foreign-source",
        "forged-artifact",
        "stripped-study-section",
    ],
)
def test_study_archive_semantic_rewrite_fails_before_mutation(
    client: TestClient,
    test_settings: Settings,
    mutation: str,
) -> None:
    project, _, analysis, _ = _study(client, reviewed_assignments=True)
    study = _freeze(client, project, {"declaration": _declaration(), **_source(analysis)})
    foreign_project = None
    if mutation == "foreign-source":
        created = client.post("/api/v1/projects", json={"name": "Other growth project"})
        assert created.status_code == 201, created.text
        foreign_project = created.json()["id"]
    if mutation in {"forged-artifact", "stripped-study-section"}:
        graph = _save_workflow(client, project, study["id"], study["content_sha256"])
        assert _run_graph(client, project, graph)["run"]["status"] == "succeeded"
    raw = export_archive(client, test_settings, project)  # type: ignore[no-untyped-call]

    def forge(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        if mutation == "stripped-study-section":
            _manifest["format_version"] = "1.2"
            del _manifest["sections"]["study_design_revisions"]
            del sections["study_design_revisions"]
            return
        if mutation == "forged-artifact":
            [result] = [
                row
                for row in sections["workflow_artifacts"]
                if row["data_type"] == "study_design_report"
            ]
            result["payload_json"]["snapshot"]["declaration"]["review_note"] = "Changed artifact"
            result["payload_sha256"] = canonical_json_sha256(result["payload_json"])
            producer = next(
                node
                for node in sections["workflow_node_runs"]
                if node["id"] == result["producer_node_run_id"]
            )
            producer["result_json"]["outputs"][0]["payload_sha256"] = result["payload_sha256"]
            return
        [record] = sections["study_design_revisions"]
        snapshot = record["snapshot_json"]
        if mutation == "wrong-roster-identity":
            snapshot["roster"][0]["identity_id"] = snapshot["roster"][1]["identity_id"]
        elif mutation == "foreign-source":
            replacement = str(uuid4())
            [source] = sections["ecology_analysis_records"]
            sections["ecology_analysis_records"].append(
                {**source, "id": replacement, "project_id": foreign_project}
            )
            snapshot["binding"]["analysis_id"] = replacement
            snapshot["binding"]["paired_report"]["analysis_id"] = replacement
            record["growth_analysis_id"] = replacement
        else:
            snapshot["binding"]["paired_report"]["mean_difference"] = 99
        report = snapshot["binding"]["paired_report"]
        report["report_sha256"] = canonical_json_sha256(
            {key: value for key, value in report.items() if key != "report_sha256"}
        )
        record["content_sha256"] = canonical_json_sha256(snapshot)

    before = client.get("/api/v1/projects").json()
    directories = set((test_settings.resolved_data_dir / "projects").iterdir())
    changed = rewrite(raw, forge)  # type: ignore[no-untyped-call]
    inspection = client.post(
        "/api/v1/exchange-packages/inspect", files={"file": ("forge.zip", changed)}
    )
    assert not inspection.json()["compatible"], inspection.text
    assert "Study design exchange" in inspection.text
    rejected = import_archive(client, changed)  # type: ignore[no-untyped-call]
    assert rejected.status_code == 400, rejected.text
    assert client.get("/api/v1/projects").json() == before
    assert set((test_settings.resolved_data_dir / "projects").iterdir()) == directories
