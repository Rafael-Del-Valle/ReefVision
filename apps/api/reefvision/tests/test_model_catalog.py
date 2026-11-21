from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.ml import provider_hub
from reefvision.services import model_catalog as model_catalog_service
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


def _source_model_catalog_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "config"
        / model_catalog_service.MODEL_CATALOG_FILENAME
    )


def test_source_catalog_is_schema_v2_and_contains_required_models() -> None:
    path = _source_model_catalog_path()
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "model_catalog.json"
    assert payload["schema_version"] == 2
    assert payload["catalog_version"] == model_catalog_service.EXPECTED_MODEL_CATALOG_VERSION
    ids = {entry["catalog_id"] for entry in payload["models"]}
    assert len(ids) == len(payload["models"])
    assert len(ids) >= 43
    assert {
        "ultralytics/yolo11/detect/n",
        "ultralytics/yolo11/detect/s",
        "ultralytics/yolo11/detect/m",
        "ultralytics/yolo11/detect/l",
        "ultralytics/yolo11/detect/x",
        "transformers/grounding_dino/tiny",
        "sam2/image/base",
        "transformers/smolvlm/256m-instruct",
        "transformers/trocr/small-printed",
        "depth-anything/metric-video-depth-anything/small",
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
        "download_source_type",
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

    response = client.get(f"/api/v1/projects/{project['id']}/model-catalog?workflow=model_hub")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["rejected_entries"] == 0
    assert len(payload["models"]) >= 43
    yolo_models = {
        item["catalog_id"]: item
        for item in payload["models"]
        if item["catalog_id"].startswith("ultralytics/yolo11/detect/")
    }
    assert len(yolo_models) == 5
    assert all(item["selection_kind"] == "builtin_architecture" for item in yolo_models.values())
    assert all(not item["expected_files"] for item in yolo_models.values())
    assert all(
        item["installation_state"] in {"Available", "Provider Required"}
        for item in yolo_models.values()
    )


def test_project_catalog_distinguishes_checkpoint_bytes_from_execution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Restored checkpoint catalog")
    app = cast(FastAPI, client.app)
    settings = app.state.settings
    monkeypatch.setattr(provider_hub, "_package_version", lambda _: "2.5.1")
    cases = {
        "supported": ("reefpose", "pose", True, "Ready"),
        "omitted": ("reefpose", "pose", False, "Model Required"),
        "wrong-size": ("reefpose", "pose", True, "Corrupted"),
        "wrong-task": ("reefpose", "detect", True, "Unavailable"),
        "unknown": ("synthetic_old_provider", "detect", True, "Unavailable"),
        "catalog-only": ("rt_detr", "detect", True, "Unavailable"),
        "retired": ("sleap_nn", "pose", True, "Unavailable"),
    }
    ids = {}
    with app.state.session_factory() as session:
        for title, (provider, task, present, _) in cases.items():
            payload = ("Generated checkpoint witness " + title).encode()
            path = f"projects/{project['id']}/models/{title}.pt"
            if present:
                resolved = resolve_managed_project_path(settings, path)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_bytes(payload + b"unexpected" if title == "wrong-size" else payload)
            model = ModelRegistration(
                project_id=project["id"],
                purpose="detector",
                display_name=title,
                source_filename=f"{title}.pt",
                managed_path=path,
                sha256=sha256(payload).hexdigest(),
                file_size_bytes=len(payload),
                framework="pytorch",
                task=task,
                provider_name=provider,
                provider_version="fixture",
                class_map_json={"0": "fixture"},
                metadata_json={"external_model_receipt": "original"},
            )
            session.add(model)
            session.flush()
            ids[title] = model.id
        session.commit()

    endpoint = f"/api/v1/projects/{project['id']}/model-catalog"
    response = client.get(endpoint, params={"workflow": "model_hub"})
    assert response.status_code == 200, response.text
    rows = {entry["resolved_model_id"]: entry for entry in response.json()["models"]}
    for title, (provider, task, present, state) in cases.items():
        model = client.get(f"/api/v1/models/{ids[title]}").raise_for_status().json()
        row = rows[ids[title]]
        assert row["provider_id"] == model["provider_name"] == provider
        assert row["task"] == model["task"] == task
        assert row["expected_checksum"] == model["sha256"]
        assert model["metadata_json"] == {"external_model_receipt": "original"}
        assert row["installation_state"] == state
        assert row["inference_supported"] is (state == "Ready")
        assert row["trainable"] is (state == "Ready")
        matching_file = present and state != "Corrupted"
        assert row["installed_checksum"] == (model["sha256"] if matching_file else None)
        assert row["installed_path"] == (model["managed_path"] if matching_file else None)
    ready_only = client.get(endpoint, params={"include_unavailable": False}).raise_for_status()
    registered = [item for item in ready_only.json()["models"] if item["resolved_model_id"]]
    assert [item["resolved_model_id"] for item in registered] == [ids["supported"]]
    assert "weights" in rows[ids["omitted"]]["installation_reason"].lower()
    assert "size" in rows[ids["wrong-size"]]["installation_reason"].lower()
    assert "retired" in rows[ids["retired"]]["installation_reason"].lower()
    assert "synthetic_old_provider" in rows[ids["unknown"]]["installation_reason"]
    assert "detect" in rows[ids["wrong-task"]]["installation_reason"]


def test_missing_provider_does_not_hide_entries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_catalog_service, "_installed_provider_version", lambda _: None)
    project = create_project(client, "Provider missing")

    response = client.get(f"/api/v1/projects/{project['id']}/model-catalog")

    assert response.status_code == 200, response.text
    payload = response.json()
    yolo11x = next(
        item for item in payload["models"] if item["catalog_id"] == "ultralytics/yolo11/detect/x"
    )
    assert len(payload["models"]) >= 43
    assert yolo11x["installation_state"] == "Provider Required"


def test_smart_mask_catalog_filters_only_by_task(client: TestClient) -> None:
    project = create_project(client, "Mask catalog study")

    response = client.get(f"/api/v1/projects/{project['id']}/model-catalog?workflow=smart_mask")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["models"]
    assert all(item["task"] == "assist_segmentation" for item in payload["models"])


def test_invalid_entry_is_reported_without_rejecting_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = json.loads(_source_model_catalog_path().read_text(encoding="utf-8"))
    source["models"][0].pop("display_name")
    (tmp_path / model_catalog_service.MODEL_CATALOG_FILENAME).write_text(
        json.dumps(source), encoding="utf-8"
    )
    monkeypatch.setenv("REEFVISION_CONFIG_DIR", str(tmp_path))
    model_catalog_service.clear_model_catalog_cache()
    try:
        catalog = model_catalog_service._load_static_model_catalog()
        assert len(catalog.models) == len(source["models"]) - 1
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
        assert detail["catalog_version"] == model_catalog_service.EXPECTED_MODEL_CATALOG_VERSION
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
    endpoint = f"/api/v1/projects/{project['id']}/model-hub/bootstrap"

    baseline_response = client.get(endpoint)
    assert baseline_response.status_code == 200, baseline_response.text
    baseline_payload = baseline_response.json()
    baseline_catalog_ids = {item["catalog_id"] for item in baseline_payload["catalog"]["models"]}
    assert baseline_catalog_ids
    assert any(item["task"] == "semantic_segment" for item in baseline_payload["catalog"]["models"])

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("auxiliary readiness unavailable")

    monkeypatch.setattr("reefvision.services.bootstrap.cached_model_provider_catalog", fail)
    monkeypatch.setattr("reefvision.services.bootstrap.cached_lightweight_provider_preflight", fail)
    monkeypatch.setattr("reefvision.services.bootstrap.cached_runtime_provider_statuses", fail)
    monkeypatch.setattr(
        "reefvision.services.bootstrap.cached_ultralytics_training_registry_summary", fail
    )

    response = client.get(endpoint)

    assert response.status_code == 200, response.text
    payload = response.json()
    degraded_catalog_ids = {item["catalog_id"] for item in payload["catalog"]["models"]}
    assert degraded_catalog_ids == baseline_catalog_ids
    assert len(payload["validation_warnings"]) == (len(baseline_payload["validation_warnings"]) + 4)


def test_all_available_definitions_have_explicit_architecture_or_registration_paths() -> None:
    catalog = model_catalog_service._load_static_model_catalog()
    for entry in catalog.models:
        assert not entry.expected_files
        assert entry.expected_checksum is None
        assert entry.selection_kind in {"builtin_architecture", "model_required"}
        if entry.selection_kind == "builtin_architecture":
            assert entry.architecture_reference
            assert entry.trainable
            assert entry.inference_requires_registered_model
        else:
            assert not entry.trainable


def test_sam2_preserves_native_pinned_provider_route() -> None:
    path = model_catalog_service._resolve_catalog_resource(
        model_catalog_service.MODEL_CATALOG_FILENAME
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    sam2 = next(entry for entry in payload["models"] if entry["catalog_id"] == "sam2/image/base")

    assert sam2["availability"] == "available"
    assert sam2["provider_id"] == "sam2"
    assert sam2["download_source_type"] == "user_registration"
    assert not sam2.get("expected_files")
