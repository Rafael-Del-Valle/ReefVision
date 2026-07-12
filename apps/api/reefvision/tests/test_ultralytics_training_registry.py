from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.ml.dependencies import provider_spec
from reefvision.ml.ultralytics_registry import ultralytics_training_registry


def test_ultralytics_training_registry_detects_pinned_version(
    test_settings: Settings,
) -> None:
    snapshot = ultralytics_training_registry(test_settings)

    assert snapshot.provider_name == "ultralytics"
    assert snapshot.provider_version == provider_spec("ultralytics").provider_version
    assert snapshot.ultralytics_version == provider_spec("ultralytics").provider_version
    assert snapshot.pinned_version_matches_installed is True
    assert "train" in snapshot.method_signatures
    assert "predict" in snapshot.method_signatures


def test_ultralytics_training_registry_exposes_supported_and_unsupported_parameters(
    test_settings: Settings,
) -> None:
    snapshot = ultralytics_training_registry(test_settings)
    record_by_name = {item.name: item for item in snapshot.parameters}

    assert record_by_name["epochs"].reefvision_supported is True
    assert record_by_name["epochs"].tunable is True
    assert record_by_name["overlap_mask"].supported_tasks == ("segment",)
    assert record_by_name["copy_paste_mode"].choices == ("flip", "mixup")
    assert record_by_name["copy_paste_mode"].native_tune_default is False
    assert record_by_name["dropout"].reefvision_supported is False
    assert record_by_name["save"].fixed_only is True


def test_ultralytics_training_registry_endpoint_returns_pinned_snapshot(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/models/ultralytics/training-registry")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider_version"] == provider_spec("ultralytics").provider_version
    assert payload["summary"]["parameter_count"] >= 100
    parameter_names = {item["name"] for item in payload["parameters"]}
    assert {"epochs", "overlap_mask", "copy_paste_mode"} <= parameter_names


def test_ultralytics_training_validation_endpoint_rejects_version_mismatch(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/models/ultralytics/training-registry/validate",
        json={
            "task": "detect",
            "mode": "tune",
            "expected_ultralytics_version": "8.3.999",
            "parameters": {"epochs": 100},
            "search_space": [],
        },
    )

    assert response.status_code == 400, response.text
    assert "Saved configuration version mismatch" in response.json()["detail"]


def test_ultralytics_training_validation_endpoint_rejects_fixed_only_search_space(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/models/ultralytics/training-registry/validate",
        json={
            "task": "detect",
            "mode": "tune",
            "expected_ultralytics_version": provider_spec("ultralytics").provider_version,
            "parameters": {"epochs": 100},
            "search_space": [{"name": "save", "fixed_value": True}],
        },
    )

    assert response.status_code == 400, response.text
    assert "fixed-only" in response.json()["detail"]


def test_ultralytics_training_validation_endpoint_accepts_native_tune_bounds(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/models/ultralytics/training-registry/validate",
        json={
            "task": "detect",
            "mode": "tune",
            "expected_ultralytics_version": provider_spec("ultralytics").provider_version,
            "parameters": {"epochs": 100, "imgsz": 640},
            "search_space": [
                {
                    "name": "lr0",
                    "minimum": 1e-5,
                    "maximum": 0.01,
                    "scale": "log",
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["normalized_mode"] == "train"
    assert payload["validated_parameters"]["epochs"] == 100
    assert payload["validated_search_space"][0]["name"] == "lr0"
