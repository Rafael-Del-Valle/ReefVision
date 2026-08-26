from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.inference as inference_module
import reefvision.ml.assist_runtime as assist_runtime_module
from reefvision.jobs.inference import process_inference_job
from reefvision.ml.providers import (
    AssistModelMetadata,
    AssistPrediction,
    DetectionModelMetadata,
    DetectionPrediction,
    PixelBox,
)
from reefvision.services.models import ModelService
from reefvision.tests.test_annotations import create_project, import_one

VALID_ASSIST_MASK_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAAAAADUTGJQAAAAL0lEQVR4nO3MMREAAAgE"
    "ILV/CKPawfsRAtBbWRP+hEKhUCgUCoVCoVAoFAqFwqcDY9wBGD01rogAAAAASUVORK5CYII="
)


class FakeDetectorRegistrationProvider:
    provider_name = "fake_detector"
    provider_version = "test"

    def inspect_model(self, model_path: Any) -> DetectionModelMetadata:
        assert model_path.exists()
        assert str(model_path).endswith(".pt")
        return DetectionModelMetadata(
            framework="fake",
            task="detect",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=["soft coral"],
            input_size={"imgsz": 640},
            metadata={"trusted_checkpoint": True},
        )

    def load_model(self, model_path: Any, device: str) -> None:
        return None

    def predict(self, image_path: Any, settings: Any) -> list[DetectionPrediction]:
        return []

    def unload_model(self) -> None:
        return None


class FakeDetectorWorkerProvider:
    provider_name = "fake_detector"
    provider_version = "test"

    def load_model(self, model_path: Any, device: str) -> None:
        assert model_path.exists()

    def predict(self, image_path: Any, settings: Any) -> list[DetectionPrediction]:
        assert image_path.exists()
        return [
            DetectionPrediction(
                label="soft coral",
                class_index=0,
                confidence=0.91,
                box=PixelBox(x_min=5, y_min=4, x_max=32, y_max=28),
            )
        ]

    def unload_model(self) -> None:
        return None


class FakeAssistRegistrationProvider:
    provider_name = "segment_anything"
    provider_version = "test"

    def inspect_model(self, model_path: Any) -> AssistModelMetadata:
        assert model_path.exists()
        assert str(model_path).endswith(".pth")
        return AssistModelMetadata(
            framework="segment_anything",
            task="assist_segmentation",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            metadata={"variant": "vit_b", "trusted_checkpoint": True},
        )

    def load_model(self, model_path: Any, device: str) -> None:
        return None

    def prepare_image(self, image_path: Any) -> object:
        assert image_path.exists()
        return object()

    def predict_from_points(
        self,
        prepared_image: Any,
        positive_points: list[Any],
        negative_points: list[Any],
        context_box: PixelBox | None = None,
    ) -> AssistPrediction:
        assert positive_points
        return AssistPrediction(
            mask="fake-mask",
            box=PixelBox(x_min=8, y_min=6, x_max=26, y_max=24),
            score=0.97,
        )

    def predict_from_box(self, prepared_image: Any, box: PixelBox) -> AssistPrediction:
        return AssistPrediction(mask="fake-mask", box=box, score=0.95)

    def unload_model(self) -> None:
        return None


def register_model(
    client: TestClient,
    project_id: str,
    *,
    purpose: str,
    filename: str,
    display_name: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/models/register",
        files={"file": (filename, b"fixture-model", "application/octet-stream")},
        data={"purpose": purpose, "display_name": display_name},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_register_model_and_create_inference_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ModelService,
        "_provider_for_purpose",
        lambda self, purpose: FakeDetectorRegistrationProvider(),
    )

    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    model = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="fixture-detector.pt",
        display_name="Fixture Detector",
    )

    assert model["purpose"] == "detector"
    assert model["framework"] == "fake"
    assert model["task"] == "detect"
    assert model["class_map_json"]["labels"] == ["soft coral"]

    response = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model["id"], "image_ids": [image_id], "device": "cpu"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["job_type"] == "inference"
    assert payload["status"] == "queued"
    assert payload["progress_total"] == 1


def test_inference_job_creates_pending_proposal_and_acceptance_records_provenance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ModelService,
        "_provider_for_purpose",
        lambda self, purpose: FakeDetectorRegistrationProvider(),
    )
    monkeypatch.setattr(
        inference_module,
        "detection_provider_for_name",
        lambda provider_name: FakeDetectorWorkerProvider(),
    )

    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    model = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="fixture-detector.pt",
        display_name="Fixture Detector",
    )
    job = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model["id"], "image_ids": [image_id], "device": "cpu"},
    ).json()

    app = cast(FastAPI, client.app)
    processed = process_inference_job(app.state.settings, app.state.session_factory, job["id"])
    assert processed is True

    proposals = client.get(f"/api/v1/images/{image_id}/prediction-proposals")
    assert proposals.status_code == 200, proposals.text
    pending = proposals.json()["items"]
    assert len(pending) == 1
    assert pending[0]["review_status"] == "pending"
    assert pending[0]["confidence"] == 0.91

    accepted = client.post(
        f"/api/v1/prediction-proposals/{pending[0]['id']}/accept",
        json={"label_class_id": label_class_id},
    )
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload["proposal"]["review_status"] == "edited_and_accepted"
    assert payload["annotation"]["source_type"] == "accepted_prediction"
    assert payload["annotation"]["source_prediction_id"] == pending[0]["id"]
    assert payload["annotation"]["provenance_json"]["original_confidence"] == 0.91
    for key, value in (pending[0]["provenance_json"] or {}).items():
        assert payload["proposal"]["provenance_json"][key] == value
    assert payload["proposal"]["confidence"] == pending[0]["confidence"]
    assert payload["proposal"]["predicted_label"] == pending[0]["predicted_label"]


def test_rejecting_a_prediction_does_not_create_an_annotation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ModelService,
        "_provider_for_purpose",
        lambda self, purpose: FakeDetectorRegistrationProvider(),
    )
    monkeypatch.setattr(
        inference_module,
        "detection_provider_for_name",
        lambda provider_name: FakeDetectorWorkerProvider(),
    )

    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    model = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="fixture-detector.pt",
        display_name="Fixture Detector",
    )
    job = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model["id"], "image_ids": [image_id], "device": "cpu"},
    ).json()

    app = cast(FastAPI, client.app)
    assert process_inference_job(app.state.settings, app.state.session_factory, job["id"]) is True
    proposal_id = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"][0][
        "id"
    ]

    rejected = client.post(f"/api/v1/prediction-proposals/{proposal_id}/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["proposal"]["review_status"] == "rejected"

    annotations = client.get(f"/api/v1/images/{image_id}/annotations").json()["annotations"]
    assert annotations == []


def test_assist_session_brush_and_accept_creates_assist_annotation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ModelService,
        "_provider_for_purpose",
        lambda self, purpose: FakeAssistRegistrationProvider(),
    )
    monkeypatch.setattr(
        assist_runtime_module,
        "mask_to_png_base64",
        lambda mask: VALID_ASSIST_MASK_PNG_BASE64,
    )

    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    model = register_model(
        client,
        project["id"],
        purpose="assist",
        filename="sam_vit_b_fixture.pth",
        display_name="Fixture SAM",
    )

    app = cast(FastAPI, client.app)
    monkeypatch.setattr(
        app.state.assist_runtime,
        "_provider_for_model",
        lambda provider_name: FakeAssistRegistrationProvider(),
    )

    session = client.post(
        f"/api/v1/images/{image_id}/assist-sessions",
        json={"model_id": model["id"], "device": "cpu"},
    )
    assert session.status_code == 200, session.text
    session_id = session.json()["session_id"]

    brushed = client.post(
        f"/api/v1/assist-sessions/{session_id}/brush",
        json={
            "mode": "add",
            "brush_radius": 8,
            "strokes": [{"points": [{"x": 12, "y": 14}, {"x": 19, "y": 18}]}],
        },
    )
    assert brushed.status_code == 200, brushed.text
    assert brushed.json()["candidate_box"] == {
        "x_min": 8.0,
        "y_min": 6.0,
        "x_max": 26.0,
        "y_max": 24.0,
    }
    assert brushed.json()["candidate_mask_png_base64"] == VALID_ASSIST_MASK_PNG_BASE64

    accepted = client.post(
        f"/api/v1/assist-sessions/{session_id}/accept",
        json={"label_class_id": label_class_id},
    )
    assert accepted.status_code == 200, accepted.text
    annotation = accepted.json()["annotation"]
    assert annotation["source_type"] == "assist_mask"
    assert annotation["source_model_id"] == model["id"]
    assert annotation["provenance_json"]["prompt_type"] == "smart_mask"


def test_assist_box_prompt_accepts_selected_prediction_as_provenance_source(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ModelService,
        "_provider_for_purpose",
        lambda self, purpose: (
            FakeDetectorRegistrationProvider()
            if purpose == "detector"
            else FakeAssistRegistrationProvider()
        ),
    )
    monkeypatch.setattr(
        inference_module,
        "detection_provider_for_name",
        lambda provider_name: FakeDetectorWorkerProvider(),
    )
    monkeypatch.setattr(
        assist_runtime_module,
        "mask_to_png_base64",
        lambda mask: VALID_ASSIST_MASK_PNG_BASE64,
    )

    project = create_project(client)
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    detector = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="fixture-detector.pt",
        display_name="Fixture Detector",
    )
    assist_response = client.post(
        f"/api/v1/projects/{project['id']}/models/register",
        files={
            "file": (
                "sam_vit_b_fixture.pth",
                b"fixture-assist-model",
                "application/octet-stream",
            )
        },
        data={"purpose": "assist", "display_name": "Fixture SAM"},
    )
    assert assist_response.status_code == 200, assist_response.text
    assist_model = cast(dict[str, Any], assist_response.json())

    job = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": detector["id"], "image_ids": [image_id], "device": "cpu"},
    ).json()

    app = cast(FastAPI, client.app)
    monkeypatch.setattr(
        app.state.assist_runtime,
        "_provider_for_model",
        lambda provider_name: FakeAssistRegistrationProvider(),
    )
    assert process_inference_job(app.state.settings, app.state.session_factory, job["id"]) is True
    proposal = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"][0]

    session = client.post(
        f"/api/v1/images/{image_id}/assist-sessions",
        json={
            "model_id": assist_model["id"],
            "device": "cpu",
            "source_prediction_id": proposal["id"],
        },
    )
    assert session.status_code == 200, session.text
    session_id = session.json()["session_id"]
    assert session.json()["source_prediction_id"] == proposal["id"]

    boxed = client.post(
        f"/api/v1/assist-sessions/{session_id}/box",
        json={
            "x_min": proposal["x_min"],
            "y_min": proposal["y_min"],
            "x_max": proposal["x_max"],
            "y_max": proposal["y_max"],
        },
    )
    assert boxed.status_code == 200, boxed.text
    assert boxed.json()["prompt_type"] == "box_to_mask"

    accepted = client.post(
        f"/api/v1/assist-sessions/{session_id}/accept",
        json={"label_class_id": label_class_id},
    )
    assert accepted.status_code == 200, accepted.text
    annotation = accepted.json()["annotation"]
    assert annotation["source_type"] == "assist_mask"
    assert annotation["source_model_id"] == assist_model["id"]
    assert annotation["source_prediction_id"] == proposal["id"]
    assert annotation["provenance_json"]["source_prediction"]["proposal_id"] == proposal["id"]

    refreshed = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"][0]
    assert refreshed["review_status"] == "edited_and_accepted"
    assert refreshed["accepted_annotation_id"] == annotation["id"]
