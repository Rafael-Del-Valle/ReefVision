from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reefvision.config import Settings
from reefvision.packaged_provider_acceptance import (
    DETECTION_CATALOG_ID,
    _managed_asset,
)
from reefvision.storage.catalog_models import write_catalog_manifest_record


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'data' / 'reefvision.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )


def test_managed_asset_requires_matching_checksum(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.ensure_directories()
    checkpoint = (
        settings.resolved_data_dir
        / "models"
        / "catalog-models"
        / "ultralytics"
        / "yolo11"
        / "detect"
        / "n"
        / "yolo11n.pt"
    )
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    payload = b"packaged-checkpoint"
    checkpoint.write_bytes(payload)
    relative = checkpoint.relative_to(settings.resolved_data_dir).as_posix()

    write_catalog_manifest_record(
        settings,
        DETECTION_CATALOG_ID,
        {
            "filename": checkpoint.name,
            "relative_path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "files": [
                {
                    "filename": checkpoint.name,
                    "relative_path": relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            ],
        },
    )

    resolved, record = _managed_asset(settings, DETECTION_CATALOG_ID)

    assert resolved == checkpoint.resolve()
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()

    checkpoint.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match=r"size mismatch|checksum mismatch"):
        _managed_asset(settings, DETECTION_CATALOG_ID)


def test_packaged_acceptance_report_filename_is_json() -> None:
    from reefvision.packaged_provider_acceptance import REPORT_FILENAME

    assert REPORT_FILENAME.endswith(".json")
    assert json.loads('{"status":"PASS"}')["status"] == "PASS"


def test_desktop_packaging_requires_compiled_pydantic_core() -> None:
    repo = Path(__file__).resolve().parents[4]
    build_script = (repo / "scripts" / "build-desktop-backend.ps1").read_text(
        encoding="utf-8"
    )
    verifier = (repo / "scripts" / "verify-windows-msi.ps1").read_text(
        encoding="utf-8"
    )

    assert '"pydantic_core"' in build_script
    assert '"pydantic_core._pydantic_core"' in build_script
    assert "_pydantic_core*.pyd" in build_script
    assert "_pydantic_core*.pyd" in verifier

