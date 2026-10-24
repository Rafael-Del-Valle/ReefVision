"""Exercise a scientist-verified frozen pose dataset through saved workflow execution."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import PoseTrainingDataset
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_pose_training import (
    create_pose_workflow_training_result,
    execute_pose_training_dataset_adapter,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_pose_training_phase10 import _frozen_dataset


def test_verified_pose_dataset_persists_workflow_lineage(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    graph = {
        "graph_id": "track-e-verified-pose-source",
        "name": "Verified pose dataset lineage",
        "nodes": [
            {
                "node_id": "frozen-pose",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": dataset["manifest_sha256"],
                },
            }
        ],
        "edges": [],
    }

    other_project = create_project(client, "Pose dataset project isolation")
    forbidden = client.post(
        f"/api/v1/projects/{other_project['id']}/workflow-graphs/plan", json=graph
    )
    assert forbidden.status_code == 200, forbidden.text
    assert forbidden.json()["valid"] is False
    issue_codes = {issue["code"] for issue in forbidden.json()["issues"]}
    assert "pose_dataset_scope_mismatch" in issue_codes

    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True

    stale_graph = {
        **graph,
        "nodes": [
            {
                **graph["nodes"][0],
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": "0" * 64,
                },
            }
        ],
    }
    stale_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=stale_graph
    )
    assert stale_plan.status_code == 200, stale_plan.text
    assert stale_plan.json()["valid"] is False
    assert stale_plan.json()["executable"] is False
    stale_codes = {issue["code"] for issue in stale_plan.json()["issues"]}
    assert "pose_dataset_manifest_mismatch" in stale_codes

    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    graph_record = saved.json()
    assert graph_record["revision"] == 1
    assert len(graph_record["graph_sha256"]) == 64

    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": graph_record["id"]},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["graph_sha256"] == graph_record["graph_sha256"]

    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is True
    )

    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    run = detail.json()
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["graph_sha256"] == graph_record["graph_sha256"]
    assert run["run"]["workflow_graph_record_id"] == graph_record["id"]
    assert len(run["nodes"]) == 1
    assert run["nodes"][0]["status"] == "succeeded"

    outputs = [
        artifact
        for artifact in run["artifacts"]
        if artifact["data_type"] == "pose_training_dataset"
    ]
    assert len(outputs) == 1
    assert len(outputs[0]["payload_sha256"]) == 64
    assert outputs[0]["payload_sha256"] == canonical_json_sha256(outputs[0]["payload_json"])
    assert outputs[0]["workflow_run_id"] == run["run"]["id"]
    assert outputs[0]["producer_node_run_id"] == run["nodes"][0]["id"]
    assert outputs[0]["id"] in run["nodes"][0]["output_artifact_ids_json"]
    payload = outputs[0]["payload_json"]
    assert payload["project_id"] == project_id
    assert payload["dataset_id"] == dataset_id
    assert payload["manifest_sha256"] == dataset["manifest_sha256"]
    assert payload["pose_schema_id"] == dataset["pose_schema_id"]
    assert payload["pose_schema_revision"] == dataset["pose_schema_revision"]
    assert payload["pose_schema_content_hash"] == dataset["pose_schema_content_hash"]

    # A recomputed checksum must not legitimize a frozen manifest that no
    # longer guarantees scientist-verified-only training truth.
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        original_manifest = dict(frozen.manifest_json)
        original_manifest_sha = frozen.manifest_sha256
        tampered_manifest = {**original_manifest, "truth_policy": "unverified_allowed"}
        tampered_manifest_sha = canonical_json_sha256(tampered_manifest)
        frozen.manifest_json = tampered_manifest
        frozen.manifest_sha256 = tampered_manifest_sha
        session.commit()

    resigned_graph = {
        **graph,
        "nodes": [
            {
                **graph["nodes"][0],
                "parameters": {
                    **graph["nodes"][0]["parameters"],
                    "manifest_sha256": tampered_manifest_sha,
                },
            }
        ],
    }
    resigned_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=resigned_graph
    )
    assert resigned_plan.status_code == 200, resigned_plan.text
    assert resigned_plan.json()["valid"] is False
    assert "pose_dataset_truth_policy_mismatch" in {
        issue["code"] for issue in resigned_plan.json()["issues"]
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="only scientist-verified items"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, resigned_graph["nodes"][0]["parameters"], {}
        )
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="only scientist-verified items"),
    ):
        create_pose_workflow_training_result(
            session,
            app.state.settings,
            project_id=project_id,
            dataset_payload={**payload, "manifest_sha256": tampered_manifest_sha},
            parameters={},
        )
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        frozen.manifest_json = original_manifest
        frozen.manifest_sha256 = original_manifest_sha
        session.commit()

    # A newly checksummed manifest cannot substitute an item fingerprint:
    # saved Workflow Builder planning and runtime must agree with frozen rows.
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        modified_items = [dict(item) for item in original_manifest["items"]]
        modified_items[0]["item_sha256"] = "0" * 64
        item_manifest = {**original_manifest, "items": modified_items}
        item_manifest_sha = canonical_json_sha256(item_manifest)
        frozen.manifest_json = item_manifest
        frozen.manifest_sha256 = item_manifest_sha
        session.commit()

    item_graph = {
        **graph,
        "nodes": [
            {
                **graph["nodes"][0],
                "parameters": {
                    **graph["nodes"][0]["parameters"],
                    "manifest_sha256": item_manifest_sha,
                },
            }
        ],
    }
    item_plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=item_graph)
    assert item_plan.status_code == 200, item_plan.text
    assert item_plan.json()["valid"] is False
    assert "pose_dataset_item_lineage_mismatch" in {
        issue["code"] for issue in item_plan.json()["issues"]
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, item_graph["nodes"][0]["parameters"], {}
        )
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        create_pose_workflow_training_result(
            session,
            app.state.settings,
            project_id=project_id,
            dataset_payload={**payload, "manifest_sha256": item_manifest_sha},
            parameters={},
        )
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        frozen.manifest_json = original_manifest
        frozen.manifest_sha256 = original_manifest_sha
        session.commit()

    # A signed manifest must also bind human-review and source identities
    # to the persisted frozen item, not just its item and pose fingerprints.
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        identity_items = [dict(item) for item in original_manifest["items"]]
        identity_items[0]["candidate_id"] = "different-verified-candidate"
        identity_manifest = {**original_manifest, "items": identity_items}
        identity_sha = canonical_json_sha256(identity_manifest)
        frozen.manifest_json = identity_manifest
        frozen.manifest_sha256 = identity_sha
        session.commit()

    identity_graph = {
        **graph,
        "nodes": [
            {
                **graph["nodes"][0],
                "parameters": {
                    **graph["nodes"][0]["parameters"],
                    "manifest_sha256": identity_sha,
                },
            }
        ],
    }
    identity_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=identity_graph
    )
    assert identity_plan.status_code == 200, identity_plan.text
    assert identity_plan.json()["valid"] is False
    assert "pose_dataset_item_lineage_mismatch" in {
        issue["code"] for issue in identity_plan.json()["issues"]
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, identity_graph["nodes"][0]["parameters"], {}
        )
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        create_pose_workflow_training_result(
            session,
            app.state.settings,
            project_id=project_id,
            dataset_payload={**payload, "manifest_sha256": identity_sha},
            parameters={},
        )
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        frozen.manifest_json = original_manifest
        frozen.manifest_sha256 = original_manifest_sha
        session.commit()

    # Re-signing a modified provenance field must not make saved training
    # truth appear reproducible when its frozen source lineage has changed.
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        lineage_manifest = {**original_manifest, "source_selection_sha256": "0" * 64}
        lineage_sha = canonical_json_sha256(lineage_manifest)
        frozen.manifest_json = lineage_manifest
        frozen.manifest_sha256 = lineage_sha
        session.commit()

    lineage_graph = {
        **graph,
        "nodes": [
            {
                **graph["nodes"][0],
                "parameters": {**graph["nodes"][0]["parameters"], "manifest_sha256": lineage_sha},
            }
        ],
    }
    lineage_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=lineage_graph
    )
    assert lineage_plan.status_code == 200, lineage_plan.text
    assert lineage_plan.json()["valid"] is False
    assert "pose_dataset_lineage_mismatch" in {
        issue["code"] for issue in lineage_plan.json()["issues"]
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="manifest lineage no longer matches"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, lineage_graph["nodes"][0]["parameters"], {}
        )
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="manifest lineage no longer matches"),
    ):
        create_pose_workflow_training_result(
            session,
            app.state.settings,
            project_id=project_id,
            dataset_payload={**payload, "manifest_sha256": lineage_sha},
            parameters={},
        )
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        frozen.manifest_json = original_manifest
        frozen.manifest_sha256 = original_manifest_sha
        session.commit()

    # The saved workflow's real output artifact must not be reusable for
    # training after any of its frozen landmark identity fields are changed.
    with app.state.session_factory() as session:
        for field, stale_value in (
            ("pose_schema_id", "not-the-frozen-schema"),
            ("pose_schema_revision", -1),
            ("pose_schema_content_hash", "0" * 64),
        ):
            with pytest.raises(ValidationError, match="artifact landmark schema metadata"):
                create_pose_workflow_training_result(
                    session,
                    app.state.settings,
                    project_id=project_id,
                    dataset_payload={**payload, field: stale_value},
                    parameters={},
                )

    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        assert frozen.status == "complete"
        assert frozen.manifest_sha256 == payload["manifest_sha256"]
        assert frozen.pose_schema_content_hash == payload["pose_schema_content_hash"]
        frozen.pose_schema_content_hash = "0" * 64
        session.commit()

    stale_schema_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph
    )
    assert stale_schema_plan.status_code == 200, stale_schema_plan.text
    assert stale_schema_plan.json()["valid"] is False
    assert stale_schema_plan.json()["executable"] is False
    stale_schema_codes = {issue["code"] for issue in stale_schema_plan.json()["issues"]}
    # A changed persisted hash first violates the frozen manifest's lineage.
    assert "pose_dataset_lineage_mismatch" in stale_schema_codes
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="manifest lineage no longer matches"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
        )

    # Even if the manifest is re-signed to agree with the tampered dataset,
    # the independent landmark revision must still reject schema drift.
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        resigned_schema_manifest = {
            **frozen.manifest_json,
            "pose_schema": {
                **frozen.manifest_json["pose_schema"],
                "content_hash": frozen.pose_schema_content_hash,
            },
        }
        frozen.manifest_json = resigned_schema_manifest
        frozen.manifest_sha256 = canonical_json_sha256(resigned_schema_manifest)
        resigned_schema_sha = frozen.manifest_sha256
        session.commit()

    resigned_schema_graph = {
        **graph,
        "nodes": [
            {
                **graph["nodes"][0],
                "parameters": {
                    **graph["nodes"][0]["parameters"],
                    "manifest_sha256": resigned_schema_sha,
                },
            }
        ],
    }
    schema_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=resigned_schema_graph
    )
    assert schema_plan.status_code == 200, schema_plan.text
    assert schema_plan.json()["valid"] is False
    assert "pose_dataset_schema_mismatch" in {
        issue["code"] for issue in schema_plan.json()["issues"]
    }

    # Execution independently rejects the same drift after successful planning.
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="landmark schema no longer matches"),
    ):
        execute_pose_training_dataset_adapter(
            session,
            app.state.settings,
            project_id,
            resigned_schema_graph["nodes"][0]["parameters"],
            {},
        )

    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        frozen.manifest_json = original_manifest
        frozen.manifest_sha256 = original_manifest_sha
        frozen.pose_schema_content_hash = payload["pose_schema_content_hash"]
        session.commit()

    # The database enforces item_count >= 1, so an empty frozen dataset
    # cannot be persisted. Test the executable incomplete-status path instead.
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        frozen.pose_schema_content_hash = payload["pose_schema_content_hash"]
        frozen.status = "incomplete"
        session.commit()

    empty_plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert empty_plan.status_code == 200, empty_plan.text
    assert empty_plan.json()["valid"] is False
    assert "pose_dataset_incomplete" in {issue["code"] for issue in empty_plan.json()["issues"]}

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="complete and contain verified items"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
        )

    # A valid manifest checksum alone must not hide a changed database item
    # count: the saved workflow and downstream training must reject drift.
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        frozen.status = "complete"
        frozen.item_count += 1
        session.commit()

    count_plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert count_plan.status_code == 200, count_plan.text
    assert count_plan.json()["valid"] is False
    assert "pose_dataset_item_count_mismatch" in {
        issue["code"] for issue in count_plan.json()["issues"]
    }

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item count no longer matches frozen manifest"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
        )

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item count no longer matches frozen manifest"),
    ):
        create_pose_workflow_training_result(
            session,
            app.state.settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={},
        )


@pytest.mark.parametrize(
    ("tamper_mode", "expected_error"),
    [
        ("changed_content", "manifest checksum"),
        ("non_object", "manifest must be a JSON object"),
    ],
)
def test_frozen_pose_manifest_tampering_fails_saved_workflow_execution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tamper_mode: str,
    expected_error: str,
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    graph = {
        "graph_id": "track-e-frozen-pose-integrity",
        "name": "Frozen pose manifest integrity at execution",
        "nodes": [
            {
                "node_id": "frozen-pose",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": dataset["manifest_sha256"],
                },
            }
        ],
        "edges": [],
    }
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        assert frozen is not None
        if tamper_mode == "non_object":
            frozen.manifest_json = ["not-a-frozen-pose-manifest"]
        else:
            changed_manifest = dict(frozen.manifest_json)
            changed_manifest["truth_policy"] = "tampered_after_queue"
            frozen.manifest_json = changed_manifest
        session.commit()

    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is False
    assert plan.json()["executable"] is False
    issue_codes = {issue["code"] for issue in plan.json()["issues"]}
    assert "pose_dataset_manifest_corrupt" in issue_codes

    # The independent runtime adapter must reject malformed frozen truth too.
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match=expected_error),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
        )

    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    result = detail.json()
    assert result["run"]["status"] == "failed"
    assert "pose_dataset_manifest_corrupt" in result["run"]["error_message"]
    assert expected_error in result["run"]["error_message"]
    assert result["artifacts"] == []
