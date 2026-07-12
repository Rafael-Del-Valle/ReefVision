from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefvision.services import model_catalog as model_catalog_service
from reefvision.tests.test_annotations import create_project


def test_source_catalog_is_schema_v2_and_contains_required_models() -> None:
    path = model_catalog_service._resolve_catalog_resource(
        model_catalog_service.MODEL_CATALOG_FILENAME
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "model_catalog.json"
    assert payload["schema_version"] == 2
    assert payload["catalog_version"] == "2.0.0"
    assert len(payload["models"]) == 40
    ids = {entry["catalog_id"] for entry in payload["models"]}
    assert len(ids) == 40
    assert {
        "ultralytics/yolo11/detect/n",
        "ultralytics/yolo11/detect/s",
        "ultralytics/yolo11/detect/m",
        "ultralytics/yolo11/detect/l",
        "ultralytics/yolo11/detect/x",
    } <= ids
    required = {
        "catalog_id",
        "display_name",
        "provider_id",
        "architecture",
        "variant",
        "task",
        "trainable",
        "inference_supported",
        "checkpoint_identifier",
        "download_source_type",
        "expected_files",
        "expected_size",
        "license_summary",
        "provider_pack_id",
        "recommended_ram",
        "recommended_vram",
        "supported_devices",
        "supported_runtimes",
        "desktop_support",
        "availability",
    }
    assert all(required <= set(entry) for entry in payload["models"])


def test_project_model_catalog_returns_all_definitions(client: TestClient) -> None:
    project = create_project(client, "Catalog study")

    response = client.get(
        f"/api/v1/projects/{project['id']}/model-catalog?workflow=model_hub"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["rejected_entries"] == 0
    assert len(payload["models"]) == 40
    yolo_models = {
        item["catalog_id"]: item
        for item in payload["models"]
        if item["catalog_id"].startswith("ultralytics/yolo11/detect/")
    }
    assert len(yolo_models) == 5
    assert all(item["selection_kind"] == "managed_catalog_model" for item in yolo_models.values())
    assert all(item["expected_files"] for item in yolo_models.values())
    assert all(
        item["installation_state"] in {"Not Installed", "Provider Required"}
        for item in yolo_models.values()
    )


def test_missing_provider_does_not_hide_entries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_catalog_service, "_installed_provider_version", lambda _: None)
    project = create_project(client, "Provider missing")

    response = client.get(f"/api/v1/projects/{project['id']}/model-catalog")

    assert response.status_code == 200, response.text
    payload = response.json()
    yolo11x = next(
        item
        for item in payload["models"]
        if item["catalog_id"] == "ultralytics/yolo11/detect/x"
    )
    assert len(payload["models"]) == 40
    assert yolo11x["installation_state"] == "Provider Required"


def test_smart_mask_catalog_filters_only_by_task(client: TestClient) -> None:
    project = create_project(client, "Mask catalog study")

    response = client.get(
        f"/api/v1/projects/{project['id']}/model-catalog?workflow=smart_mask"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["models"]
    assert all(item["task"] == "assist_segmentation" for item in payload["models"])


def test_invalid_entry_is_reported_without_rejecting_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = json.loads(
        model_catalog_service._resolve_catalog_resource(
            model_catalog_service.MODEL_CATALOG_FILENAME
        ).read_text(encoding="utf-8")
    )
    source["models"][0].pop("display_name")
    (tmp_path / model_catalog_service.MODEL_CATALOG_FILENAME).write_text(
        json.dumps(source), encoding="utf-8"
    )
    monkeypatch.setenv("REEFVISION_CONFIG_DIR", str(tmp_path))
    model_catalog_service.clear_model_catalog_cache()
    try:
        catalog = model_catalog_service._load_static_model_catalog()
        assert len(catalog.models) == 39
        assert catalog.rejected_entries == 1
        assert catalog.validation_warnings
    finally:
        model_catalog_service.clear_model_catalog_cache()


def test_missing_catalog_returns_structured_error(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Missing catalog")
    monkeypatch.setattr(
        model_catalog_service,
        "_catalog_resource_candidates",
        lambda filename: [tmp_path / filename],
    )
    model_catalog_service.clear_model_catalog_cache()
    try:
        response = client.get(f"/api/v1/projects/{project['id']}/model-catalog")
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["error"] == "catalog_resource_error"
        assert detail["expected_path"].endswith("model_catalog.json")
        assert detail["execution_mode"]
        assert detail["application_version"]
        assert detail["catalog_version"] == "2.0.0"
        assert detail["recovery_action"]
    finally:
        model_catalog_service.clear_model_catalog_cache()


def test_static_catalog_prefers_frozen_bundle_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_config_dir = tmp_path / "config"
    bundle_config_dir.mkdir(parents=True)
    source_path = model_catalog_service._resolve_catalog_resource(
        model_catalog_service.MODEL_CATALOG_FILENAME
    )
    (bundle_config_dir / model_catalog_service.MODEL_CATALOG_FILENAME).write_text(
        source_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    tracker_path = model_catalog_service._resolve_catalog_resource(
        model_catalog_service.TRACKER_CATALOG_FILENAME
    )
    (bundle_config_dir / model_catalog_service.TRACKER_CATALOG_FILENAME).write_text(
        tracker_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    model_catalog_service.clear_model_catalog_cache()
    try:
        catalog = model_catalog_service._load_static_model_catalog()
        assert catalog.models
        assert catalog.source_path == str(
            bundle_config_dir / model_catalog_service.MODEL_CATALOG_FILENAME
        )
        assert model_catalog_service._load_static_tracker_catalog().trackers
    finally:
        model_catalog_service.clear_model_catalog_cache()
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_catalog_endpoint_does_not_import_heavy_ml_libraries(client: TestClient) -> None:
    project = create_project(client, "Lightweight catalog")
    heavy = {"torch", "ultralytics", "transformers", "tensorrt", "segment_anything"}
    before = {name for name in heavy if name in sys.modules}

    response = client.get(f"/api/v1/projects/{project['id']}/model-catalog")

    assert response.status_code == 200
    after = {name for name in heavy if name in sys.modules}
    assert after == before


def test_bootstrap_auxiliary_failure_keeps_catalog_visible(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Isolated bootstrap")

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("auxiliary readiness unavailable")

    monkeypatch.setattr("reefvision.services.bootstrap.cached_model_provider_catalog", fail)
    monkeypatch.setattr("reefvision.services.bootstrap.cached_lightweight_provider_preflight", fail)
    monkeypatch.setattr("reefvision.services.bootstrap.cached_runtime_provider_statuses", fail)
    monkeypatch.setattr(
        "reefvision.services.bootstrap.cached_ultralytics_training_registry_summary", fail
    )

    response = client.get(f"/api/v1/projects/{project['id']}/model-hub/bootstrap")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["catalog"]["models"]) == 40
    assert len(payload["validation_warnings"]) == 4
