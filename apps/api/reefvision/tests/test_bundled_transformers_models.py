"""Tests for verified Transformers snapshots and catalog inference registration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from reefvision.db.models import ImageAsset, Job, ModelRegistration, Project
from reefvision.ml.transformers_provider import inspect_transformers_model
from reefvision.services import bundled_transformers_models
from reefvision.services.catalog_inference import (
    CatalogInferenceJobCreateRequest,
    CatalogInferenceService,
)

CATALOG_ID = "transformers/grounding_dino/tiny"
PROVIDER_ID = "grounding_dino"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _snapshot_digest(files: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(files, key=lambda item: str(item["relative_path"])):
        digest.update(str(record["relative_path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(int(record["size_bytes"])).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _write_bundle(root: Path) -> tuple[Path, dict[str, object]]:
    model_root = root.joinpath(*CATALOG_ID.split("/"))
    model_root.mkdir(parents=True)
    (model_root / "config.json").write_text(
        json.dumps(
            {
                "model_type": "grounding-dino",
                "architectures": ["GroundingDinoForObjectDetection"],
            }
        ),
        encoding="utf-8",
    )
    (model_root / "model.safetensors").write_bytes(b"tiny-test-weights")
    files: list[dict[str, object]] = []
    for path in sorted(item for item in model_root.rglob("*") if item.is_file()):
        files.append(
            {
                "relative_path": path.relative_to(model_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    snapshot_sha256 = _snapshot_digest(files)
    record: dict[str, object] = {
        "catalog_id": CATALOG_ID,
        "repo_id": "test/grounding-dino-tiny",
        "requested_revision": "main",
        "resolved_revision": "a" * 40,
        "provider_id": PROVIDER_ID,
        "relative_path": CATALOG_ID,
        "file_count": len(files),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in files),
        "snapshot_sha256": snapshot_sha256,
        "files": files,
    }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 2,
                "pack_id": "transformers-vision",
                "model_count": 1,
                "models": {CATALOG_ID: record},
                "total_size_bytes": record["total_size_bytes"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return model_root, record


def test_startup_seeding_verifies_and_repairs_every_file(
    client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    source_root, record = _write_bundle(bundle_root)
    monkeypatch.setenv("REEFVISION_BUNDLED_TRANSFORMERS_MODELS_DIR", str(bundle_root))

    installed, warnings = bundled_transformers_models.install_bundled_transformers_models(
        client.app.state.settings
    )

    assert warnings == []
    assert set(installed) == {CATALOG_ID}
    destination = installed[CATALOG_ID]
    assert (destination / "model.safetensors").read_bytes() == b"tiny-test-weights"
    installed_record = bundled_transformers_models.bundled_transformers_model_record(
        client.app.state.settings,
        CATALOG_ID,
    )
    assert installed_record is not None
    assert installed_record["snapshot_sha256"] == record["snapshot_sha256"]
    assert installed_record["verified"] is True

    (destination / "model.safetensors").write_bytes(b"corrupt")
    repaired, repair_warnings = bundled_transformers_models.install_bundled_transformers_models(
        client.app.state.settings
    )
    assert repair_warnings == []
    assert (
        repaired[CATALOG_ID].joinpath("model.safetensors").read_bytes()
        == (source_root / "model.safetensors").read_bytes()
    )


def test_corrupt_bundled_source_is_not_installed(
    client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "corrupt-bundle"
    source_root, _record = _write_bundle(bundle_root)
    (source_root / "model.safetensors").write_bytes(b"changed-after-manifest")
    monkeypatch.setenv("REEFVISION_BUNDLED_TRANSFORMERS_MODELS_DIR", str(bundle_root))

    installed, warnings = bundled_transformers_models.install_bundled_transformers_models(
        client.app.state.settings
    )

    assert installed == {}
    assert any("failed verification" in warning and "mismatch" in warning for warning in warnings)


def test_verified_pointer_resolves_to_managed_snapshot(
    client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "pointer-bundle"
    _write_bundle(bundle_root)
    monkeypatch.setenv("REEFVISION_BUNDLED_TRANSFORMERS_MODELS_DIR", str(bundle_root))
    installed, warnings = bundled_transformers_models.install_bundled_transformers_models(
        client.app.state.settings
    )
    assert warnings == []
    record = bundled_transformers_models.bundled_transformers_model_record(
        client.app.state.settings,
        CATALOG_ID,
    )
    assert record is not None

    pointer = tmp_path / "model.transformers.json"
    pointer.write_text(
        json.dumps(
            {
                "format": "reefvision_transformers_model_pointer_v1",
                "catalog_id": CATALOG_ID,
                "provider_id": PROVIDER_ID,
                "model_path": str(installed[CATALOG_ID]),
                "resolved_revision": record["resolved_revision"],
                "snapshot_sha256": record["snapshot_sha256"],
            }
        ),
        encoding="utf-8",
    )
    spec = inspect_transformers_model(pointer)
    assert spec.provider_name == PROVIDER_ID

    payload = json.loads(pointer.read_text(encoding="utf-8"))
    payload["snapshot_sha256"] = "0" * 64
    pointer.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="checksum does not match"):
        inspect_transformers_model(pointer)


def test_catalog_inference_creates_project_pointer_registration_and_job(
    client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "inference-bundle"
    _write_bundle(bundle_root)
    monkeypatch.setenv("REEFVISION_BUNDLED_TRANSFORMERS_MODELS_DIR", str(bundle_root))
    installed, warnings = bundled_transformers_models.install_bundled_transformers_models(
        client.app.state.settings
    )
    assert warnings == []
    assert CATALOG_ID in installed

    project_id = "11111111-1111-1111-1111-111111111111"
    image_id = "22222222-2222-2222-2222-222222222222"
    project_root = "projects/catalog-inference-test"
    image_relative = f"{project_root}/images/test.png"
    image_path = client.app.state.settings.resolved_data_dir / image_relative
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"image-placeholder")

    with client.app.state.session_factory() as session:
        session.add(
            Project(
                id=project_id,
                name="Catalog inference",
                slug="catalog-inference",
                storage_root=project_root,
            )
        )
        session.add(
            ImageAsset(
                id=image_id,
                project_id=project_id,
                original_filename="test.png",
                managed_path=image_relative,
                sha256="b" * 64,
                width_px=64,
                height_px=64,
                file_size_bytes=image_path.stat().st_size,
                media_type="image/png",
            )
        )
        session.commit()

        service = CatalogInferenceService(session, client.app.state.settings)
        monkeypatch.setattr(
            service.catalog,
            "get_project_catalog_item",
            lambda _project_id, _catalog_id: SimpleNamespace(
                installation_state="Ready",
                installation_reason=None,
                provider_id=PROVIDER_ID,
                provider=PROVIDER_ID,
                provider_version="1.0",
                display_name="Grounding DINO Tiny",
            ),
        )
        response = service.create_job(
            project_id,
            CatalogInferenceJobCreateRequest(
                catalog_id=CATALOG_ID,
                image_ids=[image_id],
                text_prompt="coral polyp, fish",
                confidence_threshold=0.3,
                device="cpu",
            ),
        )
        model = session.scalar(
            select(ModelRegistration).where(ModelRegistration.project_id == project_id)
        )
        job = session.get(Job, response.id)

        assert model is not None
        assert model.provider_name == PROVIDER_ID
        assert model.managed_path.endswith(".transformers.json")
        pointer_path = client.app.state.settings.resolved_data_dir / model.managed_path
        assert inspect_transformers_model(pointer_path).provider_name == PROVIDER_ID
        assert job is not None
        assert job.request_json["text_prompt"] == "coral polyp, fish"
        assert job.request_json["model_id"] == model.id
        assert job.progress_total == 1
