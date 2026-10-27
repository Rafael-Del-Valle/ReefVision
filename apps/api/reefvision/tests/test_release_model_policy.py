"""Release gates exercise real staged files without using researcher data."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_script(filename: str) -> ModuleType:
    scripts = Path(__file__).resolve().parents[4] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), scripts / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "catalog_version": "test",
                "models": [
                    {
                        "catalog_id": "ultralytics/yolo11/pose/n",
                        "selection_kind": "architecture",
                        "architecture_id": "yolo11n-pose.yaml",
                        "expected_files": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_staging_creates_empty_manifest_and_never_connects(
    catalog: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Weight-free staging attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    stager = load_script("stage-bundled-models.py")
    destination = tmp_path / "fresh"
    manifest = stager.stage_models(catalog, destination)
    assert manifest["assets"] == {}
    assert manifest["provider_assets"] == {}
    assert manifest["asset_count"] == manifest["provider_asset_count"] == 0
    assert manifest["total_size_bytes"] == 0
    assert manifest["model_policy"] == "architecture_first_no_pretrained_weights"
    assert list(destination.iterdir()) == [destination / "manifest.json"]


@pytest.mark.parametrize(
    "suffix", [".pt", ".pth", ".ckpt", ".safetensors", ".engine", ".onnx", ".bin", ".h5"]
)
def test_staging_refuses_existing_weights_without_deleting(
    catalog: Path, tmp_path: Path, suffix: str
) -> None:
    stager = load_script("stage-bundled-models.py")
    destination = tmp_path / "existing"
    weight = destination / "nested" / f"researcher{suffix}"
    weight.parent.mkdir(parents=True)
    weight.write_bytes(b"preserve this model")
    with pytest.raises(RuntimeError, match=r"weight|asset"):
        stager.stage_models(catalog, destination)
    assert weight.read_bytes() == b"preserve this model"
    assert not (destination / "manifest.json").exists()


def test_release_audit_allows_architecture_yaml(catalog: Path, tmp_path: Path) -> None:
    audit = load_script("audit-model-downloadability.py")
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "architecture.yaml").write_text("nc: 1\n", encoding="utf-8")
    audit.audit(catalog, bundle_roots=[root])


@pytest.mark.parametrize(
    "mutation",
    [
        {"source_url": "https://example.invalid/weights.pt"},
        {"expected_files": [{"filename": "weights.pt"}]},
        {"desktop_package_status": "optional_network_download"},
        {"selection_kind": "managed_catalog_model"},
        {"auto_download": True},
        {"architecture_id": "yolo11n.pt"},
    ],
)
def test_release_audit_rejects_catalog_acquisition(
    catalog: Path, mutation: dict[str, object]
) -> None:
    audit = load_script("audit-model-downloadability.py")
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["models"][0].update(mutation)
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"catalog|Catalog"):
        audit.audit(catalog)


def test_release_audit_rejects_nested_weights_and_nonempty_manifest(
    catalog: Path, tmp_path: Path
) -> None:
    audit = load_script("audit-model-downloadability.py")
    root = tmp_path / "bundle"
    (root / "nested").mkdir(parents=True)
    weight = root / "nested" / "MODEL.PT"
    weight.write_bytes(b"model")
    with pytest.raises(RuntimeError, match=r"MODEL\.PT"):
        audit.audit(catalog, bundle_roots=[root])
    weight.unlink()
    (root / "manifest.json").write_text(json.dumps({"assets": {"hidden": {}}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="manifest"):
        audit.audit(catalog, bundle_roots=[root])


def test_legacy_assistant_flag_fails_without_mutation(catalog: Path, tmp_path: Path) -> None:
    stager = load_script("stage-bundled-models.py")
    destination = tmp_path / "bundle"
    with pytest.raises(RuntimeError, match="pretrained"):
        stager.stage_models(catalog, destination, include_base_assistant=True)
    assert not destination.exists()


def test_runtime_audit_distinguishes_package_data_and_model_assets(
    catalog: Path, tmp_path: Path
) -> None:
    audit = load_script("audit-model-downloadability.py")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "locale.dat").write_bytes(b"not a model")
    audit.audit(catalog, runtime_roots=[runtime])
    model = runtime / "provider-models" / "nested" / "model.bin"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")
    with pytest.raises(RuntimeError, match=r"model\.bin"):
        audit.audit(catalog, runtime_roots=[runtime])


def test_runtime_nonmodel_exception_requires_exact_content(catalog: Path, tmp_path: Path) -> None:
    audit = load_script("audit-model-downloadability.py")
    root = tmp_path / "runtime"
    impostor = root / "sentencepiece" / "package_data" / "nfkc.bin"
    impostor.parent.mkdir(parents=True)
    impostor.write_bytes(b"weights hidden under a permitted filename")
    with pytest.raises(RuntimeError, match=r"nfkc\.bin"):
        audit.audit(catalog, runtime_roots=[root])


def test_release_version_checker_rejects_disagreement(tmp_path: Path) -> None:
    import shutil

    checker = load_script("check-release-version.py")
    root = Path(__file__).resolve().parents[4]
    versions = checker.check_versions(root)
    assert set(versions.values()) == {checker.EXPECTED_VERSION}
    for relative in (
        "package.json",
        "pyproject.toml",
        "apps/web/package.json",
        "apps/web/package-lock.json",
        "apps/web/src-tauri/Cargo.toml",
        "apps/web/src-tauri/Cargo.lock",
        "apps/web/src-tauri/tauri.conf.json",
        "apps/api/reefvision/__init__.py",
        "scripts/lib/reefvision-commands.ps1",
        "apps/web/src/App.tsx",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, destination)
    package = tmp_path / "package.json"
    payload = json.loads(package.read_text(encoding="utf-8"))
    payload["version"] = "1.0.99"
    package.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"package\.json.*1\.0\.99"):
        checker.check_versions(tmp_path)
