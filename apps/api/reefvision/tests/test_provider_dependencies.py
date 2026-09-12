import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import reefvision.api.routes.models as models_route_module
import reefvision.ml.provider_hub as provider_hub_module
from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import (
    ProviderPackageStatus,
    ProviderPreflightReport,
    configure_provider_runtime,
    provider_spec,
)
from reefvision.ml.provider_hub import get_model_provider
from reefvision.ml.providers import UltralyticsDetectionProvider


def test_provider_plots_render_headlessly_in_worker_thread(tmp_path: Path) -> None:
    script = """
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from reefvision.ml.dependencies import configure_provider_runtime
configure_provider_runtime(data_dir=Path(sys.argv[1]))
def plot():
    import matplotlib
    import matplotlib.pyplot as plt
    assert matplotlib.get_backend().lower() == 'agg'
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    fig.savefig(Path(sys.argv[1]) / 'headless.png')
    plt.close(fig)
with ThreadPoolExecutor(max_workers=1) as pool:
    pool.submit(plot).result()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "MPLBACKEND": "TkAgg"},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "headless.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_configure_provider_runtime_uses_research_data_dir(tmp_path: Path) -> None:
    previous_autoinstall = os.environ.get("YOLO_AUTOINSTALL")
    previous_config_dir = os.environ.get("YOLO_CONFIG_DIR")
    try:
        settings = Settings(data_dir=tmp_path / "reefvision-data")
        runtime_dir = configure_provider_runtime(settings)

        assert runtime_dir == settings.resolved_data_dir / "provider-runtime"
        assert runtime_dir.is_dir()
        assert os.environ["YOLO_AUTOINSTALL"] == "false"
        assert Path(os.environ["YOLO_CONFIG_DIR"]).resolve() == runtime_dir.resolve()
    finally:
        if previous_autoinstall is None:
            os.environ.pop("YOLO_AUTOINSTALL", None)
        else:
            os.environ["YOLO_AUTOINSTALL"] = previous_autoinstall
        if previous_config_dir is None:
            os.environ.pop("YOLO_CONFIG_DIR", None)
        else:
            os.environ["YOLO_CONFIG_DIR"] = previous_config_dir


def test_ultralytics_provider_rejects_missing_checkpoints_before_import(tmp_path: Path) -> None:
    provider = UltralyticsDetectionProvider()

    missing_checkpoint = tmp_path / "yolo11n.pt"

    try:
        provider.inspect_model(missing_checkpoint)
    except ValidationError as exc:
        assert "Automatic model downloads are disabled" in str(exc)
    else:  # pragma: no cover - the provider must reject a missing checkpoint
        raise AssertionError("Expected a missing checkpoint validation error")


def test_ultralytics_provider_spec_pins_lap_for_tracking_runtime() -> None:
    pinned_versions = {
        requirement.distribution_name: requirement.required_version
        for requirement in provider_spec("ultralytics").packages
    }

    assert pinned_versions["lap"] == "0.5.13"


def test_provider_preflight_endpoint_returns_serialized_provider_statuses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = ProviderPreflightReport(
        provider_name="ultralytics",
        display_name="Ultralytics detector",
        purpose="detector",
        provider_version="8.3.228",
        tested_python="3.12.x",
        current_python="3.12.7",
        tested_platform="Windows AMD64",
        current_platform="Windows AMD64",
        tested_cuda="12.1",
        current_cuda="12.1",
        automatic_downloads_disabled=True,
        explicit_checkpoint_required=True,
        requirements_file="requirements/providers-windows-cu121-py312.txt",
        package_statuses=(
            ProviderPackageStatus(
                distribution_name="ultralytics",
                required_version="8.3.228",
                installed_version="8.3.228",
                status="ok",
            ),
        ),
        issues=(),
    )
    monkeypatch.setattr(
        models_route_module,
        "cached_lightweight_provider_preflight",
        lambda settings, refresh=False: SimpleNamespace(value=[fake_report]),
    )

    response = client.get("/api/v1/models/provider-preflight")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["providers"][0]["provider_name"] == "ultralytics"
    assert payload["providers"][0]["ready"] is True
    assert payload["providers"][0]["packages"][0]["distribution_name"] == "ultralytics"


def test_model_provider_hub_reports_explicit_capabilities_and_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_reports = [
        ProviderPreflightReport(
            provider_name="ultralytics",
            display_name="Ultralytics detector",
            purpose="detector",
            provider_version="8.3.228",
            tested_python="3.12.x",
            current_python="3.12.7",
            tested_platform="Windows AMD64",
            current_platform="Windows AMD64",
            tested_cuda="12.1",
            current_cuda="12.1",
            automatic_downloads_disabled=True,
            explicit_checkpoint_required=True,
            requirements_file="requirements/providers-windows-cu121-py312.txt",
            package_statuses=(),
            issues=(),
        ),
        ProviderPreflightReport(
            provider_name="segment_anything",
            display_name="Segment Anything assist",
            purpose="assist",
            provider_version="1.0",
            tested_python="3.12.x",
            current_python="3.12.7",
            tested_platform="Windows AMD64",
            current_platform="Windows AMD64",
            tested_cuda="12.1",
            current_cuda="12.1",
            automatic_downloads_disabled=True,
            explicit_checkpoint_required=True,
            requirements_file="requirements/providers-windows-cu121-py312.txt",
            package_statuses=(),
            issues=(),
        ),
    ]
    monkeypatch.setattr(
        provider_hub_module,
        "cached_lightweight_provider_preflight",
        lambda settings=None, refresh=False: SimpleNamespace(
            value=fake_reports,
            checked_at="2026-07-11T00:00:00Z",
            stale=False,
            error=None,
        ),
    )

    ultralytics = get_model_provider("ultralytics")
    assert ultralytics.provider_id == "ultralytics"
    assert ultralytics.capabilities.image_detection is True
    assert ultralytics.capabilities.training is True
    assert ultralytics.registerable is True

    grounding_dino = get_model_provider("grounding_dino")
    assert grounding_dino.availability_status == "not_implemented"
    assert grounding_dino.capabilities.text_prompt_detection is True
    assert grounding_dino.registerable is False


def test_runtime_provider_status_route_serializes_runtime_backends(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        models_route_module,
        "cached_runtime_provider_statuses",
        lambda refresh=False: SimpleNamespace(
            value=[
                provider_hub_module.RuntimeProviderStatus(
                    runtime_id="pytorch",
                    display_name="PyTorch",
                    package_name="torch",
                    package_version="2.5.1+cu121",
                    available=True,
                    status="ready",
                    supports_cpu=True,
                    supports_cuda=True,
                    notes=("Reference runtime.",),
                )
            ]
        ),
    )

    response = client.get("/api/v1/runtime-providers/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload[0]["runtime_id"] == "pytorch"
    assert payload[0]["available"] is True
    assert payload[0]["notes"] == ["Reference runtime."]
