"""Pinned Ultralytics training-configuration registry for ReefVision."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from typing import Any

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import configure_provider_runtime, provider_spec
from reefvision.snapshot_cache import CachedSnapshot, get_cached_snapshot

ULTRALYTICS_PROVIDER_VERSION = provider_spec("ultralytics").provider_version
ULTRALYTICS_VERSION_LABEL = f"Ultralytics {ULTRALYTICS_PROVIDER_VERSION}"

SUPPORTED_REEFVISION_TASKS: tuple[str, ...] = ("detect", "segment")
SUPPORTED_REEFVISION_MODES: tuple[str, ...] = (
    "train",
    "val",
    "predict",
    "export",
    "tune",
)

SEGMENT_ONLY_KEYS = {
    "overlap_mask",
    "mask_ratio",
    "copy_paste",
    "copy_paste_mode",
    "retina_masks",
}
CLASSIFY_ONLY_KEYS = {"dropout", "auto_augment", "erasing"}
POSE_ONLY_KEYS = {"pose", "kobj"}
TRACK_ONLY_KEYS = {"tracker"}
PREDICT_ONLY_KEYS = {
    "source",
    "vid_stride",
    "stream_buffer",
    "augment",
    "agnostic_nms",
    "retina_masks",
    "embed",
    "show",
    "save_frames",
    "save_txt",
    "save_conf",
    "save_crop",
    "show_labels",
    "show_conf",
    "show_boxes",
    "line_width",
}
EXPORT_ONLY_KEYS = {
    "format",
    "keras",
    "optimize",
    "int8",
    "dynamic",
    "simplify",
    "opset",
    "workspace",
    "nms",
}
EVALUATION_KEYS = {
    "split",
    "save_json",
    "conf",
    "iou",
    "max_det",
    "half",
    "dnn",
    "plots",
    "visualize",
}
FIXED_ONLY_KEYS = {
    "task",
    "mode",
    "model",
    "data",
    "save",
    "save_period",
    "project",
    "name",
    "exist_ok",
    "verbose",
    "resume",
    "source",
    "show",
    "save_frames",
    "save_txt",
    "save_conf",
    "save_crop",
    "show_labels",
    "show_conf",
    "show_boxes",
    "line_width",
    "format",
    "keras",
    "optimize",
    "int8",
    "dynamic",
    "simplify",
    "opset",
    "workspace",
    "nms",
    "cfg",
    "tracker",
}
PARAMETER_CATEGORY_OVERRIDES = {
    "task": "data_identity",
    "mode": "data_identity",
    "model": "model_architecture",
    "data": "data_identity",
    "epochs": "core_training",
    "time": "core_training",
    "patience": "core_training",
    "batch": "core_training",
    "imgsz": "core_training",
    "save": "execution",
    "save_period": "execution",
    "cache": "execution",
    "device": "execution",
    "workers": "execution",
    "project": "execution",
    "name": "execution",
    "exist_ok": "execution",
    "pretrained": "model_architecture",
    "optimizer": "optimization",
    "verbose": "execution",
    "seed": "execution",
    "deterministic": "execution",
    "single_cls": "core_training",
    "rect": "core_training",
    "cos_lr": "optimization",
    "close_mosaic": "augmentation",
    "resume": "execution",
    "amp": "core_training",
    "fraction": "core_training",
    "profile": "execution",
    "freeze": "model_architecture",
    "multi_scale": "core_training",
    "compile": "execution",
    "overlap_mask": "segmentation",
    "mask_ratio": "segmentation",
    "dropout": "unsupported_task",
    "val": "evaluation",
    "split": "evaluation",
    "save_json": "evaluation",
    "conf": "evaluation",
    "iou": "evaluation",
    "max_det": "evaluation",
    "half": "evaluation",
    "dnn": "evaluation",
    "plots": "evaluation",
    "source": "prediction",
    "vid_stride": "prediction",
    "stream_buffer": "prediction",
    "visualize": "evaluation",
    "augment": "prediction",
    "agnostic_nms": "prediction",
    "classes": "evaluation",
    "retina_masks": "segmentation",
    "embed": "prediction",
    "show": "visualization",
    "save_frames": "visualization",
    "save_txt": "visualization",
    "save_conf": "visualization",
    "save_crop": "visualization",
    "show_labels": "visualization",
    "show_conf": "visualization",
    "show_boxes": "visualization",
    "line_width": "visualization",
    "format": "export",
    "keras": "export",
    "optimize": "export",
    "int8": "export",
    "dynamic": "export",
    "simplify": "export",
    "opset": "export",
    "workspace": "export",
    "nms": "export",
    "lr0": "optimization",
    "lrf": "optimization",
    "momentum": "optimization",
    "weight_decay": "optimization",
    "warmup_epochs": "optimization",
    "warmup_momentum": "optimization",
    "warmup_bias_lr": "optimization",
    "box": "loss",
    "cls": "loss",
    "dfl": "loss",
    "pose": "unsupported_task",
    "kobj": "unsupported_task",
    "nbs": "optimization",
    "hsv_h": "augmentation",
    "hsv_s": "augmentation",
    "hsv_v": "augmentation",
    "degrees": "augmentation",
    "translate": "augmentation",
    "scale": "augmentation",
    "shear": "augmentation",
    "perspective": "augmentation",
    "flipud": "augmentation",
    "fliplr": "augmentation",
    "bgr": "augmentation",
    "mosaic": "augmentation",
    "mixup": "augmentation",
    "cutmix": "augmentation",
    "copy_paste": "segmentation",
    "copy_paste_mode": "segmentation",
    "auto_augment": "unsupported_task",
    "erasing": "unsupported_task",
    "cfg": "execution",
    "tracker": "unsupported_task",
}
PARAMETER_CHOICES: dict[str, tuple[Any, ...]] = {
    "task": SUPPORTED_REEFVISION_TASKS,
    "mode": SUPPORTED_REEFVISION_MODES,
    "cache": (False, True, "ram", "disk"),
    "optimizer": ("auto", "SGD", "Adam", "Adamax", "AdamW", "NAdam", "RAdam", "RMSProp"),
    "split": ("train", "val", "test"),
    "format": (
        "torchscript",
        "onnx",
        "openvino",
        "engine",
        "coreml",
        "saved_model",
        "pb",
        "tflite",
        "edgetpu",
        "tfjs",
        "paddle",
        "mnn",
        "ncnn",
        "imx",
        "rknn",
        "executorch",
    ),
    "copy_paste_mode": ("flip", "mixup"),
    "auto_augment": ("randaugment", "autoaugment", "augmix"),
    "tracker": ("botsort.yaml", "bytetrack.yaml"),
    "compile": (False, True, "default", "reduce-overhead", "max-autotune-no-cudagraphs"),
}
TUNABLE_PARAMETER_RULES: dict[str, dict[str, Any]] = {
    "optimizer": {"choices": ("auto", "SGD", "Adam", "AdamW", "NAdam", "RAdam", "RMSProp")},
    "epochs": {"minimum": 1, "maximum": 1000, "integer": True},
    "patience": {"minimum": 0, "maximum": 1000, "integer": True},
    "batch": {"minimum": -1, "maximum": 1024, "scale": "linear"},
    "imgsz": {"minimum": 32, "maximum": 4096, "integer": True},
    "amp": {"choices": (False, True)},
    "single_cls": {"choices": (False, True)},
    "rect": {"choices": (False, True)},
    "close_mosaic": {"minimum": 0, "maximum": 1000, "integer": True},
    "fraction": {"minimum": 0.0, "maximum": 1.0},
    "multi_scale": {"choices": (False, True)},
    "overlap_mask": {"choices": (False, True)},
    "mask_ratio": {"minimum": 1, "maximum": 32, "integer": True},
    "lr0": {"minimum": 1e-5, "maximum": 1e-1, "scale": "log"},
    "lrf": {"minimum": 0.0001, "maximum": 0.1, "scale": "log"},
    "momentum": {"minimum": 0.0, "maximum": 1.0},
    "weight_decay": {"minimum": 0.0, "maximum": 1.0, "scale": "log"},
    "warmup_epochs": {"minimum": 0.0, "maximum": 10.0},
    "warmup_momentum": {"minimum": 0.0, "maximum": 1.0},
    "warmup_bias_lr": {"minimum": 0.0, "maximum": 1.0},
    "box": {"minimum": 0.0, "maximum": 20.0},
    "cls": {"minimum": 0.0, "maximum": 10.0},
    "dfl": {"minimum": 0.0, "maximum": 10.0},
    "nbs": {"minimum": 1, "maximum": 1024, "integer": True},
    "hsv_h": {"minimum": 0.0, "maximum": 1.0},
    "hsv_s": {"minimum": 0.0, "maximum": 1.0},
    "hsv_v": {"minimum": 0.0, "maximum": 1.0},
    "degrees": {"minimum": 0.0, "maximum": 180.0},
    "translate": {"minimum": 0.0, "maximum": 1.0},
    "scale": {"minimum": 0.0, "maximum": 1.0},
    "shear": {"minimum": 0.0, "maximum": 45.0},
    "perspective": {"minimum": 0.0, "maximum": 1.0},
    "flipud": {"minimum": 0.0, "maximum": 1.0},
    "fliplr": {"minimum": 0.0, "maximum": 1.0},
    "bgr": {"minimum": 0.0, "maximum": 1.0},
    "mosaic": {"minimum": 0.0, "maximum": 1.0},
    "mixup": {"minimum": 0.0, "maximum": 1.0},
    "cutmix": {"minimum": 0.0, "maximum": 1.0},
    "copy_paste": {"minimum": 0.0, "maximum": 1.0},
    "copy_paste_mode": {"choices": ("flip", "mixup")},
    "conf": {"minimum": 0.0, "maximum": 1.0},
    "iou": {"minimum": 0.0, "maximum": 1.0},
    "max_det": {"minimum": 1, "maximum": 3000, "integer": True},
}
NATIVE_TUNE_SPACE: dict[str, dict[str, float]] = {
    "lr0": {"minimum": 1e-5, "maximum": 1e-1, "scale": "log"},
    "lrf": {"minimum": 0.0001, "maximum": 0.1, "scale": "log"},
    "momentum": {"minimum": 0.7, "maximum": 0.98, "gain": 0.3, "scale": "linear"},
    "weight_decay": {"minimum": 0.0, "maximum": 0.001, "scale": "linear"},
    "warmup_epochs": {"minimum": 0.0, "maximum": 5.0, "scale": "linear"},
    "warmup_momentum": {"minimum": 0.0, "maximum": 0.95, "scale": "linear"},
    "box": {"minimum": 1.0, "maximum": 20.0, "scale": "linear"},
    "cls": {"minimum": 0.1, "maximum": 4.0, "scale": "linear"},
    "dfl": {"minimum": 0.4, "maximum": 6.0, "scale": "linear"},
    "hsv_h": {"minimum": 0.0, "maximum": 0.1, "scale": "linear"},
    "hsv_s": {"minimum": 0.0, "maximum": 0.9, "scale": "linear"},
    "hsv_v": {"minimum": 0.0, "maximum": 0.9, "scale": "linear"},
    "degrees": {"minimum": 0.0, "maximum": 45.0, "scale": "linear"},
    "translate": {"minimum": 0.0, "maximum": 0.9, "scale": "linear"},
    "scale": {"minimum": 0.0, "maximum": 0.95, "scale": "linear"},
    "shear": {"minimum": 0.0, "maximum": 10.0, "scale": "linear"},
    "perspective": {"minimum": 0.0, "maximum": 0.001, "scale": "linear"},
    "flipud": {"minimum": 0.0, "maximum": 1.0, "scale": "linear"},
    "fliplr": {"minimum": 0.0, "maximum": 1.0, "scale": "linear"},
    "bgr": {"minimum": 0.0, "maximum": 1.0, "scale": "linear"},
    "mosaic": {"minimum": 0.0, "maximum": 1.0, "scale": "linear"},
    "mixup": {"minimum": 0.0, "maximum": 1.0, "scale": "linear"},
    "cutmix": {"minimum": 0.0, "maximum": 1.0, "scale": "linear"},
    "copy_paste": {"minimum": 0.0, "maximum": 1.0, "scale": "linear"},
    "close_mosaic": {"minimum": 0.0, "maximum": 10.0, "scale": "linear"},
}
RANGE_OVERRIDES: dict[str, tuple[float | int | None, float | int | None]] = {
    "epochs": (1, None),
    "time": (0.0, None),
    "patience": (0, None),
    "batch": (-1, None),
    "imgsz": (1, None),
    "workers": (0, None),
    "save_period": (-1, None),
    "seed": (0, None),
    "close_mosaic": (0, None),
    "mask_ratio": (1, None),
    "max_det": (1, None),
    "vid_stride": (1, None),
    "line_width": (1, None),
    "workspace": (0.0, None),
    "box": (0.0, None),
    "cls": (0.0, None),
    "dfl": (0.0, None),
    "pose": (0.0, None),
    "kobj": (0.0, None),
    "nbs": (1, None),
    "erasing": (0.0, 1.0),
}
SPECIAL_TYPE_OVERRIDES = {
    "model": "optional_path",
    "data": "optional_path",
    "project": "optional_string",
    "name": "optional_string",
    "cache": "bool_or_cache_mode",
    "device": "device_selector",
    "pretrained": "bool_or_path",
    "freeze": "int_or_int_list",
    "classes": "int_or_int_list",
    "embed": "int_list",
    "source": "optional_string",
    "line_width": "optional_int",
    "format": "string",
    "compile": "bool_or_compile_mode",
    "opset": "optional_int",
    "workspace": "optional_float",
    "cfg": "optional_path",
    "tracker": "string",
    "imgsz": "int_or_int_list",
}
ULTRALYTICS_REGISTRY_TTL_SECONDS = 600


@dataclass(frozen=True)
class UltralyticsParameterRecord:
    name: str
    display_name: str
    category: str
    value_type: str
    default_value: Any
    minimum: float | int | None
    maximum: float | int | None
    choices: tuple[Any, ...]
    supported_tasks: tuple[str, ...]
    supported_modes: tuple[str, ...]
    reefvision_supported: bool
    tunable: bool
    fixed_only: bool
    native_tune_default: bool
    help_text: str
    dependency_rules: tuple[str, ...]
    supported_version: str
    native_tune_minimum: float | int | None
    native_tune_maximum: float | int | None
    native_tune_gain: float | None
    native_tune_scale: str | None


@dataclass(frozen=True)
class UltralyticsRegistrySnapshot:
    provider_name: str
    provider_version: str
    ultralytics_version: str | None
    pinned_version_matches_installed: bool
    supported_tasks: tuple[str, ...]
    supported_modes: tuple[str, ...]
    method_signatures: dict[str, str]
    parameters: tuple[UltralyticsParameterRecord, ...]

    @property
    def summary(self) -> dict[str, int]:
        reefvision_supported = [item for item in self.parameters if item.reefvision_supported]
        tunable = [item for item in self.parameters if item.tunable]
        fixed_only = [item for item in self.parameters if item.fixed_only]
        native_tune = [item for item in self.parameters if item.native_tune_default]
        return {
            "parameter_count": len(self.parameters),
            "reefvision_supported_parameter_count": len(reefvision_supported),
            "tunable_parameter_count": len(tunable),
            "native_tune_parameter_count": len(native_tune),
            "fixed_only_parameter_count": len(fixed_only),
        }


@dataclass(frozen=True)
class UltralyticsRegistrySummarySnapshot:
    provider_name: str
    provider_version: str
    ultralytics_version: str | None
    pinned_version_matches_installed: bool
    supported_tasks: tuple[str, ...]
    supported_modes: tuple[str, ...]
    summary: dict[str, int]


@dataclass(frozen=True)
class ValidatedSearchSpaceField:
    name: str
    minimum: float | int | None
    maximum: float | int | None
    discrete_values: tuple[Any, ...]
    fixed_value: Any
    scale: str
    integer: bool


@dataclass(frozen=True)
class UltralyticsValidationResult:
    ultralytics_version: str | None
    requested_mode: str
    normalized_mode: str
    validated_parameters: dict[str, Any]
    validated_search_space: tuple[ValidatedSearchSpaceField, ...]
    warnings: tuple[str, ...]


def ultralytics_training_registry(
    settings: Settings | None = None,
) -> UltralyticsRegistrySnapshot:
    return cached_ultralytics_training_registry(settings).value


def cached_ultralytics_training_registry(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
) -> CachedSnapshot[UltralyticsRegistrySnapshot]:
    return get_cached_snapshot(
        f"ultralytics_registry:{_settings_cache_key(settings)}",
        lambda: _ultralytics_training_registry_uncached(settings),
        ttl_seconds=ULTRALYTICS_REGISTRY_TTL_SECONDS,
        refresh=refresh,
    )


def ultralytics_training_registry_summary(
    settings: Settings | None = None,
) -> UltralyticsRegistrySummarySnapshot:
    return cached_ultralytics_training_registry_summary(settings).value


def cached_ultralytics_training_registry_summary(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
) -> CachedSnapshot[UltralyticsRegistrySummarySnapshot]:
    return get_cached_snapshot(
        f"ultralytics_registry_summary:{_settings_cache_key(settings)}",
        lambda: _ultralytics_registry_summary_from_snapshot(
            cached_ultralytics_training_registry(settings, refresh=refresh).value
        ),
        ttl_seconds=ULTRALYTICS_REGISTRY_TTL_SECONDS,
        refresh=refresh,
    )


def _ultralytics_training_registry_uncached(
    settings: Settings | None = None,
) -> UltralyticsRegistrySnapshot:
    provider_version = ULTRALYTICS_PROVIDER_VERSION
    installed_version = _installed_ultralytics_version()
    cfg_module, yolo_class = _import_ultralytics_runtime(settings)
    defaults = dict(cfg_module.get_cfg())
    help_texts = _parse_default_yaml_comments()
    method_signatures = {
        "train": str(inspect.signature(yolo_class.train)),
        "val": str(inspect.signature(yolo_class.val)),
        "predict": str(inspect.signature(yolo_class.predict)),
        "export": str(inspect.signature(yolo_class.export)),
        "tune": str(inspect.signature(yolo_class.tune)),
    }

    parameters = tuple(
        _build_parameter_record(
            name=key,
            default_value=value,
            help_text=help_texts.get(key, _fallback_help_text(key)),
            provider_version=provider_version,
        )
        for key, value in defaults.items()
    )
    return UltralyticsRegistrySnapshot(
        provider_name="ultralytics",
        provider_version=provider_version,
        ultralytics_version=installed_version,
        pinned_version_matches_installed=installed_version == provider_version,
        supported_tasks=SUPPORTED_REEFVISION_TASKS,
        supported_modes=SUPPORTED_REEFVISION_MODES,
        method_signatures=method_signatures,
        parameters=parameters,
    )


def validate_ultralytics_training_configuration(
    *,
    task: str,
    mode: str,
    parameters: dict[str, Any],
    search_space: list[dict[str, Any]],
    expected_ultralytics_version: str | None = None,
    settings: Settings | None = None,
) -> UltralyticsValidationResult:
    snapshot = ultralytics_training_registry(settings)
    if task not in SUPPORTED_REEFVISION_TASKS:
        raise ValidationError(
            "ReefVision currently supports Ultralytics training only for detect and segment tasks"
        )
    if mode not in SUPPORTED_REEFVISION_MODES:
        raise ValidationError(
            f"Unsupported ReefVision training mode: {mode}. "
            f"Choose one of {', '.join(SUPPORTED_REEFVISION_MODES)}."
        )
    if expected_ultralytics_version and expected_ultralytics_version != snapshot.provider_version:
        raise ValidationError(
            "Saved configuration version mismatch: "
            f"expected Ultralytics {expected_ultralytics_version}, "
            f"but ReefVision is pinned to {snapshot.provider_version}."
        )

    record_by_name = {item.name: item for item in snapshot.parameters}
    cfg_module, _ = _import_ultralytics_runtime(settings)
    normalized_mode = "train" if mode == "tune" else mode
    overrides = {"task": task, "mode": normalized_mode, **parameters}
    try:
        cfg_module.check_dict_alignment(dict(cfg_module.get_cfg()), overrides.copy())
        cfg_module.check_cfg(overrides.copy())
    except (SyntaxError, TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc

    validated_parameters: dict[str, Any] = {}
    for name, value in parameters.items():
        record = record_by_name.get(name)
        if record is None:
            raise ValidationError(
                f"'{name}' is not a valid {ULTRALYTICS_VERSION_LABEL} argument."
            )
        if not record.reefvision_supported:
            raise ValidationError(
                f"'{name}' is not exposed by ReefVision for its supported detect "
                "or segment workflows."
            )
        if mode not in record.supported_modes:
            raise ValidationError(f"'{name}' is not supported when mode={mode}.")
        if task not in record.supported_tasks:
            raise ValidationError(f"'{name}' is not supported for task={task}.")
        _validate_special_value(name, value, record)
        validated_parameters[name] = value

    validated_search_space = tuple(
        _validate_search_space_field(record_by_name, task=task, mode=mode, field=field)
        for field in search_space
    )

    warnings: list[str] = []
    if mode == "tune" and snapshot.ultralytics_version != snapshot.provider_version:
        warnings.append(
            "The installed Ultralytics package version does not match "
            "ReefVision's pinned provider version."
        )
    return UltralyticsValidationResult(
        ultralytics_version=snapshot.ultralytics_version,
        requested_mode=mode,
        normalized_mode=normalized_mode,
        validated_parameters=validated_parameters,
        validated_search_space=validated_search_space,
        warnings=tuple(warnings),
    )


def _build_parameter_record(
    *,
    name: str,
    default_value: Any,
    help_text: str,
    provider_version: str,
) -> UltralyticsParameterRecord:
    tasks = _supported_tasks(name)
    modes = _supported_modes(name)
    reefvision_supported = bool(tasks) and "track" not in modes
    tune_rule = TUNABLE_PARAMETER_RULES.get(name)
    native_rule = NATIVE_TUNE_SPACE.get(name)
    tunable = reefvision_supported and tune_rule is not None
    fixed_only = name in FIXED_ONLY_KEYS or not reefvision_supported
    minimum, maximum = _parameter_range(name)
    if tune_rule is not None:
        minimum = tune_rule.get("minimum", minimum)
        maximum = tune_rule.get("maximum", maximum)
    return UltralyticsParameterRecord(
        name=name,
        display_name=_display_name(name),
        category=PARAMETER_CATEGORY_OVERRIDES.get(name, "core_training"),
        value_type=_value_type(name, default_value),
        default_value=default_value,
        minimum=minimum,
        maximum=maximum,
        choices=tuple(
            tune_rule.get("choices", PARAMETER_CHOICES.get(name, ()))
            if tune_rule
            else PARAMETER_CHOICES.get(name, ())
        ),
        supported_tasks=tasks,
        supported_modes=modes,
        reefvision_supported=reefvision_supported,
        tunable=tunable,
        fixed_only=fixed_only,
        native_tune_default=native_rule is not None,
        help_text=help_text,
        dependency_rules=_dependency_rules(name),
        supported_version=provider_version,
        native_tune_minimum=native_rule.get("minimum") if native_rule else None,
        native_tune_maximum=native_rule.get("maximum") if native_rule else None,
        native_tune_gain=native_rule.get("gain") if native_rule else None,
        native_tune_scale=native_rule.get("scale") if native_rule else None,
    )


def _supported_tasks(name: str) -> tuple[str, ...]:
    if name in CLASSIFY_ONLY_KEYS or name in POSE_ONLY_KEYS or name in TRACK_ONLY_KEYS:
        return ()
    if name in SEGMENT_ONLY_KEYS:
        return ("segment",)
    return SUPPORTED_REEFVISION_TASKS


def _supported_modes(name: str) -> tuple[str, ...]:
    if name in TRACK_ONLY_KEYS:
        return ("track",)
    if name in EXPORT_ONLY_KEYS:
        return ("export",)
    if name in PREDICT_ONLY_KEYS:
        return ("predict",)
    if name in EVALUATION_KEYS:
        base_modes = ["val"]
        if name in {"conf", "iou", "max_det", "half", "dnn", "plots", "visualize", "classes"}:
            base_modes.extend(["predict", "tune"])
        if name == "plots":
            base_modes.append("train")
        return tuple(dict.fromkeys(base_modes))
    return ("train", "tune")


def _value_type(name: str, default_value: Any) -> str:
    if name in SPECIAL_TYPE_OVERRIDES:
        return SPECIAL_TYPE_OVERRIDES[name]
    if isinstance(default_value, bool):
        return "bool"
    if isinstance(default_value, int):
        return "int"
    if isinstance(default_value, float):
        return "float"
    if isinstance(default_value, str):
        return "string"
    return "optional"


def _parameter_range(name: str) -> tuple[float | int | None, float | int | None]:
    if name in RANGE_OVERRIDES:
        return RANGE_OVERRIDES[name]
    if name in {
        "dropout",
        "lr0",
        "lrf",
        "momentum",
        "weight_decay",
        "warmup_momentum",
        "warmup_bias_lr",
        "hsv_h",
        "hsv_s",
        "hsv_v",
        "translate",
        "scale",
        "perspective",
        "flipud",
        "fliplr",
        "bgr",
        "mosaic",
        "mixup",
        "cutmix",
        "copy_paste",
        "conf",
        "iou",
        "fraction",
    }:
        return (0.0, 1.0)
    return (None, None)


def _dependency_rules(name: str) -> tuple[str, ...]:
    rules: list[str] = []
    if name in SEGMENT_ONLY_KEYS:
        rules.append("Available only for ReefVision segment workflows.")
    if name in CLASSIFY_ONLY_KEYS:
        rules.append(
            "Classification-only parameter. ReefVision does not currently "
            "implement classify training."
        )
    if name in POSE_ONLY_KEYS:
        rules.append(
            "Pose-only parameter. ReefVision does not currently implement pose training."
        )
    if name in TRACK_ONLY_KEYS:
        rules.append(
            "Tracking-only parameter. ReefVision does not currently implement "
            "tracking workflows."
        )
    if name == "momentum":
        rules.append(
            "Meaningful primarily when the optimizer uses momentum or Adam "
            "beta1 semantics."
        )
    if name == "copy_paste_mode":
        rules.append("Only applies when copy_paste is enabled for segment training.")
    if name == "workspace":
        rules.append("Only applies when exporting TensorRT engine format.")
    if name == "opset":
        rules.append("Only applies when exporting ONNX or TensorRT engine formats.")
    if name == "keras":
        rules.append("Only applies when format=saved_model during export.")
    if name == "nms":
        rules.append("Only applies when the selected export backend can fuse NMS.")
    if name == "save_json":
        rules.append("Only applies to validation-style evaluation runs.")
    if name == "split":
        rules.append(
            "Validation split selection must remain train, val, or test from "
            "the immutable dataset version."
        )
    return tuple(rules)


def _display_name(name: str) -> str:
    return name.replace("_", " ").title()


def _fallback_help_text(name: str) -> str:
    return f"Pinned {ULTRALYTICS_VERSION_LABEL} parameter '{name}'."


def _parse_default_yaml_comments() -> dict[str, str]:
    try:
        default_yaml_path = files("ultralytics.cfg").joinpath("default.yaml")
        lines = default_yaml_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        raise ValidationError(
            f"{ULTRALYTICS_VERSION_LABEL} default configuration could not be read: {exc}"
        ) from exc
    comments: dict[str, str] = {}
    pattern = re.compile(r"^\s*([a-zA-Z0-9_]+):.*?#\s*(.+?)\s*$")
    for line in lines:
        match = pattern.match(line)
        if match:
            comments[match.group(1)] = match.group(2)
    return comments


def _installed_ultralytics_version() -> str | None:
    try:
        return version("ultralytics")
    except PackageNotFoundError:
        return None


def _import_ultralytics_runtime(settings: Settings | None):
    configure_provider_runtime(settings)
    try:
        cfg_module = import_module("ultralytics.cfg")
        yolo_module = import_module("ultralytics")
    except Exception as exc:
        raise ValidationError(f"{ULTRALYTICS_VERSION_LABEL} is unavailable: {exc}") from exc
    return cfg_module, yolo_module.YOLO


def _validate_special_value(name: str, value: Any, record: UltralyticsParameterRecord) -> None:
    if record.choices and value not in record.choices:
        raise ValidationError(
            f"'{name}' must be one of {list(record.choices)!r} for "
            f"Ultralytics {record.supported_version}."
        )

    minimum, maximum = record.minimum, record.maximum
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if minimum is not None and value < minimum:
            raise ValidationError(f"'{name}' must be greater than or equal to {minimum}.")
        if maximum is not None and value > maximum:
            raise ValidationError(f"'{name}' must be less than or equal to {maximum}.")

    if name == "cache" and not (isinstance(value, bool) or value in {"ram", "disk"}):
        raise ValidationError("'cache' must be False, True, 'ram', or 'disk'.")
    if name == "pretrained" and not isinstance(value, (bool, str)):
        raise ValidationError("'pretrained' must be a bool or a checkpoint path string.")
    if name == "compile" and not (
        isinstance(value, bool)
        or value in {"default", "reduce-overhead", "max-autotune-no-cudagraphs"}
    ):
        raise ValidationError(
            "'compile' must be False, True, 'default', 'reduce-overhead', or "
            "'max-autotune-no-cudagraphs'."
        )
    if name in {"imgsz", "freeze", "classes"} and not (
        isinstance(value, int) or _is_int_list(value)
    ):
        raise ValidationError(f"'{name}' must be an int or a list of ints.")
    if name == "embed" and not _is_int_list(value):
        raise ValidationError("'embed' must be a list of ints.")
    if name == "device" and not (
        isinstance(value, (int, str)) or _is_int_list(value) or _is_str_list(value)
    ):
        raise ValidationError("'device' must be a string, int, or list of strings or ints.")


def _validate_search_space_field(
    record_by_name: dict[str, UltralyticsParameterRecord],
    *,
    task: str,
    mode: str,
    field: dict[str, Any],
) -> ValidatedSearchSpaceField:
    name = str(field.get("name", "")).strip()
    if not name:
        raise ValidationError("Search-space entries must include a parameter name.")
    record = record_by_name.get(name)
    if record is None:
        raise ValidationError(f"'{name}' is not a valid {ULTRALYTICS_VERSION_LABEL} argument.")
    if not record.tunable:
        raise ValidationError(f"'{name}' is fixed-only in ReefVision and cannot be tuned.")
    if not record.reefvision_supported:
        raise ValidationError(f"'{name}' is not available for ReefVision's supported tasks.")
    if mode != "tune":
        raise ValidationError("Search-space definitions are only valid when mode=tune.")
    if task not in record.supported_tasks:
        raise ValidationError(f"'{name}' is not supported for task={task}.")

    minimum = field.get("minimum")
    maximum = field.get("maximum")
    discrete_values = tuple(field.get("discrete_values", []))
    fixed_value = field.get("fixed_value")
    scale = str(field.get("scale", "linear"))
    integer_flag = bool(field.get("integer")) if field.get("integer") is not None else False
    if scale not in {"linear", "log"}:
        raise ValidationError("Search-space scale must be 'linear' or 'log'.")

    populated_modes = sum(
        value is not None and value != ()
        for value in (minimum, maximum, discrete_values, fixed_value)
    )
    if populated_modes == 0:
        raise ValidationError(
            f"'{name}' search space must define bounds, choices, or a fixed value."
        )
    if fixed_value is not None and populated_modes > 1:
        raise ValidationError(
            f"'{name}' search space cannot mix fixed_value with bounds or discrete_values."
        )
    if discrete_values and (minimum is not None or maximum is not None):
        raise ValidationError(
            f"'{name}' search space cannot mix discrete_values with minimum or maximum."
        )
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValidationError(f"'{name}' search space minimum cannot exceed its maximum.")
    if scale == "log" and (minimum is None or maximum is None):
        raise ValidationError(
            f"'{name}' logarithmic search spaces require both minimum and maximum."
        )

    numeric_minimum = record.minimum
    numeric_maximum = record.maximum
    if minimum is not None and numeric_minimum is not None and minimum < numeric_minimum:
        raise ValidationError(f"'{name}' search-space minimum must be >= {numeric_minimum}.")
    if maximum is not None and numeric_maximum is not None and maximum > numeric_maximum:
        raise ValidationError(f"'{name}' search-space maximum must be <= {numeric_maximum}.")
    if integer_flag or record.value_type in {"int", "optional_int", "int_or_int_list"}:
        if minimum is not None and not isinstance(minimum, int):
            raise ValidationError(f"'{name}' integer search-space minimum must be an int.")
        if maximum is not None and not isinstance(maximum, int):
            raise ValidationError(f"'{name}' integer search-space maximum must be an int.")
        if discrete_values and not _is_int_list(list(discrete_values)):
            raise ValidationError(f"'{name}' integer search-space choices must all be ints.")

    for item in discrete_values:
        _validate_special_value(name, item, record)
    if fixed_value is not None:
        _validate_special_value(name, fixed_value, record)

    return ValidatedSearchSpaceField(
        name=name,
        minimum=minimum,
        maximum=maximum,
        discrete_values=discrete_values,
        fixed_value=fixed_value,
        scale=scale,
        integer=integer_flag or record.value_type in {"int", "optional_int", "int_or_int_list"},
    )


def _is_int_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, int) for item in value)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _ultralytics_registry_summary_from_snapshot(
    snapshot: UltralyticsRegistrySnapshot,
) -> UltralyticsRegistrySummarySnapshot:
    return UltralyticsRegistrySummarySnapshot(
        provider_name=snapshot.provider_name,
        provider_version=snapshot.provider_version,
        ultralytics_version=snapshot.ultralytics_version,
        pinned_version_matches_installed=snapshot.pinned_version_matches_installed,
        supported_tasks=snapshot.supported_tasks,
        supported_modes=snapshot.supported_modes,
        summary=snapshot.summary,
    )


def _settings_cache_key(settings: Settings | None) -> str:
    if settings is None:
        return "default"
    return str(settings.resolved_data_dir)
