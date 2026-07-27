"""Complete dependency and entrypoint contract for the pinned nnU-Net provider."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Final


@dataclass(frozen=True)
class NnUNetDependency:
    distribution_name: str
    import_name: str
    collect_all: bool = True


PINNED_NNUNET_VERSION: Final = "2.6.2"
NNUNET_DEPENDENCIES: Final[tuple[NnUNetDependency, ...]] = (
    NnUNetDependency("nnunetv2", "nnunetv2"),
    NnUNetDependency("torch", "torch"),
    NnUNetDependency("acvl-utils", "acvl_utils"),
    NnUNetDependency("dynamic-network-architectures", "dynamic_network_architectures"),
    NnUNetDependency("tqdm", "tqdm"),
    NnUNetDependency("scipy", "scipy"),
    NnUNetDependency("batchgenerators", "batchgenerators"),
    NnUNetDependency("numpy", "numpy"),
    NnUNetDependency("scikit-learn", "sklearn"),
    NnUNetDependency("scikit-image", "skimage"),
    NnUNetDependency("SimpleITK", "SimpleITK"),
    NnUNetDependency("pandas", "pandas"),
    NnUNetDependency("graphviz", "graphviz"),
    NnUNetDependency("tifffile", "tifffile"),
    NnUNetDependency("requests", "requests"),
    NnUNetDependency("nibabel", "nibabel"),
    NnUNetDependency("matplotlib", "matplotlib"),
    NnUNetDependency("seaborn", "seaborn"),
    NnUNetDependency("imagecodecs", "imagecodecs"),
    NnUNetDependency("yacs", "yacs"),
    NnUNetDependency("batchgeneratorsv2", "batchgeneratorsv2"),
    NnUNetDependency("einops", "einops"),
    NnUNetDependency("blosc2", "blosc2"),
)
NNUNET_ENTRYPOINTS: Final[dict[str, tuple[str, str]]] = {
    "nnUNetv2_plan_and_preprocess": (
        "nnunetv2.experiment_planning.plan_and_preprocess_entrypoints",
        "plan_and_preprocess_entry",
    ),
    "nnUNetv2_train": (
        "nnunetv2.run.run_training",
        "run_training_entry",
    ),
    "nnUNetv2_predict": (
        "nnunetv2.inference.predict_from_raw_data",
        "predict_entry_point",
    ),
}


def nnunet_import_packages() -> tuple[str, ...]:
    return tuple(item.import_name for item in NNUNET_DEPENDENCIES)


def nnunet_distribution_names() -> tuple[str, ...]:
    return tuple(item.distribution_name for item in NNUNET_DEPENDENCIES)


def validate_nnunet_dependency_contract() -> list[str]:
    """Return import/version problems for the complete packaged provider surface."""

    issues: list[str] = []
    try:
        installed_nnunet = version("nnunetv2")
    except PackageNotFoundError:
        installed_nnunet = None
    if installed_nnunet != PINNED_NNUNET_VERSION:
        issues.append(
            f"nnunetv2 must be {PINNED_NNUNET_VERSION}; found {installed_nnunet or 'not installed'}"
        )

    for dependency in NNUNET_DEPENDENCIES:
        try:
            importlib.import_module(dependency.import_name)
        except Exception as exc:
            issues.append(
                f"{dependency.distribution_name} ({dependency.import_name}): "
                f"{type(exc).__name__}: {exc}"
            )
    for command_name, (module_name, function_name) in NNUNET_ENTRYPOINTS.items():
        try:
            module = importlib.import_module(module_name)
            entrypoint = getattr(module, function_name, None)
            if not callable(entrypoint):
                raise AttributeError(function_name)
        except Exception as exc:
            issues.append(
                f"{command_name} ({module_name}:{function_name}): {type(exc).__name__}: {exc}"
            )
    return issues


def require_nnunet_dependency_contract() -> None:
    issues = validate_nnunet_dependency_contract()
    if issues:
        raise RuntimeError("nnU-Net dependency contract failed: " + "; ".join(issues))
