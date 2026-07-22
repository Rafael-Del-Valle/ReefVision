"""Advanced nnU-Net v2 dataset, subprocess, and result integration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

from reefvision.domain.errors import ValidationError


@dataclass(frozen=True)
class NnUNetPaths:
    raw: Path
    preprocessed: Path
    results: Path

    def environment(self) -> dict[str, str]:
        return {
            "nnUNet_raw": str(self.raw.resolve()),
            "nnUNet_preprocessed": str(self.preprocessed.resolve()),
            "nnUNet_results": str(self.results.resolve()),
        }


@dataclass(frozen=True)
class NnUNetCase:
    case_id: str
    image_path: Path
    mask_path: Path | None


@dataclass(frozen=True)
class NnUNetDatasetManifest:
    dataset_id: int
    dataset_name: str
    channel_names: dict[str, str]
    labels: dict[str, int]
    num_training: int
    file_ending: str = ".png"

    @property
    def folder_name(self) -> str:
        return f"Dataset{self.dataset_id:03d}_{self.dataset_name}"


def ensure_nnunet_paths(paths: NnUNetPaths) -> None:
    for path in (paths.raw, paths.preprocessed, paths.results):
        path.expanduser().resolve().mkdir(parents=True, exist_ok=True)


def _validate_case_id(case_id: str) -> str:
    normalized = case_id.strip()
    if not normalized or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in normalized):
        raise ValidationError(f"Invalid nnU-Net case id: {case_id!r}")
    return normalized


def export_nnunet_dataset(
    paths: NnUNetPaths,
    manifest: NnUNetDatasetManifest,
    training_cases: Iterable[NnUNetCase],
    test_cases: Iterable[NnUNetCase] = (),
) -> Path:
    """Export RGB images and indexed masks into nnU-Net v2's raw format."""

    ensure_nnunet_paths(paths)
    if not 1 <= manifest.dataset_id <= 999:
        raise ValidationError("nnU-Net dataset ids must be between 1 and 999")
    if not manifest.dataset_name.replace("_", "").isalnum():
        raise ValidationError("nnU-Net dataset names may contain letters, numbers, and underscores")
    root = paths.raw.resolve() / manifest.folder_name
    if root.exists():
        shutil.rmtree(root)
    images_tr = root / "imagesTr"
    labels_tr = root / "labelsTr"
    images_ts = root / "imagesTs"
    images_tr.mkdir(parents=True)
    labels_tr.mkdir(parents=True)
    training = list(training_cases)
    testing = list(test_cases)
    if len(training) != manifest.num_training:
        raise ValidationError("nnU-Net manifest num_training does not match supplied cases")
    for item in training:
        case_id = _validate_case_id(item.case_id)
        if item.mask_path is None:
            raise ValidationError(f"Training case {case_id} has no mask")
        _export_case_image(item.image_path, images_tr / f"{case_id}_0000.png")
        _export_case_mask(item.mask_path, labels_tr / f"{case_id}.png", manifest.labels)
    if testing:
        images_ts.mkdir(parents=True)
        for item in testing:
            case_id = _validate_case_id(item.case_id)
            _export_case_image(item.image_path, images_ts / f"{case_id}_0000.png")
    dataset_json = {
        "channel_names": manifest.channel_names,
        "labels": manifest.labels,
        "numTraining": manifest.num_training,
        "file_ending": manifest.file_ending,
        "reefvision": {
            "format_version": 1,
            "dataset_id": manifest.dataset_id,
            "dataset_name": manifest.dataset_name,
        },
    }
    (root / "dataset.json").write_text(
        json.dumps(dataset_json, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def _export_case_image(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ValidationError(f"nnU-Net source image does not exist: {source}")
    image = Image.open(source).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG")


def _export_case_mask(source: Path, destination: Path, labels: dict[str, int]) -> None:
    if not source.is_file():
        raise ValidationError(f"nnU-Net source mask does not exist: {source}")
    maximum_label = max(labels.values(), default=0)
    mask = Image.open(source).convert("L")
    extrema = mask.getextrema()
    if extrema is not None and int(extrema[1]) > maximum_label:
        raise ValidationError(
            f"Mask {source.name} contains label {extrema[1]}, above declared maximum {maximum_label}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    mask.save(destination, format="PNG")


def nnunet_command_environment(paths: NnUNetPaths) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(paths.environment())
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def run_nnunet_command(
    executable: Path,
    arguments: list[str],
    *,
    paths: NnUNetPaths,
    cwd: Path,
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    resolved = executable.expanduser().resolve()
    if not resolved.is_file():
        raise ValidationError(f"nnU-Net executable does not exist: {resolved}")
    ensure_nnunet_paths(paths)
    try:
        result = subprocess.run(
            [str(resolved), *arguments],
            cwd=cwd.resolve(),
            env=nnunet_command_environment(paths),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError(f"nnU-Net command could not complete: {exc}") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "No diagnostic output").strip()
        raise ValidationError(f"nnU-Net command failed ({result.returncode}): {details}")
    return result


def plan_and_preprocess(
    executable: Path,
    *,
    dataset_id: int,
    paths: NnUNetPaths,
    cwd: Path,
    verify_dataset: bool = True,
) -> subprocess.CompletedProcess[str]:
    arguments = ["-d", str(dataset_id)]
    if verify_dataset:
        arguments.append("--verify_dataset_integrity")
    return run_nnunet_command(executable, arguments, paths=paths, cwd=cwd)


def train_fold(
    executable: Path,
    *,
    dataset_id: int,
    configuration: str,
    fold: int | str,
    paths: NnUNetPaths,
    cwd: Path,
    trainer: str | None = None,
    plans: str | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [str(dataset_id), configuration, str(fold)]
    if trainer:
        arguments.extend(("-tr", trainer))
    if plans:
        arguments.extend(("-p", plans))
    return run_nnunet_command(executable, arguments, paths=paths, cwd=cwd)


def predict_folder(
    executable: Path,
    *,
    input_folder: Path,
    output_folder: Path,
    dataset_id: int,
    configuration: str,
    folds: tuple[int, ...],
    paths: NnUNetPaths,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    output_folder.mkdir(parents=True, exist_ok=True)
    arguments = [
        "-i",
        str(input_folder.resolve()),
        "-o",
        str(output_folder.resolve()),
        "-d",
        str(dataset_id),
        "-c",
        configuration,
        "-f",
        *(str(fold) for fold in folds),
    ]
    return run_nnunet_command(executable, arguments, paths=paths, cwd=cwd)


def import_prediction_masks(output_folder: Path) -> dict[str, Path]:
    root = output_folder.expanduser().resolve()
    if not root.is_dir():
        raise ValidationError("nnU-Net prediction output directory does not exist")
    masks: dict[str, Path] = {}
    for path in sorted(root.glob("*.png")):
        case_id = _validate_case_id(path.stem)
        masks[case_id] = path
    if not masks:
        raise ValidationError("nnU-Net produced no PNG prediction masks")
    return masks


def write_nnunet_run_manifest(
    path: Path,
    *,
    dataset: NnUNetDatasetManifest,
    configuration: str,
    folds: tuple[int, ...],
    command_output: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "dataset": asdict(dataset),
                "configuration": configuration,
                "folds": list(folds),
                "command_output": command_output,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
