from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_hub import _sleap_nn_descriptor, provider_for_registration
from reefvision.ml.video_tracking import video_tracking_provider_for_name
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.pose_interoperability import PoseInteroperabilityFormat
from reefvision.schemas.pose_training_datasets import PoseTrainingExportFormat
from reefvision.services.workflow_pose import _EXTERNAL_POSE_EXPORT_FORMATS
from reefvision.storage.pose_exchange import load_exchange, save_exchange

ROOT = Path(__file__).resolve().parents[4]
RETIREMENT_TEXT = "retired pending an authoritative SLEAP-NN license resolution"


def test_sleap_nn_catalog_entry_is_fail_closed_and_not_registerable() -> None:
    descriptor = _sleap_nn_descriptor()

    assert descriptor.availability_status == "retired_license_audit"
    assert descriptor.registerable is False
    assert descriptor.supported_tasks == ()
    assert descriptor.supported_execution_runtimes == ()
    assert descriptor.capabilities.multi_object_tracking is False
    assert descriptor.capabilities.cpu_inference is False
    assert descriptor.capabilities.cuda_inference is False
    assert descriptor.availability_reason == RETIREMENT_TEXT


@pytest.mark.parametrize(
    "factory",
    [
        lambda: provider_for_registration("detector", provider_name="sleap_nn"),
        lambda: video_tracking_provider_for_name("sleap_nn"),
    ],
)
def test_sleap_nn_factories_reject_active_execution(factory: object) -> None:
    with pytest.raises(ValidationError, match=RETIREMENT_TEXT):
        factory()  # type: ignore[operator]


def test_supported_pose_formats_exclude_slp_but_keep_neutral_interchange() -> None:
    interoperability_formats = set(get_args(PoseInteroperabilityFormat))
    training_formats = set(get_args(PoseTrainingExportFormat))

    assert "slp" not in interoperability_formats
    assert "slp" not in training_formats
    assert {"nwb", "coco", "dlc_csv", "ultralytics_pose"} <= interoperability_formats
    assert {"nwb", "coco", "dlc_csv", "ultralytics_pose"} <= training_formats
    assert "slp" not in _EXTERNAL_POSE_EXPORT_FORMATS


def test_supported_distribution_does_not_package_sleap_nn() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = list(project["project"]["dependencies"])
    for extra in project["project"]["optional-dependencies"].values():
        dependencies.extend(extra)

    assert not any(item.casefold().startswith("sleap-nn") for item in dependencies)
    assert project["project"]["optional-dependencies"]["interoperability"] == ["sleap-io==0.9.2"]


def test_legacy_slp_storage_helpers_fail_closed() -> None:
    with pytest.raises(ValidationError, match="Unsupported pose interoperability format: slp"):
        load_exchange(object(), b"historical", "historical.slp", "slp")
    with pytest.raises(ValidationError, match="Unsupported pose interoperability format: slp"):
        save_exchange(object(), object(), "historical", "slp")


def test_historical_sleap_model_metadata_remains_readable() -> None:
    created_at = datetime(2026, 1, 2, tzinfo=UTC)
    historical = ModelRegistrationResponse.model_validate(
        {
            "id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-000000000002",
            "purpose": "detector",
            "display_name": "Historical animal pose model",
            "source_filename": "historical-sleap.zip",
            "managed_path": "projects/example/models/historical-sleap.zip",
            "sha256": "a" * 64,
            "file_size_bytes": 42,
            "framework": "sleap_nn",
            "task": "pose",
            "provider_name": "sleap_nn",
            "provider_version": "0.3.3",
            "class_map_json": {},
            "input_size_json": None,
            "metadata_json": {
                "provider_state": "unavailable",
                "retirement_reason": RETIREMENT_TEXT,
            },
            "notes": "Preserved historical registration; execution unavailable.",
            "created_at": created_at,
            "updated_at": created_at,
        }
    )

    assert historical.provider_name == "sleap_nn"
    assert historical.metadata_json["provider_state"] == "unavailable"
    assert historical.metadata_json["retirement_reason"] == RETIREMENT_TEXT
