from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration
from reefvision.db.models.reefpose_validation import ReefPoseHeldoutLock
from reefvision.domain.reefpose_agreement import ScoredEvent, event_agreement
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_pose_identity_tracking_api import _video
from reefvision.tests.test_reefpose_validation import freeze_fixture
from reefvision.tests.test_scientific_project_exchange import (
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def _seed_report(
    client: TestClient,
    project_id: str,
    reference_id: str,
    reference_sha256: str,
    manifest: dict[str, Any],
    *,
    count: int,
    measurement_unit: str = "mm",
    changed_protocol: bool = False,
) -> str:
    recordings = manifest["recordings"]
    events = [ScoredEvent(str(index), 0.1, 0.2) for index in range(count)]
    counts = event_agreement([], events, 0.2, 0.2)
    partial = event_agreement([], [], 0.2, 0.2)
    configuration = {
        "definitions": [{"id": "distance", "kind": "distance"}],
        "onset_tolerance_s": 0.3 if changed_protocol else 0.2,
    }
    with client.app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project_id,
            purpose="pose",
            display_name=f"Fixture model {count}",
            source_filename="fixture.pt",
            managed_path=f"projects/{project_id}/models/{uuid4()}.pt",
            sha256=str(count) * 64,
            file_size_bytes=0,
            framework="pytorch",
            task="pose",
            provider_name="reefpose",
            provider_version="test",
            class_map_json={},
            input_size_json={},
            metadata_json={},
        )
        session.add(model)
        session.flush()
        report = {
            "schema_version": "reefpose-scientific-validation-1",
            "split": "test",
            "data_kind": "synthetic",
            "reference_id": reference_id,
            "reference_sha256": reference_sha256,
            "rater_id": "rater-a",
            "selected_configuration": configuration,
            "scored_reference_manifest": manifest,
            "configurations": [configuration],
            "bootstrap_seed": 20261114,
            "development_lock_sha256": "c" * 64,
            "selected_configuration_index": 0,
            "sensitivity": [{"configuration_index": 0, "complete": counts, "partial": partial}],
            "tracker_protocol": [["fixture", "1"]],
            "models": {model.id: {"id": model.id, "checkpoint_sha256": model.sha256}},
            "prediction_sources": [
                {
                    "video_id": row["video_id"],
                    "model_id": model.id,
                    "observations_sha256": canonical_json_sha256([]),
                }
                for row in recordings
            ],
            "recordings": [
                {
                    "video_id": row["video_id"],
                    "group_id": row["group_id"],
                    "events": [
                        {
                            "individual_id": row["individuals"][0]["id"],
                            "label": "gape",
                            "start_s": 0,
                            "end_s": 0.25,
                            "reference_events": [],
                            "predicted_events": [{"state": "complete"}] * count,
                            "complete": counts,
                            "partial": partial,
                        },
                        {
                            "individual_id": row["individuals"][0]["id"],
                            "label": "gape",
                            "start_s": 0.25,
                            "excluded": "ambiguous_reference",
                        },
                    ],
                    "measurements": [
                        {
                            "individual_id": "animal-a",
                            "definition_id": "distance",
                            "unit": measurement_unit,
                            "matched_frames": [0, 1],
                            "points": [
                                {"mean": 1.0, "difference": 2.0},
                                {"mean": 3.5, "difference": -1.0},
                            ],
                        }
                    ],
                }
                for row in recordings
            ],
        }
        manifest_fields = (
            "schema_version",
            "reference_id",
            "reference_sha256",
            "scored_reference_manifest",
            "data_kind",
            "split",
            "rater_id",
            "models",
            "prediction_sources",
            "tracker_protocol",
            "development_lock_sha256",
            "configurations",
            "bootstrap_seed",
        )
        report["input_sha256"] = canonical_json_sha256(
            {key: report[key] for key in manifest_fields}
        )
        report["result_sha256"] = canonical_json_sha256(report)
        job = Job(
            project_id=project_id,
            job_type="reefpose_validation",
            status="succeeded",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            result_json=report,
        )
        session.add(job)
        for recording in recordings:
            scope = canonical_json_sha256(
                {
                    "project": project_id,
                    "video": recording["video_sha256"],
                    "checkpoint": model.sha256,
                }
            )
            protocol = canonical_json_sha256(
                {
                    "development_lock": report["development_lock_sha256"],
                    "tracker_protocol": report["tracker_protocol"],
                    "reference": reference_sha256,
                    "rater": "rater-a",
                    "bootstrap_seed": report["bootstrap_seed"],
                    "observations_sha256": canonical_json_sha256([]),
                }
            )
            session.add(
                ReefPoseHeldoutLock(
                    scope_sha256=scope, project_id=project_id, protocol_sha256=protocol
                )
            )
        session.commit()
        return str(job.id)


def seed_comparison_fixture(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    second_protocol_changed: bool = False,
) -> tuple[str, str, str]:
    url, payload, _ = freeze_fixture(client, monkeypatch)
    project_id = url.split("/")[-2]
    recording = payload["recordings"][0]
    heldout = _video(client, project_id, monkeypatch, "comparison-heldout")
    recording.update(
        video_id=heldout["id"],
        video_sha256=heldout["sha256"],
        group_id="session-heldout",
        split="test",
    )
    recording["event_windows"] = [
        {"individual_id": "animal-a", "label": "gape", "start_s": start, "end_s": start + 0.25}
        for start in (0, 0.25)
    ]
    for rater in recording["annotations"]:
        rater["events"] = []
        rater["measurements"] = [
            {
                "individual_id": "animal-a",
                "definition_id": "distance",
                "frame": frame,
                "unit": "=mm",
                "value": value,
                "state": state,
            }
            for frame, value, state in (
                (0, 0, "scored"),
                (1, 4, "scored"),
                (2, 5, "scored"),
                (3, None, "ambiguous"),
            )
        ]
    frozen = client.post(url, json=payload)
    assert frozen.status_code == 201, frozen.text
    reference = frozen.json()
    first, second = (
        _seed_report(
            client,
            project_id,
            reference["id"],
            reference["manifest_sha256"],
            reference["manifest"],
            count=count,
            measurement_unit="=mm",
            changed_protocol=second_protocol_changed and count == 2,
        )
        for count in (1, 2)
    )
    return project_id, first, second


def test_held_out_comparison_counts_share_exact_reference_and_preserve_zero_and_exclusions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    project_id, first, second = seed_comparison_fixture(client, monkeypatch)
    url = f"/api/v1/projects/{project_id}/scientific-comparisons"
    response = client.post(
        url, json={"source_job_ids": [first, second], "metric": "event_count", "name": "gape"}
    )
    assert response.status_code == 201, response.text
    report = response.json()
    frozen_result = report["snapshot"]
    assert frozen_result["data_kind"] == "synthetic"
    assert [model["statistics"]["bias"] for model in frozen_result["models"]] == [1, 2]
    assert [model["statistics"]["zero_reference_count"] for model in frozen_result["models"]] == [
        1,
        1,
    ]
    assert [
        model["statistics"]["mean_absolute_percentage_error"] for model in frozen_result["models"]
    ] == [None, None]
    assert frozen_result["pairing"]["absolute_error_change"] == 1
    assert len(frozen_result["exclusions"]) == 2
    assert all(v["reason"] == "ambiguous_reference" for v in frozen_result["exclusions"])
    reopened = client.get(f"{url}/{report['id']}")
    assert reopened.json() == report
    csv = client.get(f"{url}/{report['id']}/export?format=csv")
    assert "signed_difference" in csv.text

    graph = {
        "graph_id": "heldout-comparison-test",
        "name": "Publish held-out comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "comparison",
                "node_type": "scientific_comparison",
                "parameters": {"comparison_id": report["id"]},
            },
        ],
        "edges": [
            {
                "edge_id": "project-comparison",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "comparison",
                "target_port_id": "project",
            }
        ],
    }
    run = _run(client, project_id, graph)
    assert run["run"]["status"] == "succeeded", run
    artifact = next(
        row for row in run["artifacts"] if row["data_type"] == "scientific_comparison_report"
    )
    assert artifact["payload_json"]["content_sha256"] == report["content_sha256"]
    calculated = _run(
        client,
        project_id,
        {
            **graph,
            "graph_id": "calculate-heldout-comparison",
            "nodes": [
                graph["nodes"][0],
                {
                    **graph["nodes"][1],
                    "parameters": {"configuration": report["snapshot"]["options"]},
                },
            ],
        },
    )
    assert calculated["run"]["status"] == "succeeded", calculated
    calculated_artifact = next(
        row for row in calculated["artifacts"] if row["data_type"] == "scientific_comparison_report"
    )
    assert calculated_artifact["payload_json"]["content_sha256"] == report["content_sha256"]
    raw = export_archive(client, test_settings, project_id)
    inspected = client.post("/api/v1/exchange-packages/inspect", files={"file": ("study.zip", raw)})
    assert inspected.json()["compatible"], inspected.text

    def tamper(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        row = next(job for job in sections["jobs"] if job["job_type"] == "scientific_comparison")
        result = row["result_json"]
        result["snapshot"]["models"][0]["statistics"]["bias"] = 18.0
        result["content_sha256"] = canonical_json_sha256(result["snapshot"])

    rejected = client.post(
        "/api/v1/exchange-packages/inspect", files={"file": ("forged.zip", rewrite(raw, tamper))}
    ).json()
    assert not rejected["compatible"]
    assert any("statistics do not replay" in error for error in rejected["errors"]), rejected
    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    result = imported.json()
    ids = result["package"]["options_json"]["id_map"]
    new_project = result["project_id"]
    new_id = ids[report["id"]]
    exchanged = client.get(f"/api/v1/projects/{new_project}/scientific-comparisons/{new_id}").json()
    assert exchanged["content_sha256"] == report["content_sha256"]
    assert exchanged["snapshot"] == report["snapshot"]
    assert not exchanged["stale"]
    assert exchanged["local_sources"][0]["job_id"] == ids[first]
    graph["nodes"][1]["parameters"]["comparison_id"] = new_id
    rerun = _run(client, new_project, graph)
    assert rerun["run"]["status"] == "succeeded", rerun


def test_continuous_comparison_keeps_missing_frames_and_escapes_spreadsheet_formula_labels(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, first, second = seed_comparison_fixture(
        client, monkeypatch, second_protocol_changed=True
    )
    url = f"/api/v1/projects/{project}/scientific-comparisons"
    payload = {
        "source_job_ids": [first],
        "metric": "measurement",
        "name": "distance",
        "unit": "=mm",
    }
    response = client.post(url, json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    snapshot = result["snapshot"]
    assert snapshot["pairing"] is None
    assert [(item["reference"], item["estimate"]) for item in snapshot["models"][0]["pairs"]] == [
        (0, 2),
        (4, 3),
    ]
    statistics = snapshot["models"][0]["statistics"]
    assert statistics["bias"] == 0.5
    assert statistics["mean_absolute_error"] == 1.5
    assert statistics["mean_absolute_percentage_error"] == 25
    assert [item["reason"] for item in snapshot["exclusions"]] == [
        "no_matched_prediction",
        "ambiguous_reference",
    ]
    response = client.get(f"{url}/{result['id']}/export?format=csv")
    rows = list(csv.DictReader(StringIO(response.text)))
    assert [row["unit"] for row in rows] == ["'=mm"] * 4
    assert [row["signed_difference"] for row in rows[:2]] == ["2.0", "-1.0"]
    incompatible = client.post(url, json={**payload, "source_job_ids": [first, second]})
    assert incompatible.status_code == 400, incompatible.text
    assert "same frozen reference, rater, and scoring protocol" in incompatible.json()["detail"]


def test_agreement_analytic_fixture_icc_and_cluster_assumptions() -> None:
    from reefvision.schemas.scientific_comparison import ComparisonRequest, PairedValue
    from reefvision.services.scientific_comparison import agreement_statistics

    def rows(independent: bool):
        return [
            PairedValue(
                video_id=uuid4(),
                group_id=f"group-{int(independent) * i}",
                individual_id="subject",
                frame=i,
                reference=ref,
                estimate=ref + 3,
            )
            for i, ref in enumerate([1, 3, 5, 7, 9])
        ]

    request = ComparisonRequest(
        source_job_ids=[uuid4()],
        metric="measurement",
        name="length",
        unit="mm",
        icc="A,1",
        independent_groups=True,
        homoscedastic_normal_differences=True,
    )
    independent = agreement_statistics(rows(True), request)
    assert independent.bias == 3
    assert independent.limits_of_agreement == (3, 3)
    assert independent.icc == pytest.approx(20 / 29)
    assert independent.bias_ci95 == (3, 3)
    assert agreement_statistics(rows(True), request.model_copy(update={"icc": "C,1"})).icc == 1
    repeated = agreement_statistics(rows(False), request)
    assert repeated.independent_groups == 1
    assert repeated.icc is None
    assert repeated.limits_of_agreement is None
    assert repeated.bias_ci95 is None
