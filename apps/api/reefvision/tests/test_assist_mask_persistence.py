from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.assist_runtime import AssistRuntime, AssistSessionState
from reefvision.ml.mask_tools import polygon_to_mask
from reefvision.ml.providers import AssistPrediction, PixelBox
from reefvision.schemas.assist import AssistAcceptRequest, AssistAcceptResponse
from reefvision.services.assist import AssistService
from reefvision.tests.test_annotations import create_project, import_one


def _mask_png_base64(size: tuple[int, int]) -> str:
    image = Image.new("L", size, 0)
    for x in range(10, 20):
        for y in range(8, 18):
            image.putpixel((x, y), 160)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


class FakeAssistRuntime:
    def __init__(self, state: AssistSessionState) -> None:
        self.state = state
        self.deleted_session_ids: list[str] = []

    def accept_session(
        self,
        session_id: str,
    ) -> tuple[AssistSessionState, PixelBox, dict[str, object]]:
        assert session_id == self.state.session_id
        return (
            self.state,
            PixelBox(x_min=10, y_min=8, x_max=20, y_max=18),
            {
                "prompt_type": "smart_mask",
                "accepted_at": datetime.now(UTC).isoformat(),
            },
        )

    def delete_session(self, session_id: str) -> None:
        self.deleted_session_ids.append(session_id)


def _polygon_accept_state(
    client: TestClient,
    mask: object,
    *,
    project_name: str,
) -> tuple[dict, str, AssistSessionState, FakeAssistRuntime]:
    project = create_project(client, project_name)
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    now = datetime.now(UTC)
    state = AssistSessionState(
        session_id=f"assist-session-{project_name}",
        project_id=project["id"],
        image_id=image_id,
        model_id="assist-model-1",
        model_display_name="Test assist model",
        model_checksum="a" * 64,
        provider_name="test",
        provider_version="1",
        prepared_cache_key="test-cache",
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(minutes=5),
        candidate_prediction=AssistPrediction(
            mask=mask,
            box=PixelBox(x_min=10, y_min=8, x_max=20, y_max=18),
            score=1.0,
        ),
        candidate_mask_png_base64=_mask_png_base64((80, 60)),
    )
    runtime = FakeAssistRuntime(state)
    return project, image_id, state, runtime


def _accept_polygon(
    client: TestClient,
    project: dict,
    state: AssistSessionState,
    runtime: FakeAssistRuntime,
) -> AssistAcceptResponse:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        return AssistService(
            session,
            app.state.settings,
            cast(AssistRuntime, runtime),
        ).accept(
            state.session_id,
            AssistAcceptRequest(
                label_class_id=project["label_classes"][0]["id"],
                output_kind="polygon",
            ),
        )


def _assert_polygon_rejected(
    client: TestClient,
    mask: object,
    *,
    project_name: str,
    message: str,
) -> None:
    project, image_id, state, runtime = _polygon_accept_state(
        client,
        mask,
        project_name=project_name,
    )
    with pytest.raises(ValidationError, match=message):
        _accept_polygon(client, project, state, runtime)
    assert runtime.deleted_session_ids == []
    payload = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert payload["annotations"] == []
    assert payload["mask_annotations"] == []
    assert payload["image"]["annotation_revision"] == 0


def test_prompt_assist_acceptance_persists_box_and_raster_mask(
    client: TestClient,
) -> None:
    project = create_project(client, "Persist assist mask")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    now = datetime.now(UTC)
    state = AssistSessionState(
        session_id="assist-session-1",
        project_id=project["id"],
        image_id=image_id,
        model_id="assist-model-1",
        model_display_name="Test assist model",
        model_checksum="a" * 64,
        provider_name="test",
        provider_version="1",
        prepared_cache_key="test-cache",
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(minutes=5),
        candidate_mask_png_base64=_mask_png_base64((80, 60)),
    )
    runtime = FakeAssistRuntime(state)

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        response = AssistService(
            session,
            app.state.settings,
            cast(AssistRuntime, runtime),
        ).accept(
            state.session_id,
            AssistAcceptRequest(label_class_id=project["label_classes"][0]["id"]),
        )

    assert response.annotation.source_type == "assist_mask"
    assert response.mask_annotation is not None
    assert response.mask_annotation.geometry_kind == "raster_mask"
    assert response.mask_annotation.area_pixels == 100
    assert response.mask_annotation.mask_path is not None
    assert runtime.deleted_session_ids == [state.session_id]

    session_payload = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert len(session_payload["annotations"]) == 1
    assert len(session_payload["mask_annotations"]) == 1
    assert session_payload["image"]["annotation_revision"] == 1

    content_response = client.get(f"/api/v1/mask-annotations/{response.mask_annotation.id}/content")
    assert content_response.status_code == 200
    assert content_response.headers["content-type"].startswith("image/png")
    assert content_response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_prompt_assist_acceptance_converts_mask_to_editable_polygon(
    client: TestClient,
) -> None:
    mask = np.zeros((60, 80), dtype=np.uint8)
    mask[8:18, 10:20] = 1
    project, _image_id, state, runtime = _polygon_accept_state(
        client,
        mask,
        project_name="Persist assist polygon",
    )
    response = _accept_polygon(client, project, state, runtime)

    assert response.mask_annotation is not None
    assert response.mask_annotation.geometry_kind == "polygon"
    assert response.mask_annotation.mask_path is None
    assert response.mask_annotation.polygon_json is not None
    assert len(response.mask_annotation.polygon_json) >= 4
    rerasterized = polygon_to_mask(
        [tuple(point) for point in response.mask_annotation.polygon_json],
        width=80,
        height=60,
    )
    assert np.array_equal(rerasterized, mask.astype(bool))
    assert response.mask_annotation.area_pixels == int(mask.sum())
    assert response.mask_annotation.provenance_json["polygon_conversion_tolerance_px"] == 1.0
    assert response.mask_annotation.provenance_json["polygon_conversion_iou"] == 1.0
    assert (
        response.mask_annotation.provenance_json["polygon_conversion_max_area_error_fraction"]
        == 0.0
    )


@pytest.mark.parametrize(
    ("mask", "message"),
    [
        (np.ones((59, 80), dtype=np.uint8), "dimensions do not match"),
        (np.ones((60, 80, 1), dtype=np.uint8), "two-dimensional"),
        (np.zeros((60, 80), dtype=np.uint8), "empty"),
    ],
    ids=["wrong-dimensions", "not-two-dimensional", "empty"],
)
def test_prompt_assist_polygon_rejects_invalid_candidate_rasters(
    client: TestClient,
    mask: np.ndarray,
    message: str,
) -> None:
    _assert_polygon_rejected(
        client,
        mask,
        project_name=f"Reject polygon {message}",
        message=message,
    )


def test_prompt_assist_polygon_rejects_disconnected_components(
    client: TestClient,
) -> None:
    mask = np.zeros((60, 80), dtype=np.uint8)
    mask[8:18, 10:20] = 1
    mask[30:35, 40:45] = 1
    _assert_polygon_rejected(
        client,
        mask,
        project_name="Reject disconnected polygon",
        message="holes or disconnected",
    )


def test_prompt_assist_polygon_rejects_holes(client: TestClient) -> None:
    mask = np.zeros((60, 80), dtype=np.uint8)
    mask[8:28, 10:30] = 1
    mask[14:20, 16:24] = 0
    _assert_polygon_rejected(
        client,
        mask,
        project_name="Reject polygon hole",
        message="holes or disconnected",
    )


def test_prompt_assist_polygon_translates_simplification_recursion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mask = np.zeros((60, 80), dtype=np.uint8)
    mask[8:18, 10:20] = 1

    def fail_simplification(*_args: object, **_kwargs: object) -> list[tuple[float, float]]:
        raise RecursionError

    monkeypatch.setattr(
        "reefvision.services.assist.simplify_ring",
        fail_simplification,
    )
    _assert_polygon_rejected(
        client,
        mask,
        project_name="Reject recursive polygon",
        message="too complex to simplify safely",
    )
