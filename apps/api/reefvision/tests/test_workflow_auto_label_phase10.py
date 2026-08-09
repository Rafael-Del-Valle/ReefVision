from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reefvision.db.models import (
    ActiveLearningRound,
    Annotation,
    AnnotationEvent,
    ModelRegistration,
    ReviewQueueItem,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.review_queues import ReviewQueueItemResponse
from reefvision.services.workflow_auto_label import (
    ensure_disagreement_active_learning_round,
    materialize_consensus_annotations,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one


def _graph(model_id: str) -> dict[str, object]:
    return {
        "graph_id": "reviewed-auto-label",
        "name": "Reviewed consensus auto label",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {"node_id": "detect", "node_type": "detection_inference"},
            {
                "node_id": "consensus",
                "node_type": "detection_consensus",
                "parameters": {"required_votes": 1},
            },
            {"node_id": "review", "node_type": "detection_review_gate"},
        ],
        "edges": [
            {
                "edge_id": "project-images",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-model",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "model",
                "target_port_id": "project",
            },
            {
                "edge_id": "images-detect",
                "source_node_id": "images",
                "source_port_id": "images",
                "target_node_id": "detect",
                "target_port_id": "images",
            },
            {
                "edge_id": "model-detect",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "detect",
                "target_port_id": "model",
            },
            {
                "edge_id": "detect-consensus",
                "source_node_id": "detect",
                "source_port_id": "proposals",
                "target_node_id": "consensus",
                "target_port_id": "predictions",
            },
            {
                "edge_id": "consensus-review",
                "source_node_id": "consensus",
                "source_port_id": "consensus",
                "target_node_id": "review",
                "target_port_id": "proposals",
            },
        ],
    }


def _seed_valid_consensus_review(
    client: TestClient,
) -> tuple[dict[str, object], str, str, str, str, str, str]:
    project = create_project(client, "Workflow Auto Label")
    imported = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(imported["successful"][0]["image_id"])
    class_id = str(project["label_classes"][0]["id"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="detector",
            display_name="Auto Label detector",
            source_filename="detector.pt",
            managed_path=f"projects/{project['id']}/models/detector.pt",
            sha256="b" * 64,
            file_size_bytes=10,
            framework="test",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            input_size_json={"width": 640, "height": 640},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        model_id = model.id

    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": _graph(model_id)},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run_id = str(queued.json()["id"])
    job_id = str(queued.json()["job_id"])

    consensus_payload = {
        "schema_version": "detection-consensus-0001",
        "project_id": project["id"],
        "source_ids": [model_id, "cloud-vlm:gemini:test"],
        "source_count": 2,
        "required_votes": 2,
        "iou_threshold": 0.5,
        "confidence_threshold": 0.0,
        "class_aware": True,
        "box_strategy": "mean",
        "count": 1,
        "detections": [
            {
                "consensus_id": "accepted-consensus",
                "image_id": image_id,
                "label_class_id": class_id,
                "predicted_label": "polyp",
                "vote_count": 2,
                "required_votes": 2,
                "total_sources": 2,
                "source_ids": [model_id, "cloud-vlm:gemini:test"],
                "mean_confidence": 0.91,
                "minimum_pairwise_iou": 0.72,
                "box_strategy": "mean",
                "box": {
                    "x_min": 10.0,
                    "y_min": 12.0,
                    "x_max": 42.0,
                    "y_max": 48.0,
                },
                "members": [],
            }
        ],
    }
    disagreement_payload = {
        "schema_version": "detection-consensus-0001",
        "project_id": project["id"],
        "source_ids": [model_id, "cloud-vlm:gemini:test"],
        "source_count": 2,
        "required_votes": 2,
        "iou_threshold": 0.5,
        "confidence_threshold": 0.0,
        "class_aware": True,
        "box_strategy": "mean",
        "count": 1,
        "detections": [
            {
                "consensus_id": "failed-consensus",
                "image_id": image_id,
                "label_class_id": class_id,
                "predicted_label": "polyp",
                "vote_count": 1,
                "required_votes": 2,
                "total_sources": 2,
                "source_ids": [model_id],
                "votes_missing": 1,
                "reason": "insufficient_votes",
                "box": {
                    "x_min": 55.0,
                    "y_min": 15.0,
                    "x_max": 75.0,
                    "y_max": 35.0,
                },
            }
        ],
    }
    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        nodes = {
            node.node_id: node
            for node in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }
        for node_id in ("project", "images", "model", "detect", "consensus"):
            nodes[node_id].status = "succeeded"
        consensus = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=nodes["consensus"].id,
            producer_port_id="consensus",
            data_type="detection_consensus",
            payload_json=consensus_payload,
            payload_sha256=canonical_json_sha256(consensus_payload),
        )
        disagreement = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=nodes["consensus"].id,
            producer_port_id="disagreements",
            data_type="detection_disagreements",
            payload_json=disagreement_payload,
            payload_sha256=canonical_json_sha256(disagreement_payload),
        )
        session.add_all([consensus, disagreement])
        session.flush()
        nodes["consensus"].output_artifact_ids_json = [consensus.id, disagreement.id]
        consensus_id = consensus.id
        disagreement_id = disagreement.id
        session.commit()

    return project, image_id, class_id, run_id, job_id, consensus_id, disagreement_id


def test_reviewed_consensus_materializes_annotation_and_routes_disagreement(
    client: TestClient,
) -> None:
    project, image_id, class_id, run_id, job_id, consensus_id, disagreement_id = (
        _seed_valid_consensus_review(client)
    )
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    ) is True

    paused = client.get(f"/api/v1/workflow-runs/{run_id}").json()
    review_node = next(node for node in paused["nodes"] if node["node_id"] == "review")
    assert review_node["status"] == "waiting_for_review"

    resumed = client.post(
        f"/api/v1/workflow-node-runs/{review_node['id']}/resume-review",
        json={
            "reviewed_by": "scientist",
            "note": "Consensus checked against source image.",
        },
    )
    assert resumed.status_code == 202, resumed.text

    with app.state.session_factory() as session:
        annotations = list(
            session.scalars(select(Annotation).where(Annotation.image_id == image_id))
        )
        assert len(annotations) == 1
        annotation = annotations[0]
        assert annotation.label_class_id == class_id
        assert annotation.source_type == "workflow_consensus"
        assert annotation.created_by == "scientist"
        assert annotation.provenance_json["workflow_artifact_id"] == consensus_id
        assert annotation.provenance_json["vote_count"] == 2
        assert annotation.provenance_json["required_votes"] == 2
        assert annotation.provenance_json["reviewed_by"] == "scientist"
        assert (
            session.scalar(
                select(func.count(AnnotationEvent.id)).where(
                    AnnotationEvent.annotation_id == annotation.id,
                    AnnotationEvent.event_type == "created",
                )
            )
            == 1
        )

        rounds = list(
            session.scalars(
                select(ActiveLearningRound).where(
                    ActiveLearningRound.project_id == project["id"]
                )
            )
        )
        assert len(rounds) == 1
        round_record = rounds[0]
        assert round_record.strategy == "workflow_disagreement"
        assert round_record.selected_count == 1
        assert round_record.strategy_config_json["source"] == "workflow_consensus"
        queue_items = list(
            session.scalars(
                select(ReviewQueueItem).where(
                    ReviewQueueItem.review_queue_id == round_record.review_queue_id
                )
            )
        )
        assert len(queue_items) == 1
        assert queue_items[0].image_id == image_id
        assert "Consensus disagreement" in str(queue_items[0].reason_summary)
        assert queue_items[0].review_state == "pending"
        serialized_queue_item = ReviewQueueItemResponse.model_validate(queue_items[0])
        assert serialized_queue_item.score_breakdown_json[0].signal_id == (
            "workflow_consensus_disagreement"
        )
        assert serialized_queue_item.score_breakdown_json[0].raw_value == 1.0

        review = session.get(WorkflowNodeRun, str(review_node["id"]))
        assert review is not None
        approval = review.result_json["review_approval"]
        assert approval["consensus_materialization"][0]["materialized_count"] == 1
        assert approval["active_learning_handoff"][0]["source_artifact_id"] == disagreement_id
        assert approval["active_learning_handoff"][0]["round_id"] == round_record.id


def test_auto_label_postprocessing_is_idempotent(client: TestClient) -> None:
    project, _, _, _, _, consensus_id, disagreement_id = _seed_valid_consensus_review(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        consensus = session.get(WorkflowArtifact, consensus_id)
        disagreement = session.get(WorkflowArtifact, disagreement_id)
        assert consensus is not None and disagreement is not None

        first_annotations = materialize_consensus_annotations(
            session,
            project_id=str(project["id"]),
            artifact=consensus,
            reviewed_by="scientist",
        )
        second_annotations = materialize_consensus_annotations(
            session,
            project_id=str(project["id"]),
            artifact=consensus,
            reviewed_by="scientist",
        )
        first_round = ensure_disagreement_active_learning_round(
            session,
            project_id=str(project["id"]),
            artifact=disagreement,
            created_by="scientist",
        )
        second_round = ensure_disagreement_active_learning_round(
            session,
            project_id=str(project["id"]),
            artifact=disagreement,
            created_by="scientist",
        )
        session.commit()

        assert first_annotations["materialized_count"] == 1
        assert second_annotations["materialized_count"] == 0
        assert first_annotations["annotation_ids"] == second_annotations["annotation_ids"]
        assert first_round is not None and second_round is not None
        assert first_round["created"] is True
        assert second_round["created"] is False
        assert first_round["round_id"] == second_round["round_id"]
        assert session.scalar(select(func.count(Annotation.id))) == 1
        assert session.scalar(select(func.count(ActiveLearningRound.id))) == 1
