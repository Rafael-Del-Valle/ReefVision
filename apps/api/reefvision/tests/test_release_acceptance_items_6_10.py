from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from PIL import Image

import reefvision.ml.semantic_segmentation as semantic_module
import reefvision.services.scale_label_ocr as ocr_module
from reefvision.ml.semantic_segmentation import (
    NnUNetV2Provider,
    SemanticClassDefinition,
    SemanticDatasetContract,
    SemanticTrainingRequest,
)
from reefvision.ml.task_registry import TASKS
from reefvision.schemas.image_calibration import CalibrationRoi
from reefvision.schemas.scale_label_ocr import ScaleLabelOcrRequest
from reefvision.services.scale_label_ocr import ScaleLabelOcrService
from reefvision.tests.test_annotations import create_project, import_one


class _FakePixelValues:
    def to(self, _device: str) -> _FakePixelValues:
        return self


class _FakeProcessor:
    @classmethod
    def from_pretrained(
        cls,
        model_path: Path,
        *,
        local_files_only: bool,
    ) -> _FakeProcessor:
        assert Path(model_path).is_dir()
        assert local_files_only is True
        return cls()

    def __call__(self, *, images: Image.Image, return_tensors: str) -> Any:
        assert images.width > 0
        assert images.height > 0
        assert return_tensors == "pt"
        return types.SimpleNamespace(pixel_values=_FakePixelValues())

    def batch_decode(
        self,
        _sequences: object,
        *,
        skip_special_tokens: bool,
    ) -> list[str]:
        assert skip_special_tokens is True
        return ["Scale 10 mm"]


class _FakeTrocrModel:
    @classmethod
    def from_pretrained(
        cls,
        model_path: Path,
        *,
        local_files_only: bool,
    ) -> _FakeTrocrModel:
        assert Path(model_path).is_dir()
        assert local_files_only is True
        return cls()

    def to(self, _device: str) -> _FakeTrocrModel:
        return self

    def eval(self) -> _FakeTrocrModel:
        return self

    def generate(self, _pixel_values: object, **kwargs: object) -> Any:
        assert kwargs["max_new_tokens"] == 24
        assert kwargs["return_dict_in_generate"] is True
        assert kwargs["output_scores"] is True
        return types.SimpleNamespace(sequences=[[1, 2, 3]], scores=[])


class _NoGrad:
    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> bool:
        del exc_type, exc, traceback
        return False


def test_trocr_reuses_model_hub_checkpoint_without_implicit_download(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "TrOCR acceptance")
    imported = import_one(client, str(project["id"]), size=(120, 80))
    image_id = str(imported["successful"][0]["image_id"])
    model_path = tmp_path / "trocr-model"
    model_path.mkdir()

    ensure_calls: list[tuple[str, bool]] = []

    def fake_ensure(
        _settings: object,
        provider_id: str,
        *,
        allow_download: bool,
        progress_callback: object = None,
    ) -> Path:
        del progress_callback
        ensure_calls.append((provider_id, allow_download))
        return model_path

    fake_torch = types.ModuleType("torch")
    fake_torch.no_grad = lambda: _NoGrad()  # type: ignore[attr-defined]
    fake_transformers = types.ModuleType("transformers")
    fake_transformers.TrOCRProcessor = _FakeProcessor  # type: ignore[attr-defined]
    fake_transformers.VisionEncoderDecoderModel = _FakeTrocrModel  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setattr(ocr_module, "ensure_optional_model", fake_ensure)
    monkeypatch.setattr(ocr_module, "resolve_torch_device", lambda _device: "cpu")

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        candidate = ScaleLabelOcrService(
            session,
            app.state.settings,
        ).detect(
            image_id,
            ScaleLabelOcrRequest(
                roi=CalibrationRoi(
                    x_min=0,
                    y_min=0,
                    x_max=120,
                    y_max=80,
                ),
                allow_model_download=False,
            ),
        )

    assert ensure_calls == [("scale_label_ocr", False)]
    assert candidate.raw_text == "Scale 10 mm"
    assert candidate.parsed_value == pytest.approx(10.0)
    assert candidate.normalized_unit == "mm"
    assert candidate.requires_researcher_confirmation is True
    assert candidate.model_revision
    assert any("advisory" in warning.casefold() for warning in candidate.warnings)


def _semantic_dataset(tmp_path: Path) -> SemanticDatasetContract:
    root = tmp_path / "semantic-export"
    images_root = root / "images"
    masks_root = root / "masks"
    for split in ("train", "validation", "test"):
        (images_root / split).mkdir(parents=True, exist_ok=True)
        (masks_root / split).mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (12, 8), (15, 30, 45)).save(images_root / "train" / "train.png")
    train_mask = Image.new("L", (12, 8), 0)
    train_mask.putpixel((4, 3), 1)
    train_mask.save(masks_root / "train" / "train.png")

    Image.new("RGB", (12, 8), (45, 30, 15)).save(images_root / "validation" / "validation.png")
    validation_mask = Image.new("L", (12, 8), 0)
    validation_mask.putpixel((5, 4), 1)
    validation_mask.save(masks_root / "validation" / "validation.png")

    classes_file = root / "classes.json"
    classes_file.write_text(
        json.dumps(
            {
                "background_pixel_value": 0,
                "overlap_policy": "higher class index overwrites lower class index",
                "classes": [
                    {
                        "class_index": 0,
                        "pixel_value": 1,
                        "name": "soft coral",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    return SemanticDatasetContract(
        dataset_version_id="dataset-version-1",
        dataset_manifest_sha256="1" * 64,
        split_manifest_sha256="2" * 64,
        export_root=root,
        images_root=images_root,
        masks_root=masks_root,
        classes_file=classes_file,
        classes=(
            SemanticClassDefinition(
                class_index=0,
                pixel_value=1,
                class_name="soft coral",
            ),
        ),
        background_pixel_value=0,
        overlap_policy="higher class index overwrites lower class index",
    )


def test_nnunet_train_package_predict_lifecycle_is_release_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _semantic_dataset(tmp_path)
    command_names = {
        "nnUNetv2_plan_and_preprocess",
        "nnUNetv2_train",
        "nnUNetv2_predict",
    }

    monkeypatch.setattr(semantic_module, "_nnunet_version", lambda: "2.test")
    monkeypatch.setattr(
        semantic_module,
        "nnunet_dependency_status",
        lambda: {
            "provider_name": "nnunet",
            "provider_version": "2.test",
            "ready": True,
            "status": "ready",
            "issues": [],
        },
    )
    monkeypatch.setattr(
        semantic_module,
        "_command_path",
        lambda name: Path(f"/fake/{name}") if name in command_names else None,
    )

    calls: list[str] = []

    def fake_run_command(
        command: list[str],
        *,
        env: dict[str, str],
        log_path: Path | None,
        cwd: Path,
    ) -> None:
        del log_path, cwd
        name = Path(command[0]).name
        calls.append(name)

        if name == "nnUNetv2_predict":
            dataset_name = command[command.index("-d") + 1]
            assert dataset_name
            output_root = Path(command[command.index("-o") + 1])
            output_root.mkdir(parents=True, exist_ok=True)
            prediction = Image.new("L", (12, 8), 0)
            prediction.putpixel((4, 3), 1)
            prediction.save(output_root / "reefvision.png")
            return

        raw_root = Path(env["nnUNet_raw"])
        dataset_name = next(
            candidate.name for candidate in raw_root.iterdir() if candidate.is_dir()
        )

        if name == "nnUNetv2_plan_and_preprocess":
            (Path(env["nnUNet_preprocessed"]) / dataset_name).mkdir(
                parents=True,
                exist_ok=True,
            )
            return

        if name == "nnUNetv2_train":
            configuration = command[2]
            fold = command[3]
            trainer = command[command.index("-tr") + 1]
            plans = command[command.index("-p") + 1]
            fold_root = (
                Path(env["nnUNet_results"])
                / dataset_name
                / f"{trainer}__{plans}__{configuration}"
                / f"fold_{fold}"
            )
            fold_root.mkdir(parents=True, exist_ok=True)
            (fold_root / "checkpoint_final.pth").write_bytes(b"checkpoint")
            validation_root = fold_root / "validation"
            validation_root.mkdir()
            (validation_root / "summary.json").write_text(
                json.dumps({"foreground_mean": {"Dice": 0.8}}),
                encoding="utf-8",
            )
            return

        raise AssertionError(f"Unexpected nnU-Net command: {name}")

    monkeypatch.setattr(semantic_module, "_run_command", fake_run_command)

    provider = NnUNetV2Provider()
    request = SemanticTrainingRequest(
        run_id="release-acceptance-run",
        project_id="project-1",
        dataset=dataset,
        device="cpu",
        precision="fp32",
        random_seed=42,
        training_config={"epochs": 50},
        resource_limits={"max_workers": 2},
        workspace_root=tmp_path / "nnunet-workspace",
    )

    result = provider.train(request)
    assert result.checkpoint_path.is_file()
    assert result.checkpoint_path.suffix == ".zip"
    assert result.provider_version == "2.test"
    assert result.metrics["semantic/foreground_dice"] == pytest.approx(0.8)
    assert result.artifact_manifest["train_case_count"] == 1
    assert result.artifact_manifest["validation_case_count"] == 1
    assert len(str(result.artifact_manifest["bundle_sha256"])) == 64

    with zipfile.ZipFile(result.checkpoint_path) as archive:
        names = set(archive.namelist())
        assert "reefvision-semantic-model.json" in names
        metadata = json.loads(archive.read("reefvision-semantic-model.json").decode("utf-8"))
        assert metadata["format"] == "reefvision_nnunet_v2"
        assert metadata["configuration"] == "2d"
        assert metadata["classes"][0]["class_name"] == "soft coral"
        assert any(name.endswith("checkpoint_final.pth") for name in names)

    source_image = dataset.images_root / "train" / "train.png"
    prediction_path = provider.predict(
        result.checkpoint_path,
        source_image,
        device="cpu",
    )
    assert prediction_path.is_file()
    with Image.open(prediction_path) as predicted:
        predicted.load()
        assert predicted.size == (12, 8)
        assert predicted.convert("L").getpixel((4, 3)) == 1

    assert calls == [
        "nnUNetv2_plan_and_preprocess",
        "nnUNetv2_train",
        "nnUNetv2_predict",
    ]


def test_semantic_segmentation_capability_registry_is_ready() -> None:
    semantic = next(item for item in TASKS if item.task_id == "semantic_segment")
    assert semantic.state == "ready"
    assert semantic.supports_training is True
    assert semantic.supports_inference is True
