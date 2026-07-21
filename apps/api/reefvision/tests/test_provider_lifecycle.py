from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import ProviderModelAsset
from reefvision.main import create_app
from reefvision.ml.provider_contract import (
    CancellationToken,
    CheckpointKind,
    DeviceMode,
    LifecycleInferenceRequest,
    LifecycleInferenceResult,
    ProviderCancelledError,
    ProviderCapabilities,
    ProviderLifecycleError,
    ProviderModelDefinition,
    ProviderOutOfMemoryError,
    ProviderUnavailableError,
)
from reefvision.ml.provider_lifecycle import (
    ProviderRuntimeManager,
    UltralyticsLifecycleProvider,
)
from reefvision.ml.provider_verification import (
    diagnose_model,
    resolve_device,
    resolve_managed_relative_path,
    verify_checkpoint,
)
from reefvision.storage.catalog_models import manifest_path, write_catalog_manifest_record


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _definition(path: Path, *, model_id: str = "test/model") -> ProviderModelDefinition:
    return ProviderModelDefinition(
        provider_id="fake",
        provider_version="1",
        model_id=model_id,
        architecture="fixture",
        task="detect",
        capabilities=ProviderCapabilities(box_output=True),
        checkpoint_path=path,
        checkpoint_kind=CheckpointKind.FILE,
        checkpoint_sha256=_digest(path.read_bytes()),
        checkpoint_size_bytes=path.stat().st_size,
        checkpoint_format="fixture",
        source="test",
        required_packages=(),
        supported_devices=(DeviceMode.CPU, DeviceMode.CUDA),
        output_types=("box",),
    )


class _FakeProvider:
    provider_id = "fake"

    def __init__(
        self,
        events: list[str],
        *,
        fail_oom: bool = False,
        fail_load: bool = False,
        delay: bool = False,
    ) -> None:
        self.events = events
        self.fail_oom = fail_oom
        self.fail_load = fail_load
        self.delay = delay
        self.model_id: str | None = None
        self.device: str | None = None

    def load(self, model: ProviderModelDefinition, device: str) -> None:
        if self.fail_load:
            raise ProviderLifecycleError("simulated provider load failure")
        self.model_id = model.model_id
        self.device = device
        self.events.append(f"load:{model.model_id}:{device}")

    def health_check(self) -> dict[str, Any]:
        return {"loaded": self.model_id is not None}

    def infer(
        self,
        model: ProviderModelDefinition,
        request: LifecycleInferenceRequest,
        cancellation: CancellationToken,
    ) -> LifecycleInferenceResult:
        self.events.append(f"infer:{model.model_id}")
        if self.fail_oom:
            raise ProviderOutOfMemoryError("simulated OOM")
        if self.delay:
            for _ in range(100):
                time.sleep(0.002)
                cancellation.raise_if_cancelled()
        return LifecycleInferenceResult(
            request_id=request.request_id,
            provider_id="fake",
            model_id=model.model_id,
            task=model.task,
            resolved_device=self.device or "cpu",
            outputs=[],
            metadata={"empty_result": True},
        )

    def cancel(self, request_id: str) -> None:
        self.events.append(f"cancel:{request_id}")

    def unload(self) -> None:
        self.events.append(f"unload:{self.model_id}")
        self.model_id = None


def test_file_verification_detects_missing_and_same_size_change(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model-a")
    definition = _definition(checkpoint)

    verified = verify_checkpoint(definition)
    assert verified.verified
    assert verified.status == "verified"

    checkpoint.write_bytes(b"model-b")
    changed = verify_checkpoint(definition)
    assert not changed.verified
    assert changed.status == "checksum_mismatch"
    assert changed.size_bytes == len(b"model-b")

    checkpoint.write_bytes(b"model-a")
    wrong_size = verify_checkpoint(replace(definition, checkpoint_size_bytes=999))
    assert not wrong_size.verified
    assert wrong_size.status == "size_mismatch"
    assert wrong_size.expected_size_bytes == 999
    assert wrong_size.size_bytes == len(b"model-a")

    checkpoint.unlink()
    missing = verify_checkpoint(definition)
    assert not missing.verified
    assert missing.status == "missing"


def test_managed_relative_path_rejects_escape(tmp_path: Path) -> None:
    assert (
        resolve_managed_relative_path(tmp_path, "models/checkpoint.pt")
        == (tmp_path / "models/checkpoint.pt").resolve()
    )
    assert resolve_managed_relative_path(tmp_path, "../outside.pt") is None
    assert (
        resolve_managed_relative_path(tmp_path, str((tmp_path / "absolute.pt").resolve())) is None
    )


def test_missing_dependency_is_diagnostic_not_exception(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"fixture")
    definition = _definition(checkpoint)
    definition = replace(
        definition,
        required_packages=("reefvision-package-that-does-not-exist",),
    )

    result = diagnose_model(definition, "cpu")

    assert not result.ready
    assert result.missing_packages == ("reefvision-package-that-does-not-exist",)
    assert "Missing required" in (result.failure_reason or "")


def test_runtime_unloads_previous_model_and_reloads(tmp_path: Path) -> None:
    first_path = tmp_path / "first.pt"
    second_path = tmp_path / "second.pt"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    first = _definition(first_path, model_id="first")
    second = _definition(second_path, model_id="second")
    events: list[str] = []
    runtime = ProviderRuntimeManager()
    runtime.register_provider("fake", lambda: _FakeProvider(events))

    assert runtime.load(first, "cpu") == "cpu"
    runtime.load(second, "cpu")
    assert "unload:first" in events
    runtime.unload()
    runtime.load(second, "cpu")

    assert events.count("load:second:cpu") == 2
    assert runtime.loaded_model_id == "second"


def test_device_modes_resolve_cpu_auto_and_mocked_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    assert resolve_device("cpu") == "cpu"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("auto") == "cpu"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_device("auto") == "cuda:0"
    assert resolve_device("cuda") == "cuda:0"


def test_duplicate_concurrent_request_id_is_rejected(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    image = tmp_path / "image.png"
    checkpoint.write_bytes(b"fixture")
    image.write_bytes(b"fixture")
    definition = _definition(checkpoint)
    events: list[str] = []
    worker_errors: list[BaseException] = []
    runtime = ProviderRuntimeManager()
    runtime.register_provider("fake", lambda: _FakeProvider(events, delay=True))
    runtime.load(definition, "cpu")

    def run() -> None:
        try:
            runtime.infer(
                definition,
                LifecycleInferenceRequest(request_id="same-request", source_path=image),
            )
        except BaseException as exc:  # test captures a worker-thread cancellation
            worker_errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    for _ in range(100):
        if "infer:test/model" in events:
            break
        time.sleep(0.002)
    with pytest.raises(ProviderLifecycleError, match="Duplicate active request id"):
        runtime.infer(
            definition,
            LifecycleInferenceRequest(request_id="same-request", source_path=image),
        )
    assert runtime.cancel("same-request")
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(worker_errors) == 1
    assert isinstance(worker_errors[0], ProviderCancelledError)


def test_ultralytics_missing_checkpoint_cannot_trigger_download(tmp_path: Path) -> None:
    placeholder = tmp_path / "placeholder.pt"
    placeholder.write_bytes(b"fixture")
    definition = replace(
        _definition(placeholder),
        checkpoint_path=tmp_path / "would-download-by-name.pt",
    )
    provider = UltralyticsLifecycleProvider()

    with pytest.raises(ProviderUnavailableError, match="automatic downloads are disabled"):
        provider.load(definition, "cpu")


def test_runtime_cancellation_is_cooperative(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    image = tmp_path / "image.png"
    checkpoint.write_bytes(b"fixture")
    image.write_bytes(b"fixture")
    definition = _definition(checkpoint)
    events: list[str] = []
    runtime = ProviderRuntimeManager()
    runtime.register_provider("fake", lambda: _FakeProvider(events, delay=True))
    runtime.load(definition, "cpu")
    observed: list[BaseException] = []

    def run() -> None:
        try:
            runtime.infer(
                definition,
                LifecycleInferenceRequest(request_id="cancel-me", source_path=image),
            )
        except BaseException as exc:  # test captures a worker-thread exception
            observed.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    for _ in range(100):
        if "infer:test/model" in events:
            break
        time.sleep(0.002)
    assert runtime.cancel("cancel-me")
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert len(observed) == 1
    assert isinstance(observed[0], ProviderCancelledError)
    assert "cancel:cancel-me" in events


def test_runtime_oom_unloads_model(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    image = tmp_path / "image.png"
    checkpoint.write_bytes(b"fixture")
    image.write_bytes(b"fixture")
    definition = _definition(checkpoint)
    events: list[str] = []
    runtime = ProviderRuntimeManager()
    runtime.register_provider("fake", lambda: _FakeProvider(events, fail_oom=True))
    runtime.load(definition, "cpu")

    with pytest.raises(ProviderOutOfMemoryError, match="simulated OOM"):
        runtime.infer(
            definition,
            LifecycleInferenceRequest(request_id="oom", source_path=image),
        )

    assert runtime.loaded_model_id is None
    assert runtime.state.value == "unloaded"
    assert "unload:test/model" in events


def test_provider_discovery_verifies_manifest_and_detects_duplicates(
    client: TestClient,
    test_settings: Settings,
) -> None:
    settings = test_settings
    root = settings.resolved_data_dir
    first = root / "models" / "catalog-models" / "fixture" / "first.pt"
    second = root / "models" / "catalog-models" / "fixture" / "second.pt"
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(b"same-checkpoint")
    second.write_bytes(b"same-checkpoint")
    for model_id, path in (("fixture/detect/first", first), ("fixture/detect/second", second)):
        write_catalog_manifest_record(
            settings,
            model_id,
            {
                "filename": path.name,
                "relative_path": path.relative_to(root).as_posix(),
                "sha256": _digest(path.read_bytes()),
                "size_bytes": path.stat().st_size,
                "provider_version": "test",
                "source": "test",
            },
        )

    response = client.post("/api/v1/provider-models/discover")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["managed_count"] == 2
    assert payload["verified_count"] == 2
    assert payload["duplicate_checksum_groups"] == [
        ["fixture/detect/first", "fixture/detect/second"]
    ]
    listing = client.get("/api/v1/provider-models?limit=1&offset=1")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert len(listing.json()["items"]) == 1


def test_provider_discovery_reports_unsafe_missing_and_changed_assets(
    client: TestClient,
    test_settings: Settings,
) -> None:
    settings = test_settings
    root = settings.resolved_data_dir
    changed = root / "models" / "catalog-models" / "fixture" / "changed.pt"
    size_mismatch = root / "models" / "catalog-models" / "fixture" / "size.pt"
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_bytes(b"changed")
    size_mismatch.write_bytes(b"valid")
    manifest_path(settings).write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "assets": {
                    "fixture/detect/unsafe": {
                        "filename": "unsafe.pt",
                        "relative_path": "../unsafe.pt",
                        "sha256": _digest(b"unsafe"),
                        "size_bytes": 6,
                    },
                    "fixture/detect/missing": {
                        "filename": "missing.pt",
                        "relative_path": "models/catalog-models/fixture/missing.pt",
                        "sha256": _digest(b"missing"),
                        "size_bytes": 7,
                    },
                    "fixture/detect/changed": {
                        "filename": "changed.pt",
                        "relative_path": changed.relative_to(root).as_posix(),
                        "sha256": _digest(b"same-len"),
                        "size_bytes": changed.stat().st_size,
                    },
                    "fixture/detect/size": {
                        "filename": "size.pt",
                        "relative_path": size_mismatch.relative_to(root).as_posix(),
                        "sha256": _digest(size_mismatch.read_bytes()),
                        "size_bytes": size_mismatch.stat().st_size + 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    response = client.post("/api/v1/provider-models/discover")
    listing = client.get("/api/v1/provider-models?limit=20")

    assert response.status_code == 200, response.text
    by_id = {item["model_id"]: item for item in listing.json()["items"]}
    assert by_id["fixture/detect/unsafe"]["verification"]["status"] == "unsafe_path"
    assert by_id["fixture/detect/missing"]["verification"]["status"] == "missing"
    assert by_id["fixture/detect/changed"]["verification"]["status"] == "checksum_mismatch"
    assert by_id["fixture/detect/size"]["verification"]["status"] == "size_mismatch"
    assert by_id["fixture/detect/size"]["verification"]["expected_size_bytes"] == 6
    assert by_id["fixture/detect/size"]["verification"]["observed_size_bytes"] == 5
    assert all(item["state"] == "unavailable" for item in by_id.values())


def test_external_depth_registration_preserves_path_and_file_checksums(
    client: TestClient,
    tmp_path: Path,
    test_settings: Settings,
) -> None:
    checkpoint = tmp_path / "Depth-Anything-V2-Small-hf"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text('{"model_type":"depth_anything"}', encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"weights")
    (checkpoint / "preprocessor_config.json").write_text("{}", encoding="utf-8")

    response = client.post(
        "/api/v1/provider-models/external",
        json={
            "model_id": "depth-anything-v2-small-external",
            "provider_id": "depth_anything_v2",
            "architecture": "Depth Anything V2 Small",
            "task": "depth",
            "checkpoint_path": str(checkpoint),
            "confirmed": True,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["checkpoint_path"] == str(checkpoint.resolve())
    assert payload["checkpoint_path_kind"] == "trusted_external"
    assert len(payload["file_manifest"]) == 3
    assert payload["metadata"]["copied_into_managed_storage"] is False
    assert checkpoint.is_dir()

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        asset = session.get(ProviderModelAsset, payload["id"])
        assert asset is not None
        asset.state = "loaded"
        session.commit()

    restarted_app = create_app(test_settings)
    with TestClient(restarted_app) as restarted_client:
        listing = restarted_client.get("/api/v1/provider-models?limit=50")
        assert listing.status_code == 200, listing.text
        reopened = next(item for item in listing.json()["items"] if item["id"] == payload["id"])
        assert reopened["state"] == "unloaded"
        assert reopened["checkpoint_path"] == str(checkpoint.resolve())
        assert len(reopened["file_manifest"]) == 3
    restarted_app.state.engine.dispose()


def test_failed_load_health_check_is_persisted(
    client: TestClient,
    test_settings: Settings,
) -> None:
    root = test_settings.resolved_data_dir
    checkpoint = root / "models" / "catalog-models" / "fixture" / "health.pt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(b"health")
    write_catalog_manifest_record(
        test_settings,
        "fixture/detect/health",
        {
            "filename": checkpoint.name,
            "relative_path": checkpoint.relative_to(root).as_posix(),
            "sha256": _digest(checkpoint.read_bytes()),
            "size_bytes": checkpoint.stat().st_size,
            "provider_version": "test",
            "source": "test",
        },
    )
    discovered = client.post("/api/v1/provider-models/discover")
    assert discovered.status_code == 200, discovered.text
    listing = client.get("/api/v1/provider-models?limit=20").json()["items"]
    asset_id = next(item["id"] for item in listing if item["model_id"] == "fixture/detect/health")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        asset = session.get(ProviderModelAsset, asset_id)
        assert asset is not None
        asset.provider_id = "failing"
        asset.required_packages_json = []
        session.commit()
    app.state.provider_runtime.register_provider(
        "failing", lambda: _FakeProvider([], fail_load=True)
    )

    failed = client.post(
        f"/api/v1/provider-models/{asset_id}/health-check",
        json={"device": "cpu", "kind": "load", "keep_loaded": False},
    )
    assert failed.status_code == 422, failed.text
    reopened = client.get(f"/api/v1/provider-models/{asset_id}")
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert body["state"] == "failed"
    assert body["last_health_check"]["healthy"] is False
    assert "simulated provider load failure" in body["last_health_check"]["failure_reason"]
