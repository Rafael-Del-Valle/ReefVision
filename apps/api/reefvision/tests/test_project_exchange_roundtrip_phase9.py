from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import MaskAnnotation, ProjectExchangePackage
from reefvision.jobs.project_exchange import process_project_exchange_export_job
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


class _FakeAssistRuntime:
    def __init__(self, state: AssistSessionState) -> None:
        self.state = state

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
        assert session_id == self.state.session_id


def _persist_raster_assist_mask(
    client: TestClient,
    *,
    project_id: str,
    image_id: str,
    label_class_id: str,
) -> tuple[str, dict[str, object]]:
    now = datetime.now(UTC)
    state = AssistSessionState(
        session_id="exchange-assist-session",
        project_id=project_id,
        image_id=image_id,
        model_id="exchange-assist-model",
        model_display_name="Exchange assist model",
        model_checksum="a" * 64,
        provider_name="test",
        provider_version="1",
        prepared_cache_key="exchange-cache",
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(minutes=5),
        candidate_mask_png_base64=_mask_png_base64((80, 60)),
    )
    runtime = _FakeAssistRuntime(state)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        accepted = AssistService(
            session,
            app.state.settings,
            cast(AssistRuntime, runtime),
        ).accept(
            state.session_id,
            AssistAcceptRequest(label_class_id=label_class_id),
        )
        assert accepted.mask_annotation is not None
        mask_id = accepted.mask_annotation.id
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        return mask_id, dict(mask.measurement_json or {})


def test_project_exchange_true_round_trip_preserves_media_masks_and_measurements(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Round trip source")
    imported = import_one(
        client,
        project["id"],
        filename="roundtrip.png",
        relative_path="study/roundtrip.png",
        size=(80, 60),
    )
    image_id = str(imported["successful"][0]["image_id"])
    label_class_id = str(project["label_classes"][0]["id"])
    original_image = client.get(f"/api/v1/images/{image_id}/content")
    assert original_image.status_code == 200

    mask_id, source_measurements = _persist_raster_assist_mask(
        client,
        project_id=project["id"],
        image_id=image_id,
        label_class_id=label_class_id,
    )
    source_mask_content = client.get(f"/api/v1/mask-annotations/{mask_id}/content")
    assert source_mask_content.status_code == 200
    source_annotations = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert len(source_annotations["annotations"]) == 1
    assert len(source_annotations["mask_annotations"]) == 1

    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": True,
            "notes": "full round-trip acceptance",
        },
    )
    assert created.status_code == 202, created.text
    created_payload = created.json()
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        created_payload["job_id"],
    )

    package = client.get(
        f"/api/v1/exchange-packages/{created_payload['package']['id']}"
    ).json()
    assert package["status"] == "complete"
    assert package["manifest_json"]["import_policy"]["mode"] == "create_new_project"
    media_kinds = {item["kind"] for item in package["manifest_json"]["media"]}
    assert {"image", "mask"}.issubset(media_kinds)
    archive_path = test_settings.resolved_data_dir / Path(package["archive_path"])
    archive_bytes = archive_path.read_bytes()

    imported_exchange = client.post(
        "/api/v1/exchange-packages/import",
        data={"project_name": "Round trip restored"},
        files={
            "file": (
                "roundtrip.reefvision.zip",
                archive_bytes,
                "application/zip",
            )
        },
    )
    assert imported_exchange.status_code == 201, imported_exchange.text
    result = imported_exchange.json()
    restored_project_id = str(result["project_id"])
    assert restored_project_id != project["id"]
    assert result["project_name"] == "Round trip restored"
    assert result["restored_file_count"] >= 2
    assert result["remapped_id_count"] >= 4

    restored_page = client.get(
        f"/api/v1/projects/{restored_project_id}/images?page=1&page_size=100"
    )
    assert restored_page.status_code == 200, restored_page.text
    restored_images = restored_page.json()["items"]
    assert len(restored_images) == 1
    restored_image = restored_images[0]
    restored_image_id = str(restored_image["id"])
    assert restored_image_id != image_id
    assert restored_image["original_filename"] == "roundtrip.png"
    assert restored_image["relative_path"] == "study/roundtrip.png"

    reopened_image = client.get(f"/api/v1/images/{restored_image_id}/content")
    assert reopened_image.status_code == 200
    assert reopened_image.content == original_image.content

    restored_annotations_response = client.get(
        f"/api/v1/images/{restored_image_id}/annotations"
    )
    assert restored_annotations_response.status_code == 200, restored_annotations_response.text
    restored_annotations = restored_annotations_response.json()
    assert len(restored_annotations["annotations"]) == 1
    assert len(restored_annotations["mask_annotations"]) == 1
    restored_mask = restored_annotations["mask_annotations"][0]
    restored_mask_id = str(restored_mask["id"])
    assert restored_mask_id != mask_id
    assert restored_mask["geometry_kind"] == "raster_mask"
    assert restored_mask["area_pixels"] == 100

    reopened_mask = client.get(f"/api/v1/mask-annotations/{restored_mask_id}/content")
    assert reopened_mask.status_code == 200
    assert reopened_mask.content == source_mask_content.content

    with app.state.session_factory() as session:
        restored_mask_record = session.get(MaskAnnotation, restored_mask_id)
        assert restored_mask_record is not None
        assert dict(restored_mask_record.measurement_json or {}) == source_measurements
        assert restored_mask_record.image_id == restored_image_id
        imported_package = session.scalar(
            select(ProjectExchangePackage).where(
                ProjectExchangePackage.id == result["package_id"]
            )
        )
        assert imported_package is not None
        assert imported_package.direction == "import"
        assert imported_package.project_id == restored_project_id

    source_page = client.get(
        f"/api/v1/projects/{project['id']}/images?page=1&page_size=100"
    ).json()
    assert len(source_page["items"]) == 1
    assert source_page["items"][0]["id"] == image_id


def test_project_exchange_import_rejects_missing_required_media_without_partial_project(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Metadata-only source")
    import_one(client, project["id"], filename="needs-media.png")
    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={"include_media": False},
    ).json()
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        created["job_id"],
    )
    package = client.get(
        f"/api/v1/exchange-packages/{created['package']['id']}"
    ).json()
    archive_path = test_settings.resolved_data_dir / Path(package["archive_path"])

    before = client.get("/api/v1/projects").json()
    response = client.post(
        "/api/v1/exchange-packages/import",
        data={"project_name": "Should not survive"},
        files={"file": ("metadata.zip", archive_path.read_bytes(), "application/zip")},
    )
    assert response.status_code == 400
    assert "original image media" in response.json()["detail"].lower()
    after = client.get("/api/v1/projects").json()
    assert len(after) == len(before)
