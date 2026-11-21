from __future__ import annotations

import io
import json
import tomllib
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast, get_args
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.ml import sleap_nn_provider, video_tracking
from reefvision.ml.provider_hub import _sleap_nn_descriptor, provider_for_registration
from reefvision.ml.video_tracking import video_tracking_provider_for_name
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.pose_interoperability import PoseInteroperabilityFormat
from reefvision.schemas.pose_training_datasets import PoseTrainingExportFormat
from reefvision.services.workflow_pose import _EXTERNAL_POSE_EXPORT_FORMATS
from reefvision.storage.pose_exchange import load_exchange, save_exchange
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project

ROOT = Path(__file__).resolve().parents[4]
RETIREMENT_TEXT = "retired pending an authoritative SLEAP-NN license resolution"


def test_packaged_compatibility_module_exposes_no_retired_provider_code() -> None:
    public_callables = sorted(
        name
        for name, value in vars(sleap_nn_provider).items()
        if not name.startswith("_")
        and getattr(value, "__module__", None) == sleap_nn_provider.__name__
        and callable(value)
    )
    assert public_callables == []


def test_video_tracking_has_no_retired_provider_adapter() -> None:
    assert not hasattr(video_tracking, "SleapNNVideoTrackingProvider")


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


@pytest.mark.parametrize("provider", ["sleap_nn", "historical_unknown"])
def test_historical_pose_registration_roundtrips_with_opaque_model_bytes(
    client: TestClient,
    provider: str,
) -> None:
    project = create_project(client, "Historical pose records")
    project_id = str(project["id"])
    label = project["label_classes"][0]
    model_id = str(uuid4())
    app = cast(FastAPI, client.app)
    settings = app.state.settings
    bundle = io.BytesIO()
    with ZipFile(bundle, "w") as stored:
        stored.writestr("reefvision-sleap-nn-model.json", '{"format":"reefvision_sleap_nn"}')
        stored.writestr("historical-provenance.txt", "Retained original; generated test fixture.")
    original = bundle.getvalue()
    digest = sha256(original).hexdigest()
    managed_path = f"{project['storage_root']}/models/{model_id}.zip"
    original_path = resolve_managed_project_path(settings, managed_path)
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_bytes(original)
    metadata = {"landmark_labels": ["center", "tip", "tip"], "source": "historical"}
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=project_id,
                purpose="detector",
                display_name="Historical pose bundle",
                source_filename="historical.zip",
                managed_path=managed_path,
                sha256=digest,
                file_size_bytes=len(original),
                framework=provider,
                task="pose",
                provider_name=provider,
                provider_version="0.3.3",
                class_map_json={
                    "labels": [label["name"]],
                    "mapping": {label["name"]: label["id"]},
                },
                metadata_json=metadata,
            )
        )
        session.commit()

    historical = client.get(f"/api/v1/models/{model_id}")
    assert historical.status_code == 200, historical.text
    assert historical.json()["metadata_json"] == metadata

    queued = client.post(
        f"/api/v1/projects/{project_id}/exchange-packages",
        json={"include_model_weights": True, "include_media": False},
    )
    assert queued.status_code == 202, queued.text
    package = queued.json()
    assert process_project_exchange_export_job(
        settings, app.state.session_factory, package["job_id"]
    )
    downloaded = client.get(f"/api/v1/exchange-packages/{package['package']['id']}/download")
    assert downloaded.status_code == 200, downloaded.text
    with ZipFile(io.BytesIO(downloaded.content)) as archive:
        manifest = json.loads(archive.read("reefvision-exchange-manifest.json"))
        [asset] = [item for item in manifest["media"] if item["kind"] == "model"]
        assert asset["record_id"] == model_id
        assert archive.read(asset["path"]) == original

    upload = {"file": ("historical.reefvision.zip", downloaded.content, "application/zip")}
    preview = client.post("/api/v1/exchange-packages/inspect", files=upload)
    assert preview.status_code == 200 and preview.json()["compatible"], preview.text
    restored = client.post("/api/v1/exchange-packages/import", files=upload)
    assert restored.status_code == 201, restored.text
    result = restored.json()
    new_project_id = result["project_id"]
    new_id = result["package"]["options_json"]["id_map"][model_id]
    assert (new_project_id, new_id) != (project_id, model_id)
    reopened = client.get(f"/api/v1/projects/{new_project_id}/models")
    assert reopened.status_code == 200, reopened.text
    [model] = reopened.json()
    assert (model["id"], model["sha256"], model["provider_name"], model["task"]) == (
        new_id,
        digest,
        provider,
        "pose",
    )
    assert model["metadata_json"] == metadata
    assert resolve_managed_project_path(settings, model["managed_path"]).read_bytes() == original

    identical = client.post(
        f"/api/v1/projects/{new_project_id}/models/register",
        files={"file": ("historical.zip", original, "application/zip")},
        data={"purpose": "detector", "provider_name": provider},
    )
    assert identical.status_code == 200 and identical.json() == model, identical.text

    refused = client.post(
        f"/api/v1/projects/{new_project_id}/models/register",
        files={"file": ("new.zip", original + b"different bytes", "application/zip")},
        data={"purpose": "detector", "provider_name": provider},
    )
    assert refused.status_code == 400, refused.text
    expected = RETIREMENT_TEXT if provider == "sleap_nn" else "Unsupported"
    assert expected in refused.json()["detail"]
    assert client.get(f"/api/v1/projects/{new_project_id}/models").json() == [model]
    assert client.get(f"/api/v1/models/{model_id}").json() == historical.json()
    assert original_path.read_bytes() == original
