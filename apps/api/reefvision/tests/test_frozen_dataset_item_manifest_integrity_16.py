"""Tampered frozen coral rows must fail standalone and saved QC without rewriting review."""

from __future__ import annotations

from copy import deepcopy
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    WorkflowArtifact,
    WorkflowNodeRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.review_queues import ReviewQueueCreateRequest
from reefvision.services.frozen_dataset_integrity_16 import (
    _item_payload,
    validate_frozen_dataset_manifest,
)
from reefvision.services.review_queues import ReviewQueueService
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version, save_annotations, update_image
from reefvision.tests.test_mask_dataset_exports import _save_polygon
from reefvision.tests.test_review_queue_annotation_evidence_16 import _queue_item
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
    _study,
)


@pytest.mark.parametrize(
    "tamper",
    [
        "geometry",
        "resigned_geometry",
        "split",
        "per_class_counts",
        "original_filename",
        "snapshot_digest",
    ],
)
def test_frozen_item_evidence_cannot_change_under_standalone_or_saved_qc(
    client: TestClient, tamper: str
) -> None:
    project_id, _, version_id, _ = _study(client)
    standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": _frozen_graph(version_id)},
    )
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    workflow_url = f"/api/v1/review-queues/{payload['queue_id']}/items"
    before = client.get(workflow_url)
    assert before.status_code == 200, before.text
    assert payload["review_status"] == "requires_researcher_review"
    assert payload["priority_score_unit"] == "dimensionless"

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        frozen = session.scalar(
            select(DatasetVersionItem).where(DatasetVersionItem.dataset_version_id == version_id)
        )
        assert frozen is not None
        if tamper in {"geometry", "resigned_geometry"}:
            annotations = [dict(annotation) for annotation in frozen.annotation_snapshot_json]
            assert len(annotations) == 1
            annotations[0]["x_min"] = float(annotations[0]["x_min"]) + 3.0
            frozen.annotation_snapshot_json = annotations
            if tamper == "resigned_geometry":
                frozen.snapshot_sha256 = canonical_json_sha256(
                    _item_payload(frozen, schema_version="0007")
                )
        elif tamper == "split":
            frozen.split = "train" if frozen.split != "train" else "test"
        elif tamper == "per_class_counts":
            frozen.per_class_counts_json = {"forged_taxon": 1}
        elif tamper == "original_filename":
            frozen.original_filename = "other-coral.png"
        else:
            frozen.snapshot_sha256 = "f" * 64
        session.flush()

        # Standalone and the persisted typed Workflow Builder adapter share
        # the same immutable source check. Neither can silently create a
        # replacement review queue or infer verification from altered media.
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            ReviewQueueService(session, app.state.settings).create_queue_for_dataset_version(
                version_id, ReviewQueueCreateRequest()
            )

        node_runs = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        nodes = {node.node_type: node for node in node_runs}
        project_source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        assert project_source is not None and dataset_source is not None
        qc_node = nodes["qc_review_queue"]
        params = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_source], "dataset": [dataset_source]}
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, params, inputs
            )
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, params, inputs
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    after = client.get(workflow_url)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
    assert _queue_item(client, standalone.json()["id"])["review_state"] == "pending"


@pytest.mark.parametrize(
    "tamper",
    [
        "annotation_total",
        "class_census",
        "class_census_boolean",
        "class_census_float",
        "summary_image_count_boolean",
        "summary_annotation_count_float",
        "summary_mask_count_boolean",
        "manifest_reuse_flag_integer",
        "manifest_class_index_float",
        "manifest_item_count_boolean",
        "manifest_item_class_count_float",
        "reused_identity",
        "empty_identity",
        "negative_box",
        "zero_area_box",
        "outside_image_box",
        "nonfinite_box",
        "class_name_drift",
        "class_index_drift",
        "unknown_class_id",
        "source_digest_nonhex",
        "source_width_zero",
        "ineligible_status",
        "eligible_status_manifest_drift",
        "unknown_eligible_status",
        "split_seed_row_drift",
        "missing_group_count_forged",
        "achieved_ratios_forged",
        "achieved_ratios_negative",
        "achieved_ratios_huge",
        "blank_biological_group",
        "requested_ratios_not_normalized",
        "resolved_method_inconsistent",
        "parent_reuse_without_parent",
    ],
)
def test_resigned_frozen_detection_census_fails_standalone_and_saved_qc(
    client: TestClient, tamper: str
) -> None:
    """Rehashing cannot certify contradictory census or observation identity."""
    project_id, _, version_id, _ = _study(client)
    standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": _frozen_graph(version_id)},
    )
    assert saved.status_code == 201, saved.text
    run_id, output = _run_frozen_graph(client, project_id, saved.json()["id"])
    queue_url = f"/api/v1/review-queues/{output['queue_id']}/items"
    before = client.get(queue_url)
    assert before.status_code == 200, before.text
    assert output["review_status"] == "requires_researcher_review"
    assert output["priority_score_unit"] == "dimensionless"

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        version = session.get(DatasetVersion, version_id)
        item = session.scalar(
            select(DatasetVersionItem).where(DatasetVersionItem.dataset_version_id == version_id)
        )
        assert version is not None and item is not None
        assert version.schema_version == "0007"
        assert item.annotation_count == len(item.annotation_snapshot_json) == 1
        validate_frozen_dataset_manifest(version, [item])

        if tamper == "annotation_total":
            item.annotation_count += 1
            version.annotation_count += 1
        elif tamper == "class_census":
            item.per_class_counts_json = {"forged_taxon": item.annotation_count}
        elif tamper in {"class_census_boolean", "class_census_float"}:
            class_id = str(item.annotation_snapshot_json[0]["label_class_id"])
            item.per_class_counts_json = {
                class_id: True if tamper == "class_census_boolean" else 1.0
            }
            # ORM equality also conflates bool/float with integer counts.
            flag_modified(item, "per_class_counts_json")
        elif tamper.startswith(("summary_", "manifest_")):
            pass  # The version manifest is mutated below.
        elif tamper == "source_digest_nonhex":
            item.image_sha256 = "z" * 64
        elif tamper == "source_width_zero":
            item.width_px = 0
        elif tamper == "ineligible_status":
            item.image_annotation_status = "excluded"
        elif tamper == "eligible_status_manifest_drift":
            version.eligible_annotation_statuses_json = ["reviewed", "annotated"]
        elif tamper == "unknown_eligible_status":
            version.eligible_annotation_statuses_json = ["reviewed", "not_a_real_status"]
        elif tamper == "split_seed_row_drift":
            version.split_seed = 42 if version.split_seed is None else version.split_seed + 1
        elif tamper == "missing_group_count_forged":
            version.missing_group_key_count += 1
        elif tamper.startswith("achieved_ratios_"):
            value: int | float
            if tamper == "achieved_ratios_negative":
                key, value = "test", -1e-15
            elif tamper == "achieved_ratios_huge":
                key, value = "train", 10**400
            else:
                key, value = "train", 0.123456
            version.achieved_ratios_json = {**version.achieved_ratios_json, key: value}
        elif tamper == "requested_ratios_not_normalized":
            version.requested_ratios_json = {"train": 0.8, "validation": 0.4, "test": 0.1}
        elif tamper == "resolved_method_inconsistent":
            version.requested_split_method = "manual"
            version.resolved_split_method = "group_random"
        elif tamper == "parent_reuse_without_parent":
            assert version.parent_version_id is None
            version.reuse_parent_assignments = True
        elif tamper == "blank_biological_group":
            item.group_key = "\u2003"
            version.missing_group_key_count = 0
        else:
            annotations = [dict(annotation) for annotation in item.annotation_snapshot_json]
            if tamper == "reused_identity":
                annotations.append(dict(annotations[0]))
                item.annotation_count += 1
                version.annotation_count += 1
                class_id = str(annotations[0]["label_class_id"])
                item.per_class_counts_json = {class_id: item.annotation_count}
            elif tamper == "empty_identity":
                annotations[0]["id"] = ""
            elif tamper == "negative_box":
                annotations[0]["x_min"] = -1.0
            elif tamper == "zero_area_box":
                annotations[0]["x_max"] = annotations[0]["x_min"]
            elif tamper == "outside_image_box":
                annotations[0]["y_max"] = item.height_px + 1.0
            elif tamper == "class_name_drift":
                annotations[0]["class_name"] = "Incorrect coral taxon"
            elif tamper == "class_index_drift":
                annotations[0]["class_index"] = 999
            elif tamper == "unknown_class_id":
                annotations[0]["label_class_id"] = "foreign-coral-class"
                item.per_class_counts_json = {"foreign-coral-class": 1}
            else:
                annotations[0]["x_max"] = float("inf")
            item.annotation_snapshot_json = annotations

        # Re-sign both levels so validation checks biological evidence,
        # not merely a checksum mismatch. These are not authenticated signatures.
        payload = _item_payload(item, schema_version="0007")
        item.snapshot_sha256 = canonical_json_sha256(payload)
        manifest = {
            **version.manifest_json,
            "items": [{**payload, "snapshot_sha256": item.snapshot_sha256}],
        }
        if tamper.startswith("manifest_"):
            manifest = deepcopy(manifest)
            if tamper == "manifest_reuse_flag_integer":
                manifest["split_config"]["reuse_parent_assignments"] = int(
                    version.reuse_parent_assignments
                )
            elif tamper == "manifest_class_index_float":
                entry = manifest["class_map"][0]
                entry["class_index"] = float(entry["class_index"])
            elif tamper == "manifest_item_count_boolean":
                manifest["items"][0]["annotation_count"] = True
            else:
                counts = manifest["items"][0]["per_class_counts"]
                class_id = str(item.annotation_snapshot_json[0]["label_class_id"])
                counts[class_id] = 1.0
            # The original row and its item digest remain unchanged.
            assert manifest == version.manifest_json
            assert canonical_json_sha256(manifest) != version.manifest_sha256
        if tamper.startswith("summary_"):
            summary_key, replacement = {
                "summary_image_count_boolean": ("image_count", True),
                "summary_annotation_count_float": ("annotation_count", 1.0),
                "summary_mask_count_boolean": ("mask_annotation_count", False),
            }[tamper]
            manifest["summary"] = {
                **version.manifest_json["summary"],
                summary_key: replacement,
            }
        if tamper in {"annotation_total", "reused_identity"}:
            manifest["summary"] = {
                **version.manifest_json["summary"],
                "annotation_count": version.annotation_count,
            }
        if tamper in {
            "unknown_eligible_status",
            "missing_group_count_forged",
            "achieved_ratios_forged",
            "achieved_ratios_negative",
            "achieved_ratios_huge",
            "blank_biological_group",
            "requested_ratios_not_normalized",
            "resolved_method_inconsistent",
            "parent_reuse_without_parent",
        }:
            manifest["split_config"] = {
                **version.manifest_json["split_config"],
            }
            if tamper == "unknown_eligible_status":
                manifest["split_config"]["eligible_annotation_statuses"] = list(
                    version.eligible_annotation_statuses_json
                )
            elif tamper in {"missing_group_count_forged", "blank_biological_group"}:
                manifest["split_config"]["missing_group_key_count"] = (
                    version.missing_group_key_count
                )
            elif tamper == "requested_ratios_not_normalized":
                manifest["split_config"]["requested_ratios"] = version.requested_ratios_json
            elif tamper == "resolved_method_inconsistent":
                manifest["split_config"]["requested_split_method"] = version.requested_split_method
                manifest["split_config"]["resolved_split_method"] = version.resolved_split_method
            elif tamper == "parent_reuse_without_parent":
                manifest["split_config"]["reuse_parent_assignments"] = True
            else:
                manifest["split_config"]["achieved_ratios"] = version.achieved_ratios_json
        version.manifest_json = manifest
        flag_modified(version, "manifest_json")
        version.manifest_sha256 = canonical_json_sha256(manifest)
        session.flush()
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            validate_frozen_dataset_manifest(version, [item])
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            ReviewQueueService(session, app.state.settings).create_queue_for_dataset_version(
                version_id, ReviewQueueCreateRequest()
            )

        if tamper.startswith(("class_census_", "summary_", "manifest_", "achieved_ratios_")) or (
            tamper in {"blank_biological_group", "parent_reuse_without_parent"}
        ):
            with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
                ReviewQueueService(session, app.state.settings).regenerate(standalone.json()["id"])

        nodes = {
            node.node_type: node
            for node in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }
        project_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        assert project_artifact is not None and dataset_artifact is not None
        qc_node = nodes["qc_review_queue"]
        params = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_artifact], "dataset": [dataset_artifact]}
        # The saved typed source still records the original manifest digest.
        # Most re-signed mutations are stopped by its producer-binding gate,
        # but a row-only drift with unchanged selection can hit the shared
        # frozen-integrity validator first. Both paths must fail closed.
        expected_error = (
            "Frozen dataset item snapshot"
            if tamper in {"eligible_status_manifest_drift", "split_seed_row_drift"}
            else "QC Review Queue dataset version or manifest does not match"
        )
        with pytest.raises(ValidationError, match=expected_error):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, params, inputs
            )
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, params, inputs
        )
        assert replay[0]["payload"] == output
        session.rollback()

    after = client.get(queue_url)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
    assert _queue_item(client, standalone.json()["id"])["review_state"] == "pending"


@pytest.mark.parametrize(
    "tamper",
    [
        "draft_status",
        "missing_status",
        "unsupported_geometry",
        "outside_polygon",
        "wrong_polygon_bounds",
        "wrong_polygon_area",
        "non_numeric_polygon",
        "degenerate_polygon",
        "raster_missing_path",
        "raster_missing_digest",
        "raster_outside_box",
        "raster_impossible_area",
        "mask_class_name_drift",
        "mask_class_index_drift",
        "mask_unknown_class_id",
    ],
)
def test_resigned_mask_review_provenance_fails_standalone_and_saved_qc(
    client: TestClient, tamper: str
) -> None:
    """An originally verified coral mask cannot become a draft in frozen QC."""
    project = create_project(client, "Frozen reviewed coral masks")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="mask-review-evidence.png")
    image_id = imported["successful"][0]["image_id"]
    _save_polygon(
        client,
        image_id=image_id,
        class_id=project["label_classes"][0]["id"],
        mask_id=str(uuid4()),
        points=[(8, 8), (28, 8), (28, 28), (8, 28)],
        base_revision=0,
    )
    version_id = create_version(client, project_id, name="Verified mask snapshot")["id"]
    standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": _frozen_graph(version_id)},
    )
    assert saved.status_code == 201, saved.text
    run_id, output = _run_frozen_graph(client, project_id, saved.json()["id"])
    queue_url = f"/api/v1/review-queues/{output['queue_id']}/items"
    original_queue = client.get(queue_url)
    assert original_queue.status_code == 200, original_queue.text
    assert output["review_status"] == "requires_researcher_review"
    assert output["priority_score_unit"] == "dimensionless"

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        version = session.get(DatasetVersion, version_id)
        item = session.scalar(
            select(DatasetVersionItem).where(DatasetVersionItem.dataset_version_id == version_id)
        )
        assert version is not None and item is not None
        assert item.mask_annotation_count == len(item.mask_annotation_snapshot_json) == 1
        validate_frozen_dataset_manifest(version, [item])
        masks = deepcopy(item.mask_annotation_snapshot_json)
        assert masks[0]["status"] == "verified"
        if tamper == "draft_status":
            masks[0]["status"] = "draft"
        elif tamper == "missing_status":
            masks[0].pop("status")
        elif tamper == "unsupported_geometry":
            masks[0]["geometry_kind"] = "unregistered_mask"
        elif tamper == "outside_polygon":
            masks[0]["polygon_json"][0][0] = item.width_px + 1
        elif tamper == "wrong_polygon_bounds":
            masks[0]["x_min"] = 0.0
        elif tamper == "wrong_polygon_area":
            masks[0]["area_pixels"] += 1
        elif tamper == "non_numeric_polygon":
            masks[0]["polygon_json"][0][0] = "invalid coordinate"
        elif tamper == "degenerate_polygon":
            masks[0]["polygon_json"] = [[8, 8], [18, 8], [28, 8]]
        elif tamper == "mask_class_name_drift":
            masks[0]["class_name"] = "Incorrect coral taxon"
        elif tamper == "mask_class_index_drift":
            masks[0]["class_index"] = 999
        elif tamper == "mask_unknown_class_id":
            masks[0]["label_class_id"] = "foreign-coral-class"
            item.per_mask_class_counts_json = {"foreign-coral-class": 1}
        else:
            masks[0]["geometry_kind"] = "raster_mask"
            masks[0]["polygon_json"] = None
            masks[0]["mask_path"] = "projects/example/masks/coral.png"
            masks[0]["mask_content_sha256"] = "a" * 64
            if tamper == "raster_missing_path":
                masks[0]["mask_path"] = None
            elif tamper == "raster_missing_digest":
                masks[0]["mask_content_sha256"] = None
            elif tamper == "raster_outside_box":
                masks[0]["x_max"] = item.width_px + 1
            else:
                masks[0]["area_pixels"] = item.width_px * item.height_px + 1
        item.mask_annotation_snapshot_json = masks

        # Both stored checksums are recomputed; the scientific review-state
        # constraint, not an incidental checksum mismatch, must block QC.
        payload = _item_payload(item, schema_version="0007")
        item.snapshot_sha256 = canonical_json_sha256(payload)
        manifest = deepcopy(version.manifest_json)
        manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
        version.manifest_json = manifest
        version.manifest_sha256 = canonical_json_sha256(manifest)
        session.flush()

        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            validate_frozen_dataset_manifest(version, [item])
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            ReviewQueueService(session, app.state.settings).create_queue_for_dataset_version(
                version_id, ReviewQueueCreateRequest()
            )
        nodes = {
            node.node_type: node
            for node in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }
        project_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        assert project_artifact is not None and dataset_artifact is not None
        qc_node = nodes["qc_review_queue"]
        params = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_artifact], "dataset": [dataset_artifact]}
        with pytest.raises(
            ValidationError, match="QC Review Queue dataset version or manifest does not match"
        ):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, params, inputs
            )
        session.rollback()

        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, params, inputs
        )
        assert replay[0]["payload"] == output
        session.rollback()

    restored_queue = client.get(queue_url)
    assert restored_queue.status_code == 200, restored_queue.text
    assert restored_queue.json() == original_queue.json()
    assert _queue_item(client, standalone.json()["id"])["review_state"] == "pending"


def test_resigned_colony_split_leakage_blocks_standalone_and_saved_qc(
    client: TestClient,
) -> None:
    """Fail closed when one source colony crosses splits despite fresh digests."""
    project = create_project(client, "Grouped coral replicas")
    project_id = project["id"]
    image_ids: list[str] = []
    for index in range(2):
        imported = import_one(
            client,
            project_id,
            filename=f"colony-{index}.png",
            relative_path=f"colony/colony-{index}.png",
            size=(80 + index, 60),
        )
        image_id = imported["successful"][0]["image_id"]
        image_ids.append(image_id)
        save_annotations(
            client,
            image_id,
            base_revision=0,
            annotation_status="reviewed",
            annotations=[
                {
                    "id": str(uuid4()),
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 25,
                    "y_max": 25,
                }
            ],
        )
        update_image(
            client,
            image_id,
            group_key="same-parent-colony",
            annotation_status="reviewed",
        )
    version_id = create_version(client, project_id, name="No-leak coral dataset")["id"]
    standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": _frozen_graph(version_id)},
    )
    assert saved.status_code == 201, saved.text
    run_id, output = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert output["review_status"] == "requires_researcher_review"
    assert output["priority_score_unit"] == "dimensionless"
    queue_url = f"/api/v1/review-queues/{output['queue_id']}/items"
    before = client.get(queue_url)
    assert before.status_code == 200, before.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        version = session.get(DatasetVersion, version_id)
        items = session.scalars(
            select(DatasetVersionItem).where(DatasetVersionItem.dataset_version_id == version_id)
        ).all()
        assert version is not None and len(items) == 2
        assert len({item.split for item in items}) == 1
        assert {item.group_key for item in items} == {"same-parent-colony"}
        validate_frozen_dataset_manifest(version, items)
        # Recompute the per-item and whole-version SHA-256 after moving the
        # second image alone into a different evaluation split.
        items[1].split = "test" if items[0].split != "test" else "train"
        items[1].snapshot_sha256 = canonical_json_sha256(
            _item_payload(items[1], schema_version="0007")
        )
        manifest = deepcopy(version.manifest_json)
        manifest["items"] = [
            {
                **_item_payload(item, schema_version="0007"),
                "snapshot_sha256": item.snapshot_sha256,
            }
            for item in items
        ]
        version.manifest_json = manifest
        version.manifest_sha256 = canonical_json_sha256(manifest)
        session.flush()

        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            validate_frozen_dataset_manifest(version, items)
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            ReviewQueueService(session, app.state.settings).create_queue_for_dataset_version(
                version_id, ReviewQueueCreateRequest()
            )
        nodes = {
            node.node_type: node
            for node in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }
        project_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        assert project_artifact is not None and dataset_artifact is not None
        qc_node = nodes["qc_review_queue"]
        params = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_artifact], "dataset": [dataset_artifact]}
        # The saved artifact retains the original version digest, so the
        # existing producer-binding gate rejects this newly re-signed version.
        with pytest.raises(
            ValidationError, match="QC Review Queue dataset version or manifest does not match"
        ):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, params, inputs
            )
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, params, inputs
        )
        assert replay[0]["payload"] == output
        session.rollback()

    after = client.get(queue_url)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
    standalone_items = client.get(f"/api/v1/review-queues/{standalone.json()['id']}/items")
    assert standalone_items.status_code == 200, standalone_items.text
    assert standalone_items.json()["total"] == 2
    assert all(item["review_state"] == "pending" for item in standalone_items.json()["items"])
