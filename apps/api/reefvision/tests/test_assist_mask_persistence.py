from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.ml.assist_runtime import AssistRuntime, AssistSessionState
from reefvision.ml.providers import PixelBox
from reefvision.schemas.assist import AssistAcceptRequest
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
            {"prompt_type": "smart_mask", "accepted_at": datetime.now(UTC).isoformat()},
        )

    def delete_session(self, session_id: str) -> None:
        self.deleted_session_ids.append(session_id)


def test_prompt_assist_acceptance_persists_box_and_raster_mask(client: TestClient) -> None:
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

    content_response = client.get(
        f"/api/v1/mask-annotations/{response.mask_annotation.id}/content"
    )
    assert content_response.status_code == 200
    assert content_response.headers["content-type"].startswith("image/png")
    assert content_response.content.startswith(b"\x89PNG\r\n\x1a\n")
