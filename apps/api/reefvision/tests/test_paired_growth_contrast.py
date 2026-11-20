from importlib.util import find_spec
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services import paired_growth_contrast
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_reviewed_growth_sampling_1_3 import _growth_sources
from reefvision.tests.test_scientific_project_exchange import (
    export_archive,
    import_archive,
    rewrite,
)


def _study(client: TestClient) -> tuple[str, str, dict[str, Any], dict[str, str]]:
    project = create_project(client, "Paired calibrated study")
    project_id = str(project["id"])
    ecology = f"/api/v1/projects/{project_id}/ecology"
    roster = {
        "Tank-1": ["a-left", "a-right", "b"],
        "Tank-2": ["c"],
        "Tank-3": ["d"],
        "Tank-4": ["e", "f"],
    }

    def register(organism: str, tank: str, kind: str, parent: str | None = None) -> None:
        response = client.post(
            f"{ecology}/organisms",
            json={
                "organism_key": organism,
                "experimental_unit_type": "tank",
                "experimental_unit_id": tank,
                "kind": kind,
                "parent_colony_key": parent,
                "reason": "Reviewed fixture sampling roster",
            },
        )
        assert response.status_code == 201, response.text

    register("a", "Tank-1", "colony")
    for tank, organisms in roster.items():
        for organism in organisms:
            parent = "a" if organism.startswith("a-") else f"parent-{organism}"
            if parent != "a":
                register(parent, tank, "colony")
            register(organism, tank, "fragment", parent)

    widths = {
        "a-left": [(1, 10), (2, 14)],
        "a-right": [(1, 12), (2, 24)],
        "b": [(1, 16), (2, 32)],
        "c": [(1, 21), (2, 41)],
        "d": [(1, 23), (2, 51)],
        "e": [(1, 25), (2, 53)],
    }
    sources = [
        row
        for organism, visits in widths.items()
        for row in _growth_sources(client, project, organism, visits)
    ]
    sources[-1]["exclusion_reason"] = "Glare obscured follow-up boundary"
    path = f"{ecology}/verified-analyses"
    response = client.post(
        path,
        json={
            "selection": {
                "kind": "growth",
                "metric": "box_width",
                "sources": sources,
                "sampling_plan": [
                    {
                        "experimental_unit_id": tank,
                        "organism_keys": organisms,
                        "dates": ["2026-11-01", "2026-11-02", "2026-11-03"],
                    }
                    for tank, organisms in roster.items()
                ],
            },
            "reviewed_by": "Fixture reviewer",
            "review_note": "Reviewed the roster, observations and omissions.",
            "confirm_reviewed_selection": True,
        },
    )
    assert response.status_code == 201, response.text
    analysis = response.json()
    return (
        project_id,
        f"{path}/{analysis['id']}/paired-contrast",
        analysis,
        {
            "source_sha256": analysis["content_sha256"],
            "baseline_date": "2026-11-01",
            "followup_date": "2026-11-02",
            "experimental_unit_type": "tank",
            "estimand": "Mean change in the declared independent tanks with both visits complete.",
            "missingness_policy": "complete_unit",
        },
    )


def test_paired_growth_known_answer_and_two_saved_replays(client: TestClient) -> None:
    project_id, url, analysis, design = _study(client)
    response = client.post(url, json=design)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["analysis_id"] == analysis["id"]
    assert report["source_sha256"] == analysis["content_sha256"]
    assert report["planned_unit_count"] == 4
    assert report["included_unit_count"] == 3
    assert report["metric"] == "box_width"
    assert report["unit"] == "mm"
    assert report["mean_difference"] == pytest.approx(5.0)
    assert report["standard_error"] == pytest.approx(2 / 3**0.5)
    assert report["degrees_of_freedom"] == 2
    if find_spec("scipy"):
        assert report["confidence_interval_95"] == pytest.approx([0.031724576, 9.968275424])
    else:
        assert report["confidence_interval_95"] is None
        assert report["interval_status"] == "statistics_runtime_unavailable"
    assert [unit["difference"] for unit in report["units"][:3]] == pytest.approx([3, 5, 7])
    assert [pair["difference"] for pair in report["units"][0]["organisms"]] == [1, 3, 4]
    unavailable = report["units"][3]
    assert unavailable["status"] == "excluded"
    assert unavailable["reason"] == "incomplete_unit"
    assert unavailable["difference"] is None
    assert unavailable["organisms"][0]["baseline_source_record_id"]
    assert unavailable["organisms"][0]["followup_source_record_id"] is None
    assert unavailable["organisms"][1]["reason"] == "missing_both_visits"
    assert any(
        row["reason"] == "Glare obscured follow-up boundary" for row in report["source_exclusions"]
    )
    assert report["report_sha256"] == canonical_json_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )

    workflow = {
        "graph_id": "paired-growth-known-pairs",
        "name": "Paired calibrated tank contrast",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "paired",
                "node_type": "paired_growth_contrast",
                "parameters": {"analysis_id": analysis["id"], **design},
            },
        ],
        "edges": [
            {
                "edge_id": "project-paired",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "paired",
                "target_port_id": "project",
            }
        ],
    }
    graphs = f"/api/v1/projects/{project_id}/workflow-graphs"
    saved = client.post(graphs, json={"graph": workflow, "create_new_revision": True})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    for _ in range(2):
        queued = client.post(
            f"/api/v1/projects/{project_id}/workflow-runs",
            json={"graph_record_id": saved.json()["id"]},
        )
        assert queued.status_code == 202, queued.text
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
        assert detail["run"]["status"] == "succeeded", detail
        assert (
            next(
                row["payload_json"]
                for row in detail["artifacts"]
                if row["data_type"] == "paired_growth_contrast"
            )
            == report
        )

    _revise_planned_identity(client, project_id)
    stale = _run_graph(client, project_id, saved.json()["id"])
    assert stale["run"]["status"] == "failed", stale
    assert "Selected growth evidence has changed" in stale["run"]["error_message"]
    assert not any(row["data_type"] == "paired_growth_contrast" for row in stale["artifacts"])
    assert (
        _paired_output(client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json())[
            "payload_json"
        ]
        == report
    )


def test_paired_growth_rejects_invalid_design_and_excludes_absent_visits(
    client: TestClient,
) -> None:
    project_id, url, analysis, design = _study(client)
    invalid_designs: list[tuple[dict[str, object], int]] = [
        ({"source_sha256": "0" * 64}, 409),
        ({"baseline_date": "2026-11-02"}, 422),
        ({"followup_date": "2026-11-04"}, 400),
        ({"baseline_date": 1793491200}, 422),
        ({"experimental_unit_type": "colony"}, 400),
        ({"experimental_unit_type": "videoFrame"}, 422),
        ({"missingness_policy": "zero"}, 422),
        ({"organism_ids": ["a-left"]}, 422),
    ]
    for change, status in invalid_designs:
        result = client.post(url, json={**design, **change})
        assert result.status_code == status, result.text
    foreign = create_project(client, "Unrelated")
    assert client.post(url.replace(project_id, foreign["id"]), json=design).status_code == 404

    no_followup = client.post(url, json={**design, "followup_date": "2026-11-03"})
    assert no_followup.status_code == 200, no_followup.text
    empty = no_followup.json()
    assert empty["included_unit_count"] == 0
    for statistic in (
        "mean_difference",
        "standard_error",
        "degrees_of_freedom",
        "confidence_interval_95",
    ):
        assert empty[statistic] is None
    assert all(unit["status"] == "excluded" for unit in empty["units"])

    _revise_planned_identity(client, project_id)
    stale = client.post(url, json=design)
    assert stale.status_code == 409, stale.text
    reopened = client.get(url.removesuffix("/paired-contrast")).json()
    assert reopened["stale"]
    assert reopened["snapshot"] == analysis["snapshot"]


def _revise_planned_identity(client: TestClient, project_id: str) -> None:
    changed = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/f/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "parent_colony_key": "parent-f",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "Tank-4",
            "reason": "Recorded a changed planned roster membership",
        },
    )
    assert changed.status_code == 201, changed.text


def test_exchange_preserves_original_paired_receipt_and_rebinds_live_replays(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project_id, url, analysis, design = _study(client)
    # A UUID-looking research declaration must remain literal when the linked analysis ID moves.
    design["estimand"] = analysis["id"]
    original = client.post(url, json=design).json()
    graph = {
        "graph_id": "paired-growth-exchange",
        "name": "Paired contrast with immutable history",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "paired",
                "node_type": "paired_growth_contrast",
                "parameters": {"analysis_id": analysis["id"].upper(), **design},
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
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    graph_id = saved.json()["id"]
    run = _run_graph(client, project_id, graph_id)
    assert run["run"]["status"] == "succeeded", run
    original_run_id = run["run"]["id"]
    historical = _paired_output(run)
    assert historical["payload_json"] == original

    raw = export_archive(client, test_settings, project_id)  # type: ignore[no-untyped-call]
    for _ in range(2):
        imported = import_archive(client, raw)  # type: ignore[no-untyped-call]
        assert imported.status_code == 201, imported.text
        bundle = imported.json()
        copy_project = bundle["project_id"]
        provenance = bundle["package"]["options_json"]
        lineage = provenance["origin_id_map"]
        assert lineage[project_id] == copy_project
        archived_run = client.get(f"/api/v1/workflow-runs/{lineage[original_run_id]}").json()
        artifact = _paired_output(archived_run)
        assert artifact["payload_json"] == historical["payload_json"]
        assert artifact["payload_sha256"] == historical["payload_sha256"]
        paired_node = next(row for row in archived_run["nodes"] if row["node_id"] == "paired")
        assert (
            paired_node["result_json"]["outputs"][0]["payload_sha256"] == artifact["payload_sha256"]
        )
        assert (
            canonical_json_sha256(archived_run["run"]["result_json"]["provenance_manifest"])
            == archived_run["run"]["result_json"]["provenance_sha256"]
        )

        replay = _run_graph(client, copy_project, lineage[graph_id])
        assert replay["run"]["status"] == "succeeded", replay
        current = _paired_output(replay)["payload_json"]
        assert current["project_id"] == copy_project
        assert current["analysis_id"] == lineage[analysis["id"]]
        for key in (
            "source_sha256",
            "design",
            "units",
            "mean_difference",
            "confidence_interval_95",
        ):
            assert current[key] == original[key]
        assert current["report_sha256"] != original["report_sha256"]
        raw = export_archive(client, test_settings, copy_project)  # type: ignore[no-untyped-call]

    def forge(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        artifact = next(
            row for row in sections["workflow_artifacts"] if row["id"] == lineage[historical["id"]]
        )
        payload = artifact["payload_json"]
        payload["mean_difference"] = 42
        payload["report_sha256"] = canonical_json_sha256(
            {key: value for key, value in payload.items() if key != "report_sha256"}
        )
        artifact["payload_sha256"] = canonical_json_sha256(payload)
        producer = next(
            row
            for row in sections["workflow_node_runs"]
            if row["id"] == artifact["producer_node_run_id"]
        )
        producer["result_json"]["outputs"][0]["payload_sha256"] = artifact["payload_sha256"]

    def relabel(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        artifact = next(
            row for row in sections["workflow_artifacts"] if row["id"] == lineage[historical["id"]]
        )
        artifact["data_type"] = "verified_ecology_analysis"
        producer = next(
            row
            for row in sections["workflow_node_runs"]
            if row["id"] == artifact["producer_node_run_id"]
        )
        producer["result_json"]["outputs"][0]["data_type"] = artifact["data_type"]

    projects_before = client.get("/api/v1/projects").json()
    dirs_before = set((test_settings.resolved_data_dir / "projects").iterdir())
    for mutation in (forge, relabel):
        tampered = rewrite(raw, mutation)  # type: ignore[no-untyped-call]
        rejected = import_archive(client, tampered)  # type: ignore[no-untyped-call]
        assert rejected.status_code == 400, rejected.text
        assert "Paired growth workflow receipt" in rejected.json()["detail"], rejected.text
        assert client.get("/api/v1/projects").json() == projects_before
        assert set((test_settings.resolved_data_dir / "projects").iterdir()) == dirs_before


def _paired_output(run: dict[str, Any]) -> dict[str, Any]:
    [artifact] = [row for row in run["artifacts"] if row["data_type"] == "paired_growth_contrast"]
    return cast(dict[str, Any], artifact)


def _run_graph(client: TestClient, project_id: str, graph_id: str) -> dict[str, Any]:
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs", json={"graph_record_id": graph_id}
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    reopened = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert reopened.status_code == 200, reopened.text
    return cast(dict[str, Any], reopened.json())


def test_paired_statistics_withholds_unsupported_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_scipy(name: str) -> None:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(paired_growth_contrast, "import_module", missing_scipy)
    statistics = paired_growth_contrast._paired_statistics
    unavailable = statistics([1, 3, 5], calculate_t_interval=True)
    assert unavailable.mean_difference == 3
    assert unavailable.standard_error == pytest.approx(2 / 3**0.5)
    assert unavailable.degrees_of_freedom == 2
    assert unavailable.confidence_interval_95 is None
    assert unavailable.interval_status == "statistics_runtime_unavailable"
    identical = statistics([3, 3], calculate_t_interval=True)
    assert identical.standard_error == 0
    assert identical.confidence_interval_95 is None
    assert identical.interval_status == "zero_between_unit_variation"
    one = statistics([3], calculate_t_interval=True)
    assert one.mean_difference == 3
    assert one.standard_error is None
    assert one.degrees_of_freedom is None
    assert one.confidence_interval_95 is None
    assert one.interval_status == "insufficient_complete_units"


def _cross_unit_colony_study(
    client: TestClient,
) -> tuple[str, str, str, dict[str, Any]]:
    project = create_project(client, "Paired colony and descendant")
    project_id = project["id"]
    ecology = f"/api/v1/projects/{project_id}/ecology"
    plan = []
    sources = []
    for key, tank, kind, parent, visits in (
        ("colony-a", "Tank-A", "colony", None, [(1, 20), (2, 24), (3, 25), (3, 26)]),
        ("fragment-a", "Tank-B", "fragment", "colony-a", [(1, 21), (2, 37)]),
    ):
        registered = client.post(
            f"{ecology}/organisms",
            json={
                "organism_key": key,
                "experimental_unit_id": tank,
                "experimental_unit_type": "tank",
                "kind": kind,
                "parent_colony_key": parent,
                "reason": "Reviewed synthetic lineage",
            },
        )
        assert registered.status_code == 201, registered.text
        sources.extend(_growth_sources(client, project, key, visits))
        plan.append(
            {
                "experimental_unit_id": tank,
                "organism_keys": [key],
                "dates": ["2026-11-01", "2026-11-02", "2026-11-03"],
            }
        )
    response = client.post(
        f"{ecology}/verified-analyses",
        json={
            "selection": {
                "kind": "growth",
                "metric": "box_width",
                "sources": sources,
                "sampling_plan": plan,
            },
            "reviewed_by": "Fixture reviewer",
            "review_note": "Reviewed frozen roster including a duplicate at the third visit.",
            "confirm_reviewed_selection": True,
        },
    )
    assert response.status_code == 201, response.text
    analysis = response.json()
    assert any(
        row["source"] == "colony-a" and row["reason"] == "duplicate_utc_sampling_date"
        for row in analysis["snapshot"]["result"]["exclusions"]
    )
    return (
        project_id,
        ecology,
        analysis["id"],
        {
            "source_sha256": analysis["content_sha256"],
            "baseline_date": "2026-11-01",
            "followup_date": "2026-11-02",
            "experimental_unit_type": "tank",
            "estimand": "Declared tank contrast across the two selected visits.",
            "missingness_policy": "complete_unit",
        },
    )


def _save_cross_unit_colony_graph(
    client: TestClient, project_id: str, analysis_id: str, design: dict[str, Any]
) -> str:
    graph = {
        "graph_id": "cross-unit-colony-contrast",
        "name": "Cross-unit colony contrast",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "paired",
                "node_type": "paired_growth_contrast",
                "parameters": {"analysis_id": analysis_id, **design},
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
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    return str(saved.json()["id"])


def test_enrolled_colony_and_fragment_do_not_count_as_independent_units(
    client: TestClient,
) -> None:
    project_id, ecology, analysis_id, design = _cross_unit_colony_study(client)
    url = f"{ecology}/verified-analyses/{analysis_id}"
    original = client.get(url).json()
    response = client.post(f"{url}/paired-contrast", json=design)
    assert response.status_code == 400, response.text
    assert "colony" in response.json()["detail"].lower()
    graph_id = _save_cross_unit_colony_graph(client, project_id, analysis_id, design)
    rejected = _run_graph(client, project_id, graph_id)
    assert rejected["run"]["status"] == "failed", rejected
    assert "colony" in rejected["run"]["error_message"].lower()
    assert not any(row["data_type"] == "paired_growth_contrast" for row in rejected["artifacts"])
    assert client.get(url).json() == original
