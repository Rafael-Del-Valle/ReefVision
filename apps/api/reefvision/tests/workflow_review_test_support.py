"""Consistent persisted upstream lineage for existing review-workflow tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import WorkflowArtifact, WorkflowNodeRun
from reefvision.storage.datasets import canonical_json_sha256


def seed_review_upstream_artifacts(
    session: Session,
    *,
    run_id: str,
    nodes: dict[str, WorkflowNodeRun],
    project_id: str,
    model_id: str,
    consensus_payload: dict[str, Any],
    disagreement_payload: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Seed pre-completed nodes with the artifacts and inputs their graph declares.

    The review tests intentionally bypass detector inference. A succeeded node
    must nevertheless retain its actual dependency IDs so the paused workflow
    is a valid persisted execution, not corrupted scientific lineage.
    """
    specs = [
        ("project", "project", "project_reference", {"project_id": project_id}),
        ("images", "images", "image_collection", {"image_ids": []}),
        ("model", "model", "model_reference", {"model_id": model_id}),
        ("detect", "proposals", "detection_proposals", {"detections": []}),
        ("consensus", "consensus", "detection_consensus", consensus_payload),
    ]
    if disagreement_payload is not None:
        specs.append(
            ("consensus", "disagreements", "detection_disagreements", disagreement_payload)
        )

    artifacts: dict[tuple[str, str], WorkflowArtifact] = {}
    for node_id, port_id, data_type, payload in specs:
        artifact = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=nodes[node_id].id,
            producer_port_id=port_id,
            data_type=data_type,
            payload_json=payload,
            payload_sha256=canonical_json_sha256(payload),
        )
        session.add(artifact)
        artifacts[node_id, port_id] = artifact
    session.flush()

    for node_id in ("project", "images", "model", "detect", "consensus"):
        nodes[node_id].status = "succeeded"
        nodes[node_id].output_artifact_ids_json = [
            artifact.id for (producer, _), artifact in artifacts.items() if producer == node_id
        ]

    nodes["project"].input_artifact_ids_json = []
    nodes["images"].input_artifact_ids_json = [artifacts["project", "project"].id]
    nodes["model"].input_artifact_ids_json = [artifacts["project", "project"].id]
    nodes["detect"].input_artifact_ids_json = [
        artifacts["images", "images"].id,
        artifacts["model", "model"].id,
    ]
    nodes["consensus"].input_artifact_ids_json = [artifacts["detect", "proposals"].id]

    disagreement = artifacts.get(("consensus", "disagreements"))
    return artifacts["consensus", "consensus"].id, disagreement.id if disagreement else None
