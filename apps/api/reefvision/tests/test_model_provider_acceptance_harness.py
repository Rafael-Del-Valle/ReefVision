from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = Path(__file__).resolve().parents[4] / "scripts" / "acceptance-model-providers.py"
    spec = importlib.util.spec_from_file_location("acceptance_model_providers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_result_rejects_non_evidence_status(harness) -> None:
    with pytest.raises(ValueError, match="Unsupported acceptance status"):
        harness.result("MAYBE")


def test_verified_catalog_asset_fails_closed_on_checksum_mismatch(harness, tmp_path: Path) -> None:
    checkpoint = tmp_path / "models" / "catalog-models" / "sam2" / "sam2_b.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"real bytes")
    manifest = checkpoint.parents[1] / "manifest.json"
    manifest.write_text(
        '{"assets":{"sam2/image/base":{"relative_path":"models/catalog-models/sam2/sam2_b.pt",'
        '"size_bytes":10,"sha256":"incorrect"}}}',
        encoding="utf-8",
    )
    path, _, error = harness.load_verified_catalog_asset(tmp_path, "sam2/image/base")
    assert path is None
    assert error == "Managed checkpoint SHA-256 does not match its manifest"


def test_depth_acceptance_invariant_is_explicit() -> None:
    source = (
        Path(__file__).resolve().parents[4] / "scripts" / "acceptance-model-providers.py"
    ).read_text(encoding="utf-8")
    assert '"relative_monocular_depth_is_metric": False' in source
