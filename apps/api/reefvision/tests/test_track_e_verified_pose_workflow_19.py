"""Exercise a scientist-verified frozen pose dataset through saved workflow execution."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import PoseTrainingDataset, PoseTrainingDatasetItem
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.pose_training_datasets import (
    PACKAGE_CHECKSUMS_FILENAME,
    PACKAGE_ITEMS_FILENAME,
    PACKAGE_MANIFEST_FILENAME,
    PoseTrainingDatasetService,
)
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

    # The unmodified scientist-verified dataset remains retrievable and exportable.
    with app.state.session_factory() as session:
        service = PoseTrainingDatasetService(session)
        retrieved = service.manifest(dataset_id)
        assert retrieved.manifest_sha256 == dataset["manifest_sha256"]
        assert len(service.items(dataset_id)) == dataset["item_count"]
        _, package_bytes, package_sha256 = service.native_package(dataset_id)
        _, repeated_package_bytes, repeated_package_sha256 = service.native_package(dataset_id)
    assert package_bytes == repeated_package_bytes
    assert package_sha256 == repeated_package_sha256
    assert len(package_sha256) == 64

    # Audit the actual frozen dataset exported from the saved workflow. ZIP
    # host metadata must be stable across Windows and Linux, not merely within
    # repeated exports on one operating system.
    with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
        assert all(member.create_system == 3 for member in archive.infolist())
        # The saved-workflow export must carry a portable integrity index
        # for the exact bytes researchers receive after extracting the ZIP.
        expected_checksums = "".join(
            f"{hashlib.sha256(archive.read(name)).hexdigest()}  {name}\n"
            for name in (PACKAGE_MANIFEST_FILENAME, PACKAGE_ITEMS_FILENAME, "README.txt")
        ).encode("ascii")
        assert archive.read(PACKAGE_CHECKSUMS_FILENAME) == expected_checksums
        exported_manifest = json.loads(archive.read(PACKAGE_MANIFEST_FILENAME))
        exported_items = [
            json.loads(line)
            for line in archive.read(PACKAGE_ITEMS_FILENAME).decode("utf-8").splitlines()
        ]
    assert canonical_json_sha256(exported_manifest) == dataset["manifest_sha256"]
    assert len(exported_items) == dataset["item_count"]
    assert {item["item_id"] for item in exported_items} == {
        summary["item_id"] for summary in exported_manifest["items"]
    }

    # A valid checksum cannot authorize an unsupported frozen dataset or
    # manifest schema version. Verify the existing saved workflow, native
    # export, and downstream training all reject either kind of schema drift.
    for schema_target in ("dataset", "manifest"):
        with app.state.session_factory() as session:
            frozen = session.get(PoseTrainingDataset, dataset_id)
            assert frozen is not None
            original_schema_version = frozen.schema_version
            original_manifest = dict(frozen.manifest_json)
            original_manifest_sha = frozen.manifest_sha256
            if schema_target == "dataset":
                frozen.schema_version = "pose-training-dataset-9999"
            else:
                changed_manifest = {
                    **original_manifest,
                    "schema_version": "pose-training-dataset-manifest-9999",
                }
                frozen.manifest_json = changed_manifest
                frozen.manifest_sha256 = canonical_json_sha256(changed_manifest)
            session.commit()

        with (
            app.state.session_factory() as session,
            pytest.raises(ConflictError, match="item lineage no longer matches"),
        ):
            PoseTrainingDatasetService(session).native_package(dataset_id)

        schema_plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
        assert schema_plan.status_code == 200, schema_plan.text
        assert schema_plan.json()["valid"] is False
        assert "pose_dataset_item_lineage_mismatch" in {
            issue["code"] for issue in schema_plan.json()["issues"]
        }
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="item fingerprints no longer match"),
        ):
            create_pose_workflow_training_result(
                session,
                app.state.settings,
                project_id=project_id,
                dataset_payload=payload,
                parameters={},
            )

        with app.state.session_factory() as session:
            frozen = session.get(PoseTrainingDataset, dataset_id)
            assert frozen is not None
            frozen.schema_version = original_schema_version
            frozen.manifest_json = original_manifest
            frozen.manifest_sha256 = original_manifest_sha
            session.commit()

    # Mutating the persisted canonical landmarks does not change the signed
    # manifest or the item's stored SHA-256. The frozen scientist-approved
    # pose digest must independently protect export, planning and training.
    with app.state.session_factory() as session:
        item = session.scalar(
            select(PoseTrainingDatasetItem).where(PoseTrainingDatasetItem.dataset_id == dataset_id)
        )
        assert item is not None
        original_pose = dict(item.canonical_pose_json)
        item.canonical_pose_json = {
            **original_pose,
            "keypoints": [*list(original_pose.get("keypoints") or []), {"tampered": True}],
        }
        session.commit()

    # Even with a valid manifest checksum, neither manifest nor item-list
    # retrieval may expose altered scientist-verified frozen landmarks.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="item lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).items(dataset_id)
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="item lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).manifest(dataset_id)
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="item lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).native_package(dataset_id)

    changed_pose_plan = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph
    )
    assert changed_pose_plan.status_code == 200, changed_pose_plan.text
    assert changed_pose_plan.json()["valid"] is False
    assert "pose_dataset_item_lineage_mismatch" in {
        issue["code"] for issue in changed_pose_plan.json()["issues"]
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
        )
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        create_pose_workflow_training_result(
            session,
            app.state.settings,
            project_id=project_id,
            dataset_payload=payload,
            parameters={},
        )
    with app.state.session_factory() as session:
        item = session.scalar(
            select(PoseTrainingDatasetItem).where(PoseTrainingDatasetItem.dataset_id == dataset_id)
        )
        assert item is not None
        item.canonical_pose_json = original_pose
        session.commit()

    # The verified-landmark digest intentionally omits the frame's confidence
    # and crop bbox. The new frozen-manifest digest must also protect these
    # persisted frame fields against post-freeze changes.
    with app.state.session_factory() as session:
        service = PoseTrainingDatasetService(session)
        frozen_manifest = service.manifest(dataset_id).manifest_json
        assert "canonical_pose_sha256" in frozen_manifest["items"][0]
        item = session.scalar(
            select(PoseTrainingDatasetItem).where(PoseTrainingDatasetItem.dataset_id == dataset_id)
        )
        assert item is not None
        original_pose = dict(item.canonical_pose_json)
        changed_confidence = 0.123456 if original_pose.get("confidence") != 0.123456 else 0.654321
        item.canonical_pose_json = {
            **original_pose,
            "confidence": changed_confidence,
        }
        session.commit()

    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="item lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).manifest(dataset_id)

    confidence_plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert confidence_plan.status_code == 200, confidence_plan.text
    assert confidence_plan.json()["valid"] is False
    assert "pose_dataset_item_lineage_mismatch" in {
        issue["code"] for issue in confidence_plan.json()["issues"]
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
        )

    with app.state.session_factory() as session:
        item = session.scalar(
            select(PoseTrainingDatasetItem).where(PoseTrainingDatasetItem.dataset_id == dataset_id)
        )
        assert item is not None
        item.canonical_pose_json = original_pose
        session.commit()

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

    # Manifest retrieval must not expose re-signed unverified training truth.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="only scientist-verified items"),
    ):
        PoseTrainingDatasetService(session).manifest(dataset_id)

    # Re-freezing the same round must not silently return corrupted persisted
    # training truth just because an immutable dataset already exists.
    repeated_freeze = client.post(
        f"/api/v1/pose-active-learning-rounds/{dataset['source_round_id']}/training-dataset",
        json={"created_by": "scientist"},
    )
    assert repeated_freeze.status_code == 409, repeated_freeze.text

    # Native exports must enforce the same verified-only policy as saved workflows,
    # even when a modified manifest has been assigned a matching new checksum.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="only scientist-verified items"),
    ):
        PoseTrainingDatasetService(session).native_package(dataset_id)

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

    # Re-signing the manifest must not bypass native package export validation.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="item lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).native_package(dataset_id)

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
    # A re-signed item summary must preserve both candidate identity and
    # the candidate acquisition provenance digest captured at freeze time.
    for identity_field, stale_value in (
        ("candidate_id", "different-verified-candidate"),
        ("candidate_provenance_sha256", "0" * 64),
    ):
        with app.state.session_factory() as session:
            frozen = session.get(PoseTrainingDataset, dataset_id)
            assert frozen is not None
            identity_items = [dict(item) for item in original_manifest["items"]]
            identity_items[0][identity_field] = stale_value
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
                session,
                app.state.settings,
                project_id,
                identity_graph["nodes"][0]["parameters"],
                {},
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

    # Retrieval and export must agree on source lineage, even with a new checksum.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="manifest lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).manifest(dataset_id)

    # Re-signing source selection lineage must not make a native package exportable.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="manifest lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).native_package(dataset_id)

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

    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="manifest lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).manifest(dataset_id)

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

    # Manifest retrieval must fail closed, not expose corrupt frozen truth.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="manifest"),
    ):
        PoseTrainingDatasetService(session).manifest(dataset_id)

    # Export must reject the same corrupted frozen manifest as workflow execution.
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="manifest"),
    ):
        PoseTrainingDatasetService(session).native_package(dataset_id)

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


def test_frozen_pose_review_evidence_corruption_fails_closed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reuse the scientist-verified persisted dataset rather than a synthetic
    # manifest. Corrupt only its frozen review/acquisition JSON columns.
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    app = cast(FastAPI, client.app)
    graph = {
        "graph_id": "track-e-review-evidence-integrity",
        "name": "Frozen review evidence integrity",
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

    with app.state.session_factory() as session:
        service = PoseTrainingDatasetService(session)
        assert service.manifest(dataset_id).manifest_sha256 == dataset["manifest_sha256"]
        assert service.get_dataset(dataset_id).id == dataset_id
        assert any(row.id == dataset_id for row in service.list_datasets(project_id))
        item = session.scalar(
            select(PoseTrainingDatasetItem).where(PoseTrainingDatasetItem.dataset_id == dataset_id)
        )
        assert item is not None
        original_review = dict(item.review_provenance_json)
        original_acquisition = dict(item.acquisition_provenance_json)
        original_models = list(item.source_models_json or [])
        original_jobs = list(item.source_job_ids_json or [])
        assert "frozen_evidence_sha256" in service.manifest(dataset_id).manifest_json["items"][0]

    cases = (
        ("review_provenance_json", ["not-a-review-record"]),
        (
            "review_provenance_json",
            {**original_review, "action": "skip_active_learning_pose"},
        ),
        (
            "review_provenance_json",
            {**original_review, "target_id": "unrelated-candidate"},
        ),
        # These remain structurally valid but must not silently change
        # frozen scientist attribution or source model/job lineage.
        (
            "review_provenance_json",
            {**original_review, "actor": "tampered-reviewer"},
        ),
        ("source_models_json", [{"model_id": "tampered-source-model"}]),
        ("source_job_ids_json", ["tampered-source-job"]),
        ("acquisition_provenance_json", ["not-an-acquisition-record"]),
    )
    for field, invalid_value in cases:
        with app.state.session_factory() as session:
            item = session.scalar(
                select(PoseTrainingDatasetItem).where(
                    PoseTrainingDatasetItem.dataset_id == dataset_id
                )
            )
            assert item is not None
            setattr(item, field, invalid_value)
            session.commit()

        # Project listings must not advertise corrupted science as complete.
        with (
            app.state.session_factory() as session,
            pytest.raises(ConflictError, match="item lineage no longer matches"),
        ):
            PoseTrainingDatasetService(session).list_datasets(project_id)
        # Direct dataset lookups enforce the same frozen-truth contract.
        with (
            app.state.session_factory() as session,
            pytest.raises(ConflictError, match="item lineage no longer matches"),
        ):
            PoseTrainingDatasetService(session).get_dataset(dataset_id)
        with (
            app.state.session_factory() as session,
            pytest.raises(ConflictError, match="item lineage no longer matches"),
        ):
            PoseTrainingDatasetService(session).manifest(dataset_id)
        with (
            app.state.session_factory() as session,
            pytest.raises(ConflictError, match="item lineage no longer matches"),
        ):
            PoseTrainingDatasetService(session).native_package(dataset_id)

        plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
        assert plan.status_code == 200, plan.text
        assert plan.json()["valid"] is False
        assert "pose_dataset_item_lineage_mismatch" in {
            issue["code"] for issue in plan.json()["issues"]
        }
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="item fingerprints no longer match"),
        ):
            execute_pose_training_dataset_adapter(
                session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
            )

        with app.state.session_factory() as session:
            item = session.scalar(
                select(PoseTrainingDatasetItem).where(
                    PoseTrainingDatasetItem.dataset_id == dataset_id
                )
            )
            assert item is not None
            item.review_provenance_json = original_review
            item.acquisition_provenance_json = original_acquisition
            item.source_models_json = original_models
            item.source_job_ids_json = original_jobs
            session.commit()

    with app.state.session_factory() as session:
        assert (
            PoseTrainingDatasetService(session).manifest(dataset_id).manifest_sha256
            == dataset["manifest_sha256"]
        )


def test_resigned_empty_pose_is_not_scientist_verified(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise a real API-frozen, scientist-verified item, not a fabricated
    # training manifest. Re-signing both digests must not validate zero landmarks.
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        item = session.scalar(
            select(PoseTrainingDatasetItem).where(PoseTrainingDatasetItem.dataset_id == dataset_id)
        )
        assert frozen is not None and item is not None
        assert item.canonical_pose_json.get("pose_observations") or item.canonical_pose_json.get(
            "keypoints"
        )
        empty_pose = {
            **item.canonical_pose_json,
            "pose_observations": [],
            "keypoints": [],
        }
        item.canonical_pose_json = empty_pose
        verified_payload = {
            "schema_version": "pose-active-learning-verified-pose-0001",
            "video_track_id": item.video_track_id,
            "track_revision": item.verified_track_revision,
            "focus_frame": item.frame_index,
            "pose_schema_id": item.pose_schema_id,
            "pose_schema_revision": item.pose_schema_revision,
            "pose_observations": [],
            "keypoints": [],
        }
        item.verified_pose_sha256 = canonical_json_sha256(verified_payload)
        summaries = [dict(summary) for summary in frozen.manifest_json["items"]]
        matching = [summary for summary in summaries if summary["item_id"] == item.id]
        assert len(matching) == 1
        matching[0]["verified_pose_sha256"] = item.verified_pose_sha256
        matching[0]["canonical_pose_sha256"] = canonical_json_sha256(empty_pose)
        resigned_manifest = {**frozen.manifest_json, "items": summaries}
        frozen.manifest_json = resigned_manifest
        frozen.manifest_sha256 = canonical_json_sha256(resigned_manifest)
        resigned_sha = frozen.manifest_sha256
        session.commit()

    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="item lineage no longer matches"),
    ):
        PoseTrainingDatasetService(session).native_package(dataset_id)

    graph = {
        "graph_id": "track-e-empty-resigned-pose",
        "name": "Reject re-signed empty scientist pose",
        "nodes": [
            {
                "node_id": "frozen-pose",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset_id,
                    "manifest_sha256": resigned_sha,
                },
            }
        ],
        "edges": [],
    }
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is False
    assert "pose_dataset_item_lineage_mismatch" in {
        issue["code"] for issue in plan.json()["issues"]
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item fingerprints no longer match"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, graph["nodes"][0]["parameters"], {}
        )


def test_resigned_empty_dataset_cannot_be_exported_or_planned(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Start with an API-frozen scientist-verified dataset, then simulate
    # deletion of its only verified item and re-signing the empty manifest.
    # The database CHECK requires item_count >= 1, so keep the persisted
    # count intact and verify that the signed manifest cannot hide missing rows.
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_id = str(project["id"])
    dataset_id = str(dataset["id"])
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        frozen = session.get(PoseTrainingDataset, dataset_id)
        items = list(
            session.scalars(
                select(PoseTrainingDatasetItem).where(
                    PoseTrainingDatasetItem.dataset_id == dataset_id
                )
            )
        )
        assert frozen is not None and len(items) == 1
        session.delete(items[0])
        empty_manifest = {**frozen.manifest_json, "items": [], "item_count": 0}
        frozen.manifest_json = empty_manifest
        frozen.manifest_sha256 = canonical_json_sha256(empty_manifest)
        resigned_sha = frozen.manifest_sha256
        session.commit()

    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="manifest item count no longer matches"),
    ):
        PoseTrainingDatasetService(session).manifest(dataset_id)

    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="manifest item count no longer matches"),
    ):
        PoseTrainingDatasetService(session).native_package(dataset_id)

    parameters = {"dataset_id": dataset_id, "manifest_sha256": resigned_sha}
    graph = {
        "graph_id": "track-e-resigned-empty-dataset",
        "name": "Reject emptied frozen pose training dataset",
        "nodes": [
            {
                "node_id": "frozen-pose",
                "node_type": "pose_training_dataset",
                "parameters": parameters,
            }
        ],
        "edges": [],
    }
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is False
    assert "pose_dataset_item_count_mismatch" in {issue["code"] for issue in plan.json()["issues"]}

    with (
        app.state.session_factory() as session,
        pytest.raises(ValidationError, match="item count no longer matches frozen manifest"),
    ):
        execute_pose_training_dataset_adapter(
            session, app.state.settings, project_id, parameters, {}
        )
