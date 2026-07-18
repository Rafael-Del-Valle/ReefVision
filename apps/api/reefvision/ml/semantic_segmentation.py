"""Provider-neutral semantic segmentation with an nnU-Net v2 implementation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from reefvision.domain.errors import ValidationError

SEMANTIC_SEGMENTATION_TASK = "semantic_segment"
NNUNET_PROVIDER_ID = "nnunet"
NNUNET_CONFIGURATION = "2d"
NNUNET_PLANS = "nnUNetPlans"
SUPPORTED_NNUNET_EPOCHS = (1, 5, 10, 20, 50, 100, 250, 500, 750, 2000, 4000, 8000)


@dataclass(frozen=True)
class SemanticClassDefinition:
    class_index: int
    pixel_value: int
    class_name: str


@dataclass(frozen=True)
class SemanticDatasetContract:
    """Immutable indexed-PNG dataset surface consumed by semantic trainers."""

    dataset_version_id: str
    dataset_manifest_sha256: str
    split_manifest_sha256: str
    export_root: Path
    images_root: Path
    masks_root: Path
    classes_file: Path
    classes: tuple[SemanticClassDefinition, ...]
    background_pixel_value: int = 0
    overlap_policy: str = ""

    def validate(self) -> None:
        if not self.dataset_version_id.strip():
            raise ValidationError("Semantic datasets require a dataset version id")
        for value, label in (
            (self.dataset_manifest_sha256, "dataset manifest"),
            (self.split_manifest_sha256, "split manifest"),
        ):
            is_sha256 = len(value) == 64 and all(
                character in "0123456789abcdef" for character in value
            )
            if not is_sha256:
                raise ValidationError(f"Semantic datasets require a lowercase SHA-256 {label}")
        if self.background_pixel_value != 0:
            raise ValidationError("ReefVision semantic-mask background must use pixel value 0")
        if not self.export_root.is_dir():
            raise ValidationError("Semantic dataset export root is missing")
        if not self.images_root.is_dir() or not self.masks_root.is_dir():
            raise ValidationError("Semantic datasets require images and masks directories")
        if not self.classes_file.is_file():
            raise ValidationError("Semantic dataset classes metadata is missing")
        if not self.classes:
            raise ValidationError("Semantic datasets require at least one foreground class")
        class_indices = [item.class_index for item in self.classes]
        if len(class_indices) != len(set(class_indices)):
            raise ValidationError("Semantic class indices must be unique")
        pixel_values = [item.pixel_value for item in self.classes]
        if len(pixel_values) != len(set(pixel_values)):
            raise ValidationError("Semantic class pixel values must be unique")
        if any(value <= 0 or value > 255 for value in pixel_values):
            raise ValidationError("Semantic class pixel values must be between 1 and 255")
        expected_pixels = list(range(1, len(pixel_values) + 1))
        if sorted(pixel_values) != expected_pixels:
            raise ValidationError("nnU-Net semantic class pixel values must be consecutive from 1")


@dataclass(frozen=True)
class SemanticTrainingRequest:
    run_id: str
    project_id: str
    dataset: SemanticDatasetContract
    device: str = "auto"
    precision: str = "fp32"
    random_seed: int | None = None
    training_config: dict[str, Any] = field(default_factory=dict)
    resource_limits: dict[str, Any] = field(default_factory=dict)
    workspace_root: Path | None = None
    log_path: Path | None = None


@dataclass(frozen=True)
class SemanticTrainingResult:
    checkpoint_path: Path
    metrics: dict[str, float]
    metrics_history: dict[str, list[float]]
    artifact_manifest: dict[str, Any]
    provider_version: str


class SemanticSegmentationProvider(Protocol):
    """Modular trainer/inference boundary for indexed semantic masks."""

    provider_id: str
    provider_version: str

    def preflight(
        self,
        request: SemanticTrainingRequest,
    ) -> tuple[list[str], list[str]]: ...

    def train(
        self,
        request: SemanticTrainingRequest,
    ) -> SemanticTrainingResult: ...

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        device: str,
    ) -> Path: ...


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nnunet_version() -> str | None:
    try:
        return version("nnunetv2")
    except PackageNotFoundError:
        return None


def _command_path(name: str) -> Path | None:
    executable = shutil.which(name)
    if executable:
        return Path(executable)
    suffixes = (".exe", "") if os.name == "nt" else ("",)
    for suffix in suffixes:
        candidate = Path(sys.executable).resolve().parent / f"{name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def nnunet_dependency_status() -> dict[str, Any]:
    installed_version = _nnunet_version()
    commands = {
        name: _command_path(name)
        for name in (
            "nnUNetv2_plan_and_preprocess",
            "nnUNetv2_train",
            "nnUNetv2_predict",
        )
    }
    missing_commands = [name for name, path in commands.items() if path is None]
    issues: list[str] = []
    if installed_version is None:
        issues.append("nnunetv2 is not installed; install PyTorch first, then install nnunetv2")
    if missing_commands:
        issues.append("Missing nnU-Net commands: " + ", ".join(missing_commands))
    return {
        "provider_name": NNUNET_PROVIDER_ID,
        "provider_version": installed_version or "not-installed",
        "ready": not issues,
        "status": "ready" if not issues else "missing",
        "issues": issues,
        "commands": {
            name: str(path) if path is not None else None for name, path in commands.items()
        },
    }


def _safe_case_id(split: str, index: int, source: Path) -> str:
    token = "".join(character for character in source.stem if character.isalnum())[:32]
    token = token or "image"
    return f"rv_{split}_{index:05d}_{token}"


def _trainer_for_epochs(epochs: int) -> str:
    if epochs not in SUPPORTED_NNUNET_EPOCHS:
        choices = ", ".join(str(value) for value in SUPPORTED_NNUNET_EPOCHS)
        raise ValidationError(
            f"nnU-Net epochs must use one of the packaged trainer lengths: {choices}"
        )
    return f"nnUNetTrainer_{epochs}epoch" if epochs == 1 else f"nnUNetTrainer_{epochs}epochs"


def _resolved_device(device: str) -> str:
    normalized = device.strip().casefold()
    if normalized in {"cpu", "cuda", "mps"}:
        return normalized
    if normalized not in {"", "auto"}:
        raise ValidationError("nnU-Net device must be auto, cpu, cuda, or mps")
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _append_log(path: Path | None, text: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(text.rstrip() + "\n")


def _run_command(
    command: list[str],
    *,
    env: dict[str, str],
    log_path: Path | None,
    cwd: Path,
) -> None:
    _append_log(log_path, "$ " + subprocess.list2cmdline(command))
    process = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.stdout:
        _append_log(log_path, process.stdout)
    if process.stderr:
        _append_log(log_path, process.stderr)
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "nnU-Net command failed").strip()
        raise ValidationError(detail[-4000:])


def _convert_rgb_png(source: Path, target: Path) -> None:
    try:
        with Image.open(source) as image:
            image.load()
            image.convert("RGB").save(target, format="PNG", optimize=True)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError(
            f"Semantic source image could not be converted: {source.name}"
        ) from exc


def _copy_indexed_mask(source: Path, target: Path) -> None:
    try:
        with Image.open(source) as image:
            image.load()
            image.convert("L").save(target, format="PNG", optimize=True)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError(f"Semantic mask could not be read: {source.name}") from exc


def _materialize_nnunet_dataset(
    contract: SemanticDatasetContract,
    raw_root: Path,
    dataset_name: str,
) -> tuple[list[str], list[str], list[str]]:
    dataset_root = raw_root / dataset_name
    images_tr = dataset_root / "imagesTr"
    labels_tr = dataset_root / "labelsTr"
    images_ts = dataset_root / "imagesTs"
    images_tr.mkdir(parents=True, exist_ok=False)
    labels_tr.mkdir(parents=True, exist_ok=False)
    images_ts.mkdir(parents=True, exist_ok=False)

    train_cases: list[str] = []
    validation_cases: list[str] = []
    test_cases: list[str] = []
    case_index = 0
    for split in ("train", "validation"):
        image_dir = contract.images_root / split
        mask_dir = contract.masks_root / split
        for source_image in sorted(path for path in image_dir.iterdir() if path.is_file()):
            source_mask = mask_dir / f"{source_image.stem}.png"
            if not source_mask.is_file():
                raise ValidationError(
                    f"Semantic mask is missing for exported image {source_image.name}"
                )
            case_id = _safe_case_id(split, case_index, source_image)
            case_index += 1
            _convert_rgb_png(source_image, images_tr / f"{case_id}_0000.png")
            _copy_indexed_mask(source_mask, labels_tr / f"{case_id}.png")
            if split == "train":
                train_cases.append(case_id)
            else:
                validation_cases.append(case_id)

    test_dir = contract.images_root / "test"
    if test_dir.is_dir():
        for source_image in sorted(path for path in test_dir.iterdir() if path.is_file()):
            case_id = _safe_case_id("test", case_index, source_image)
            case_index += 1
            _convert_rgb_png(source_image, images_ts / f"{case_id}_0000.png")
            test_cases.append(case_id)

    if not train_cases:
        raise ValidationError("nnU-Net requires at least one training image with a semantic mask")
    if not validation_cases and len(train_cases) >= 2:
        validation_cases.append(train_cases.pop())

    labels: dict[str, int] = {"background": 0}
    for item in sorted(contract.classes, key=lambda value: value.pixel_value):
        labels[item.class_name] = item.pixel_value
    dataset_json = {
        "channel_names": {"0": "RGB"},
        "labels": labels,
        "numTraining": len(train_cases) + len(validation_cases),
        "file_ending": ".png",
        "overwrite_image_reader_writer": "NaturalImage2DIO",
    }
    (dataset_root / "dataset.json").write_text(
        json.dumps(dataset_json, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return train_cases, validation_cases, test_cases


def _validation_metrics(summary_path: Path) -> dict[str, float]:
    if not summary_path.is_file():
        return {}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    metrics: dict[str, float] = {}
    foreground = payload.get("foreground_mean")
    if isinstance(foreground, dict):
        for key, value in foreground.items():
            if isinstance(value, (int, float)):
                metrics[f"semantic/foreground_{str(key).casefold()}"] = float(value)
    mean = payload.get("mean")
    if isinstance(mean, dict):
        for label, values in mean.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                if isinstance(value, (int, float)):
                    metrics[f"semantic/class_{label}_{str(key).casefold()}"] = float(value)
    return metrics


class NnUNetV2Provider:
    """Run nnU-Net v2 through its supported command-line interface."""

    provider_id = NNUNET_PROVIDER_ID

    @property
    def provider_version(self) -> str:
        return _nnunet_version() or "not-installed"

    def preflight(
        self,
        request: SemanticTrainingRequest,
    ) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []
        try:
            request.dataset.validate()
        except ValidationError as exc:
            blockers.append(str(exc))
        dependency = nnunet_dependency_status()
        blockers.extend(str(item) for item in dependency["issues"])
        epochs = int(request.training_config.get("epochs", 50))
        if epochs not in SUPPORTED_NNUNET_EPOCHS:
            blockers.append(
                "nnU-Net epochs must be one of: "
                + ", ".join(str(value) for value in SUPPORTED_NNUNET_EPOCHS)
            )
        if request.precision == "amp" and _resolved_device(request.device) == "cpu":
            warnings.append("AMP was requested on CPU; nnU-Net will use its CPU execution path")
        if request.workspace_root is None:
            blockers.append("nnU-Net training requires a managed workspace root")
        return blockers, warnings

    def train(
        self,
        request: SemanticTrainingRequest,
    ) -> SemanticTrainingResult:
        blockers, _warnings = self.preflight(request)
        if blockers:
            raise ValidationError("; ".join(blockers))
        if request.workspace_root is None:
            raise ValidationError("nnU-Net training requires a managed workspace root")

        workspace = request.workspace_root.resolve()
        shutil.rmtree(workspace, ignore_errors=True)
        workspace.mkdir(parents=True, exist_ok=False)
        raw_root = workspace / "nnUNet_raw"
        preprocessed_root = workspace / "nnUNet_preprocessed"
        results_root = workspace / "nnUNet_results"
        raw_root.mkdir()
        preprocessed_root.mkdir()
        results_root.mkdir()

        dataset_id = 500 + int(request.dataset.dataset_manifest_sha256[:8], 16) % 500
        dataset_name = f"Dataset{dataset_id:03d}_ReefVision_{request.run_id.replace('-', '')[:12]}"
        train_cases, validation_cases, test_cases = _materialize_nnunet_dataset(
            request.dataset,
            raw_root,
            dataset_name,
        )

        env = dict(os.environ)
        env.update(
            {
                "nnUNet_raw": str(raw_root),
                "nnUNet_preprocessed": str(preprocessed_root),
                "nnUNet_results": str(results_root),
                "nnUNet_n_proc_DA": str(max(1, int(request.resource_limits.get("max_workers", 2)))),
            }
        )
        if request.random_seed is not None:
            env["PYTHONHASHSEED"] = str(request.random_seed)

        plan_command = _command_path("nnUNetv2_plan_and_preprocess")
        train_command = _command_path("nnUNetv2_train")
        if plan_command is None or train_command is None:
            raise ValidationError("nnU-Net command-line tools are unavailable")

        _run_command(
            [
                str(plan_command),
                "-d",
                str(dataset_id),
                "--verify_dataset_integrity",
                "-c",
                NNUNET_CONFIGURATION,
                "--no_pbar",
            ],
            env=env,
            log_path=request.log_path,
            cwd=workspace,
        )

        preprocessed_dataset = preprocessed_root / dataset_name
        fold: str
        if validation_cases:
            splits = [{"train": train_cases, "val": validation_cases}]
            (preprocessed_dataset / "splits_final.json").write_text(
                json.dumps(splits, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            fold = "0"
        else:
            fold = "all"

        epochs = int(request.training_config.get("epochs", 50))
        trainer = _trainer_for_epochs(epochs)
        device = _resolved_device(request.device)
        _run_command(
            [
                str(train_command),
                str(dataset_id),
                NNUNET_CONFIGURATION,
                fold,
                "-tr",
                trainer,
                "-p",
                NNUNET_PLANS,
                "-device",
                device,
            ],
            env=env,
            log_path=request.log_path,
            cwd=workspace,
        )

        configuration_root = (
            results_root / dataset_name / f"{trainer}__{NNUNET_PLANS}__{NNUNET_CONFIGURATION}"
        )
        fold_root = configuration_root / f"fold_{fold}"
        checkpoint = fold_root / "checkpoint_final.pth"
        if not checkpoint.is_file():
            checkpoint = fold_root / "checkpoint_best.pth"
        if not checkpoint.is_file():
            raise ValidationError("nnU-Net completed without a finalized checkpoint")

        summary_path = fold_root / "validation" / "summary.json"
        metrics = _validation_metrics(summary_path)
        bundle_metadata = {
            "format": "reefvision_nnunet_v2",
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "configuration": NNUNET_CONFIGURATION,
            "plans": NNUNET_PLANS,
            "trainer": trainer,
            "fold": fold,
            "checkpoint_name": checkpoint.name,
            "classes": [
                {
                    "class_index": item.class_index,
                    "pixel_value": item.pixel_value,
                    "class_name": item.class_name,
                }
                for item in request.dataset.classes
            ],
        }
        (configuration_root / "reefvision-semantic-model.json").write_text(
            json.dumps(bundle_metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        bundle_path = workspace / "semantic-model.zip"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(configuration_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(configuration_root).as_posix())

        artifacts = {
            **bundle_metadata,
            "workspace_root": str(workspace),
            "raw_dataset_root": str(raw_root / dataset_name),
            "preprocessed_dataset_root": str(preprocessed_dataset),
            "results_configuration_root": str(configuration_root),
            "validation_summary": str(summary_path) if summary_path.is_file() else None,
            "train_case_count": len(train_cases),
            "validation_case_count": len(validation_cases),
            "test_case_count": len(test_cases),
            "bundle_sha256": _file_sha256(bundle_path),
        }
        return SemanticTrainingResult(
            checkpoint_path=bundle_path,
            metrics=metrics,
            metrics_history={key: [value] for key, value in metrics.items()},
            artifact_manifest=artifacts,
            provider_version=self.provider_version,
        )

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        device: str,
    ) -> Path:
        dependency = nnunet_dependency_status()
        if not dependency["ready"]:
            raise ValidationError("; ".join(str(item) for item in dependency["issues"]))
        if not checkpoint_path.is_file() or checkpoint_path.suffix.casefold() != ".zip":
            raise ValidationError("nnU-Net inference requires a ReefVision semantic model ZIP")
        if not image_path.is_file():
            raise ValidationError("Semantic inference source image is missing")

        predict_command = _command_path("nnUNetv2_predict")
        if predict_command is None:
            raise ValidationError("nnUNetv2_predict is unavailable")

        temporary_root = Path(tempfile.mkdtemp(prefix="reefvision-nnunet-predict-"))
        try:
            raw_root = temporary_root / "nnUNet_raw"
            preprocessed_root = temporary_root / "nnUNet_preprocessed"
            results_root = temporary_root / "nnUNet_results"
            input_root = temporary_root / "input"
            output_root = temporary_root / "output"
            raw_root.mkdir()
            preprocessed_root.mkdir()
            results_root.mkdir()
            input_root.mkdir()
            output_root.mkdir()

            with zipfile.ZipFile(checkpoint_path) as archive:
                try:
                    metadata = json.loads(
                        archive.read("reefvision-semantic-model.json").decode("utf-8")
                    )
                except (KeyError, json.JSONDecodeError) as exc:
                    raise ValidationError("Semantic model bundle metadata is invalid") from exc
                dataset_name = str(metadata["dataset_name"])
                trainer = str(metadata["trainer"])
                plans = str(metadata.get("plans", NNUNET_PLANS))
                configuration = str(metadata.get("configuration", NNUNET_CONFIGURATION))
                fold = str(metadata["fold"])
                configuration_root = (
                    results_root / dataset_name / f"{trainer}__{plans}__{configuration}"
                )
                configuration_root.mkdir(parents=True)
                archive.extractall(configuration_root)

            _convert_rgb_png(image_path, input_root / "reefvision_0000.png")
            env = dict(os.environ)
            env.update(
                {
                    "nnUNet_raw": str(raw_root),
                    "nnUNet_preprocessed": str(preprocessed_root),
                    "nnUNet_results": str(results_root),
                }
            )
            _run_command(
                [
                    str(predict_command),
                    "-i",
                    str(input_root),
                    "-o",
                    str(output_root),
                    "-d",
                    dataset_name,
                    "-c",
                    configuration,
                    "-f",
                    fold,
                    "-tr",
                    trainer,
                    "-p",
                    plans,
                    "-device",
                    _resolved_device(device),
                    "--disable_tta",
                ],
                env=env,
                log_path=None,
                cwd=temporary_root,
            )
            prediction = output_root / "reefvision.png"
            if not prediction.is_file():
                raise ValidationError("nnU-Net inference did not produce an indexed PNG mask")
            persistent_result = checkpoint_path.parent / (
                f"semantic-prediction-{image_path.stem}-{os.getpid()}.png"
            )
            shutil.copy2(prediction, persistent_result)
            return persistent_result
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)


PlannedNnUNetProvider = NnUNetV2Provider


def semantic_provider_for_name(
    provider_id: str,
) -> SemanticSegmentationProvider:
    normalized = provider_id.strip().casefold()
    if normalized == NNUNET_PROVIDER_ID:
        return NnUNetV2Provider()
    raise ValidationError(f"Unsupported semantic segmentation provider: {provider_id}")
