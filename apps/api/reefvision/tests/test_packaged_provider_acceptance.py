from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reefvision.packaged_provider_acceptance import _explicit_local_asset


def test_explicit_acceptance_model_requires_matching_checksum(tmp_path: Path) -> None:
    checkpoint = tmp_path / "researcher.pt"
    payload = b"researcher-supplied-checkpoint"
    checkpoint.write_bytes(payload)
    record = {
        "path": str(checkpoint),
        "files": [
            {
                "path": str(checkpoint),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        ],
    }
    resolved, provenance = _explicit_local_asset({"detection": record}, "detection")
    assert resolved == checkpoint.resolve()
    assert provenance == record
    checkpoint.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match=r"size mismatch|checksum mismatch"):
        _explicit_local_asset({"detection": record}, "detection")
    assert checkpoint.read_bytes() == b"tampered"


def test_acceptance_never_falls_back_to_managed_or_bundled_assets(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="explicit local"):
        _explicit_local_asset({}, "detection")
    with pytest.raises(RuntimeError, match="missing"):
        _explicit_local_asset(
            {"detection": {"path": str(tmp_path / "missing.pt"), "files": []}}, "detection"
        )


def test_acceptance_refuses_unverified_file_and_directory_escape(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"local")
    with pytest.raises(RuntimeError, match="checksum manifest"):
        _explicit_local_asset({"detection": {"path": str(checkpoint), "files": []}}, "detection")
    model_dir = tmp_path / "depth"
    model_dir.mkdir()
    record = {
        "path": str(model_dir),
        "files": [
            {
                "path": str(checkpoint),
                "sha256": hashlib.sha256(b"local").hexdigest(),
                "size_bytes": 5,
            }
        ],
    }
    with pytest.raises(RuntimeError, match="outside"):
        _explicit_local_asset({"depth": record}, "depth")


def test_packaged_acceptance_report_filename_is_json() -> None:
    from reefvision.packaged_provider_acceptance import REPORT_FILENAME

    assert REPORT_FILENAME.endswith(".json")
    assert json.loads('{"status":"PASS"}')["status"] == "PASS"


def test_packaged_provider_execution_blocks_network() -> None:
    import socket

    from reefvision.packaged_provider_acceptance import _timed_run

    def attempted_download() -> dict[str, object]:
        socket.create_connection(("example.invalid", 443))
        return {}

    result = _timed_run("cpu", attempted_download)
    assert result["status"] == "FAIL"
    assert result["failure_message"] == "Acceptance network blocked"


def test_optional_depth_reports_model_required_without_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import torch

    from reefvision import packaged_provider_acceptance as acceptance
    from reefvision.config import Settings

    checkpoint = tmp_path / "researcher.pt"
    checkpoint.write_bytes(b"explicit input fixture")
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "models": {
                    "detection": {
                        "path": str(checkpoint),
                        "files": [
                            {
                                "path": str(checkpoint),
                                "size_bytes": checkpoint.stat().st_size,
                                "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("REEFVISION_ACCEPTANCE_MODEL_MANIFEST", str(manifest))
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    def detection(path: Path, image: Path, device: str) -> dict[str, object]:
        assert path == checkpoint and image.exists() and device == "cpu"
        return {"status": "PASS", "device_actually_used": "cpu"}

    def unexpected_depth(*args: object) -> dict[str, object]:
        pytest.fail("Optional depth model must not be loaded or acquired when absent")

    monkeypatch.setattr(acceptance, "_detection_run", detection)
    monkeypatch.setattr(acceptance, "_depth_run", unexpected_depth)
    settings = Settings(env="test", data_dir=tmp_path / "fresh-profile")
    assert acceptance.run_packaged_provider_acceptance(settings) == 0
    report = json.loads((settings.resolved_data_dir / acceptance.REPORT_FILENAME).read_text())
    assert report["optional_depth_tested"] is False
    assert report["results"]["depth_anything_v2_cpu"]["status"] == "MODEL_REQUIRED"
    assert "depth_anything_v2_cpu" not in report["required_results"]
    assert report["model_inputs"]["detection"]["path"] == str(checkpoint)
    assert not list(settings.resolved_data_dir.rglob("*.pt"))


def test_desktop_packaging_requires_compiled_pydantic_core() -> None:
    repo = Path(__file__).resolve().parents[4]
    build_script = (repo / "scripts" / "build-desktop-backend.ps1").read_text(encoding="utf-8")
    verifier = (repo / "scripts" / "verify-windows-msi.ps1").read_text(encoding="utf-8")

    assert '"pydantic_core"' in build_script
    assert '"pydantic_core._pydantic_core"' in build_script
    assert "_pydantic_core*.pyd" in build_script
    assert "_pydantic_core*.pyd" in verifier
