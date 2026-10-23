import pytest
from fastapi.testclient import TestClient

from reefvision.schemas.training import TrainingProviderArchitectureResponse
from reefvision.services.segmentation_training import SegmentationTrainingService
from reefvision.services.training import TrainingService, _ultralytics_architecture_available
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_training_workspace import (
    _patch_training_foundation,
    _seed_training_dataset,
)


def test_scaled_yolo_catalog_architectures_match_base_ultralytics_yaml() -> None:
    available = {"yolo11.yaml", "yolov8.yaml"}

    for family in ("yolo11", "yolov8"):
        for scale in "nslmx":
            assert _ultralytics_architecture_available(
                f"{family}{scale}.yaml",
                available,
            )


def test_exact_ultralytics_architecture_name_still_matches() -> None:
    assert _ultralytics_architecture_available(
        "yolo11.yaml",
        {"yolo11.yaml"},
    )


def test_segmentation_preflight_accepts_scaled_catalog_architecture_from_base_yaml(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Scaled segmentation architecture")
    monkeypatch.setattr(
        SegmentationTrainingService,
        "_cached_ultralytics_segment_architectures",
        lambda self: [
            TrainingProviderArchitectureResponse(
                architecture_id="yolo11-seg.yaml",
                display_name="yolo11-seg",
                task="segment",
                source="11/yolo11-seg.yaml",
            )
        ],
    )

    response = client.post(
        f"/api/v1/projects/{project['id']}/training-preflight",
        json={
            "name": "YOLO11 nano segmentation",
            "task": "segment",
            "provider_id": "ultralytics",
            "architecture": "yolo11n-seg.yaml",
            "initial_checkpoint_source": "scratch",
        },
    )

    assert response.status_code == 200, response.text
    assert not any(
        "segmentation architecture is not available" in blocker
        for blocker in response.json()["blockers"]
    )


def test_unknown_ultralytics_architecture_remains_unavailable() -> None:
    assert not _ultralytics_architecture_available(
        "yolo99n.yaml",
        {"yolo11.yaml", "yolov8.yaml"},
    )


@pytest.mark.parametrize(
    ("requested", "installed"),
    [
        ("yolov8n-p2.yaml", "yolov8-p2.yaml"),
        ("yolov8x-ghost.yaml", "yolov8-ghost.yaml"),
        ("yolov8s-ghost-p6.yaml", "yolov8-ghost-p6.yaml"),
        ("yolov8m-p6.yaml", "yolov8-p6.yaml"),
        ("yolov8n6.yaml", "yolov8-p6.yaml"),
        ("yolov5x6.yaml", "yolov5-p6.yaml"),
        ("yolov9t.yaml", "yolov9t.yaml"),
        ("yolov10b.yaml", "yolov10b.yaml"),
        ("yolo12n.yaml", "yolo12.yaml"),
    ],
)
def test_pinned_loader_filename_variants(requested: str, installed: str) -> None:
    assert _ultralytics_architecture_available(requested, {installed})


@pytest.mark.parametrize(
    "requested",
    ["yolov8n-p7.yaml", "yolov8n-seg.yaml", "yolo13n.yaml", "yolo11z.yaml"],
)
def test_variants_must_have_the_matching_installed_definition(requested: str) -> None:
    assert not _ultralytics_architecture_available(requested, {"yolov8.yaml", "yolo11.yaml"})


def test_run_creation_rechecks_architecture_when_saved_preflight_was_ready(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    project, version = _seed_training_dataset(client)
    endpoint = f"/api/v1/projects/{project['id']}"
    response = client.post(
        f"{endpoint}/training-drafts",
        json={
            "name": "Previously ready draft",
            "dataset_version_id": version["id"],
            "architecture": "yolo11n.yaml",
            "provider_id": "ultralytics",
            "task": "detect",
            "initial_checkpoint_source": "scratch",
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["validation_state"]["status"] != "blocked"

    monkeypatch.setattr(
        TrainingService, "_cached_ultralytics_detect_architectures", lambda self: []
    )
    response = client.post(f"{endpoint}/training-runs", json={"draft_id": draft["id"]})
    assert response.status_code == 400, response.text
    assert "architecture is not available" in response.text
    assert client.get(f"{endpoint}/training-runs").json() == []
