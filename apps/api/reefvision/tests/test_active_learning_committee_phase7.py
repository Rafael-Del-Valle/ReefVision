from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, ModelRegistration, PredictionProposal
from reefvision.services.active_learning_committee import score_committee_disagreement
from reefvision.tests.test_annotations import create_project, import_one


def test_committee_signal_is_bounded_and_explainable() -> None:
    result = score_committee_disagreement(
        model_ids=["a", "b", "c"],
        model_names={"a": "YOLO", "b": "RF-DETR", "c": "YOLO11"},
        predictions=[
            {"model_id": "a", "confidence": 0.90},
            {"model_id": "b", "confidence": 0.50},
            {"model_id": "b", "confidence": 0.60},
            {"model_id": "b", "confidence": 0.70},
        ],
    )

    assert 0.0 <= result["score"] <= 100.0
    assert result["count_disagreement"] == 1.0
    assert result["missing_model_fraction"] == 1 / 3
    assert result["confidence_disagreement"] == 0.30
    assert [item["count"] for item in result["per_model"]] == [1, 3, 0]
    assert "YOLO=1 detections" in result["reason_summary"]
    assert "RF-DETR=3 detections" in result["reason_summary"]
    assert "YOLO11=0 detections" in result["reason_summary"]


def _model(project_id: str, index: int) -> ModelRegistration:
    return ModelRegistration(
        project_id=project_id,
        purpose="detector",
        display_name=f"Committee detector {index}",
        source_filename=f"committee-{index}.pt",
        managed_path=f"projects/{project_id}/models/committee-{index}.pt",
        sha256=str(index) * 64,
        file_size_bytes=10,
        framework="ultralytics",
        task="detect",
        provider_name="ultralytics",
        provider_version="test",
        class_map_json={},
        input_size_json={},
        metadata_json={},
    )


def _proposal(
    *,
    project_id: str,
    image_id: str,
    model: ModelRegistration,
    job_id: str,
    class_id: str,
    confidence: float,
    offset: float,
) -> PredictionProposal:
    return PredictionProposal(
        project_id=project_id,
        image_id=image_id,
        model_id=model.id,
        inference_job_id=job_id,
        model_checksum=model.sha256,
        label_class_id=class_id,
        predicted_label="target",
        predicted_index=0,
        confidence=confidence,
        geometry_kind="bounding_box",
        x_min=offset,
        y_min=offset,
        x_max=offset + 10.0,
        y_max=offset + 10.0,
        review_status="pending",
        inference_settings_json={},
        provenance_json={"source": "committee-test"},
    )


def test_committee_round_selects_image_with_highest_model_disagreement(
    client: TestClient,
) -> None:
    project = create_project(client, "Committee acquisition")
    first = import_one(
        client,
        project["id"],
        filename="disagreement.png",
        relative_path="committee/disagreement.png",
    )
    second = import_one(
        client,
        project["id"],
        filename="agreement.png",
        relative_path="committee/agreement.png",
    )
    disagreement_image = str(first["successful"][0]["image_id"])
    agreement_image = str(second["successful"][0]["image_id"])
    class_id = str(project["label_classes"][0]["id"])

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        models = [_model(str(project["id"]), index) for index in (1, 2, 3)]
        session.add_all(models)
        session.flush()
        job = Job(
            project_id=project["id"],
            job_type="inference",
            status="succeeded",
            request_json={"source": "committee-test"},
            result_json={},
        )
        session.add(job)
        session.flush()

        proposals: list[PredictionProposal] = []
        proposals.append(
            _proposal(
                project_id=str(project["id"]),
                image_id=disagreement_image,
                model=models[0],
                job_id=job.id,
                class_id=class_id,
                confidence=0.92,
                offset=1.0,
            )
        )
        for index in range(4):
            proposals.append(
                _proposal(
                    project_id=str(project["id"]),
                    image_id=disagreement_image,
                    model=models[1],
                    job_id=job.id,
                    class_id=class_id,
                    confidence=0.52 + index * 0.03,
                    offset=20.0 + index,
                )
            )
        for model_index, model in enumerate(models):
            for detection_index in range(2):
                proposals.append(
                    _proposal(
                        project_id=str(project["id"]),
                        image_id=agreement_image,
                        model=model,
                        job_id=job.id,
                        class_id=class_id,
                        confidence=0.79 + model_index * 0.01,
                        offset=40.0 + detection_index * 12.0,
                    )
                )
        session.add_all(proposals)
        session.commit()
        model_ids = [model.id for model in models]

    request = {
        "name": "Three-model committee",
        "strategy": "committee",
        "requested_size": 1,
        "model_ids": model_ids,
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json=request,
    )
    assert response.status_code == 201, response.text
    round_record = response.json()
    assert round_record["strategy"] == "committee"
    assert round_record["model_ids_json"] == model_ids
    assert round_record["strategy_config_json"]["minimum_models"] == 2
    assert (
        round_record["strategy_config_json"]["committee_formula_id"]
        == "detection_committee_disagreement_v1"
    )

    selected = round_record["selection_manifest_json"]["items"][0]
    assert selected["image_id"] == disagreement_image
    assert selected["score"] > 60.0
    committee = selected["committee"]
    assert [item["count"] for item in committee["per_model"]] == [1, 4, 0]
    assert committee["missing_model_fraction"] == 1 / 3
    assert "Committee detector 1=1 detections" in selected["reason_summary"]
    assert "Committee detector 2=4 detections" in selected["reason_summary"]
    assert "Committee detector 3=0 detections" in selected["reason_summary"]

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={**request, "name": "Equivalent committee"},
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == round_record["id"]

    too_small = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Invalid committee",
            "strategy": "committee",
            "requested_size": 1,
            "model_ids": model_ids[:1],
        },
    )
    assert too_small.status_code == 422, too_small.text

    with app.state.session_factory() as session:
        assist = ModelRegistration(
            project_id=project["id"],
            purpose="assist",
            display_name="Not a committee detector",
            source_filename="assist.pth",
            managed_path=f"projects/{project['id']}/models/assist.pth",
            sha256="9" * 64,
            file_size_bytes=10,
            framework="segment_anything",
            task="assist_segmentation",
            provider_name="segment_anything",
            provider_version="test",
            class_map_json={},
            input_size_json=None,
            metadata_json={},
        )
        session.add(assist)
        session.commit()
        assist_id = assist.id

    wrong_purpose = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Mixed-purpose committee",
            "strategy": "committee",
            "requested_size": 1,
            "model_ids": [model_ids[0], assist_id],
        },
    )
    assert wrong_purpose.status_code == 422, wrong_purpose.text
    assert "requires registered detection models" in wrong_purpose.text
