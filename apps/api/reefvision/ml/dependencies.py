"""Pinned provider dependency metadata and readiness checks."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.snapshot_cache import CachedSnapshot, get_cached_snapshot

PROVIDER_REQUIREMENTS_FILE = "requirements/providers-windows-cu121-py312.txt"
TESTED_PROVIDER_PYTHON = "3.12.x"
TESTED_PROVIDER_PLATFORM = "Windows AMD64"
DEFAULT_PROVIDER_RUNTIME_DIRNAME = "provider-runtime"
LIGHTWEIGHT_PROVIDER_PREFLIGHT_TTL_SECONDS = 300
ProviderCheckLevel = Literal["lightweight", "full"]


@dataclass(frozen=True)
class ProviderPackageRequirement:
    distribution_name: str
    required_version: str
    import_name: str | None = None


@dataclass(frozen=True)
class ProviderRuntimeSpec:
    provider_name: str
    display_name: str
    purpose: str
    provider_version: str
    packages: tuple[ProviderPackageRequirement, ...]
    tested_python: str = TESTED_PROVIDER_PYTHON
    tested_platform: str = TESTED_PROVIDER_PLATFORM
    tested_cuda: str | None = None
    automatic_downloads_disabled: bool = True
    explicit_checkpoint_required: bool = True


@dataclass(frozen=True)
class ProviderPackageStatus:
    distribution_name: str
    required_version: str
    installed_version: str | None
    status: str


@dataclass(frozen=True)
class ProviderPreflightReport:
    provider_name: str
    display_name: str
    purpose: str
    provider_version: str
    tested_python: str
    current_python: str
    tested_platform: str
    current_platform: str
    tested_cuda: str | None
    current_cuda: str | None
    automatic_downloads_disabled: bool
    explicit_checkpoint_required: bool
    requirements_file: str
    package_statuses: tuple[ProviderPackageStatus, ...]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def status(self) -> str:
        if not self.issues and all(item.status == "ok" for item in self.package_statuses):
            return "ready"
        if any(item.status == "missing" for item in self.package_statuses):
            return "missing"
        return "incompatible"


IMPLEMENTED_PROVIDER_SPECS: tuple[ProviderRuntimeSpec, ...] = (
    ProviderRuntimeSpec(
        provider_name="ultralytics",
        display_name="Ultralytics detector",
        purpose="detector",
        provider_version="8.3.228",
        tested_cuda="12.1",
        packages=(
            ProviderPackageRequirement("numpy", "2.2.6"),
            ProviderPackageRequirement("matplotlib", "3.10.7"),
            ProviderPackageRequirement(
                "opencv-contrib-python",
                "4.12.0.88",
                import_name="cv2",
            ),
            ProviderPackageRequirement("pillow", "12.0.0", import_name="PIL"),
            ProviderPackageRequirement("pyyaml", "6.0.3", import_name="yaml"),
            ProviderPackageRequirement("requests", "2.32.5"),
            ProviderPackageRequirement("scipy", "1.16.3"),
            ProviderPackageRequirement("lap", "0.5.13"),
            ProviderPackageRequirement("torch", "2.5.1+cu121"),
            ProviderPackageRequirement("torchvision", "0.20.1+cu121"),
            ProviderPackageRequirement("psutil", "7.1.3"),
            ProviderPackageRequirement("polars", "1.35.2"),
            ProviderPackageRequirement("pandas", "2.3.3"),
            ProviderPackageRequirement("seaborn", "0.13.2"),
            ProviderPackageRequirement("ultralytics-thop", "2.0.18", import_name="thop"),
            ProviderPackageRequirement("ultralytics", "8.3.228"),
        ),
    ),
    ProviderRuntimeSpec(
        provider_name="segment_anything",
        display_name="Segment Anything assist",
        purpose="assist",
        provider_version="1.0",
        tested_cuda="12.1",
        packages=(
            ProviderPackageRequirement("numpy", "2.2.6"),
            ProviderPackageRequirement(
                "opencv-contrib-python",
                "4.12.0.88",
                import_name="cv2",
            ),
            ProviderPackageRequirement("torch", "2.5.1+cu121"),
            ProviderPackageRequirement("torchvision", "0.20.1+cu121"),
            ProviderPackageRequirement(
                "segment-anything",
                "1.0",
                import_name="segment_anything",
            ),
        ),
    ),
)


def provider_requirements_path() -> Path:
    return Path(__file__).resolve().parents[4] / PROVIDER_REQUIREMENTS_FILE


def provider_runtime_dir(settings: Settings | None = None, data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        base_dir = data_dir
    elif settings is not None:
        base_dir = settings.resolved_data_dir
    else:
        base_dir = Path.cwd() / ".reefvision"
    return base_dir / DEFAULT_PROVIDER_RUNTIME_DIRNAME


def configure_provider_runtime(
    settings: Settings | None = None,
    *,
    data_dir: Path | None = None,
) -> Path:
    runtime_dir = provider_runtime_dir(settings, data_dir=data_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_AUTOINSTALL"] = "false"
    # API workers and the frozen sidecar have no GUI event loop. Select the
    # file-rendering backend before importing providers/pyplot, including threads.
    os.environ["MPLBACKEND"] = "Agg"
    config_dir = str(runtime_dir.resolve())
    if settings is not None or data_dir is not None:
        os.environ["YOLO_CONFIG_DIR"] = config_dir
    else:
        os.environ.setdefault("YOLO_CONFIG_DIR", config_dir)
    return runtime_dir


def provider_spec(provider_name: str) -> ProviderRuntimeSpec:
    for spec in IMPLEMENTED_PROVIDER_SPECS:
        if spec.provider_name == provider_name:
            return spec
    raise ValidationError(f"Unknown provider: {provider_name}")


def implemented_provider_preflight(
    settings: Settings | None = None,
    *,
    check_level: ProviderCheckLevel = "full",
) -> list[ProviderPreflightReport]:
    configure_provider_runtime(settings)
    return [
        provider_preflight(spec.provider_name, settings, check_level=check_level)
        for spec in IMPLEMENTED_PROVIDER_SPECS
    ]


def provider_preflight(
    provider_name: str,
    settings: Settings | None = None,
    *,
    check_level: ProviderCheckLevel = "full",
) -> ProviderPreflightReport:
    configure_provider_runtime(settings)
    spec = provider_spec(provider_name)
    current_python = platform.python_version()
    current_platform = _current_platform_label()
    package_statuses = tuple(_package_status(requirement) for requirement in spec.packages)
    issues = list(
        _base_issues(spec, current_python=current_python, current_platform=current_platform)
    )

    current_cuda: str | None = None
    if check_level == "full":
        if _package_state(package_statuses, "torch") == "ok":
            current_cuda, torch_issue = _torch_runtime_check(spec.tested_cuda)
            if torch_issue is not None:
                issues.append(torch_issue)

        if all(item.status == "ok" for item in package_statuses):
            provider_issue = _provider_import_issue(provider_name)
            if provider_issue is not None:
                issues.append(provider_issue)

    return ProviderPreflightReport(
        provider_name=spec.provider_name,
        display_name=spec.display_name,
        purpose=spec.purpose,
        provider_version=spec.provider_version,
        tested_python=spec.tested_python,
        current_python=current_python,
        tested_platform=spec.tested_platform,
        current_platform=current_platform,
        tested_cuda=spec.tested_cuda,
        current_cuda=current_cuda,
        automatic_downloads_disabled=spec.automatic_downloads_disabled,
        explicit_checkpoint_required=spec.explicit_checkpoint_required,
        requirements_file=PROVIDER_REQUIREMENTS_FILE,
        package_statuses=package_statuses,
        issues=tuple(issues),
    )


def require_provider_ready(provider_name: str, settings: Settings | None = None) -> None:
    report = provider_preflight(provider_name, settings, check_level="full")
    if report.ready:
        return

    package_issues = [
        _format_package_issue(item) for item in report.package_statuses if item.status != "ok"
    ]
    all_issues = [*report.issues, *package_issues]
    message = "; ".join(all_issues) if all_issues else "unknown provider dependency issue"
    raise ValidationError(
        f"{report.display_name} dependencies are not ready: {message}. "
        f"Install the pinned provider stack from {report.requirements_file}."
    )


def require_all_implemented_providers_ready(settings: Settings | None = None) -> None:
    reports = implemented_provider_preflight(settings, check_level="full")
    failures = [report for report in reports if not report.ready]
    if not failures:
        return

    formatted = "; ".join(
        f"{report.provider_name}: "
        + ", ".join(
            [
                *report.issues,
                *[
                    _format_package_issue(item)
                    for item in report.package_statuses
                    if item.status != "ok"
                ],
            ]
        )
        for report in failures
    )
    raise ValidationError(
        "Pinned provider dependencies are not ready for desktop packaging: "
        f"{formatted}. Install {PROVIDER_REQUIREMENTS_FILE} first."
    )


def cached_lightweight_provider_preflight(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
) -> CachedSnapshot[list[ProviderPreflightReport]]:
    settings_key = _settings_cache_key(settings)
    return get_cached_snapshot(
        f"provider_preflight:{settings_key}",
        lambda: implemented_provider_preflight(settings, check_level="lightweight"),
        ttl_seconds=LIGHTWEIGHT_PROVIDER_PREFLIGHT_TTL_SECONDS,
        refresh=refresh,
    )


def _package_status(requirement: ProviderPackageRequirement) -> ProviderPackageStatus:
    try:
        installed_version = version(requirement.distribution_name)
    except PackageNotFoundError:
        return ProviderPackageStatus(
            distribution_name=requirement.distribution_name,
            required_version=requirement.required_version,
            installed_version=None,
            status="missing",
        )

    status = "ok" if installed_version == requirement.required_version else "incompatible"
    return ProviderPackageStatus(
        distribution_name=requirement.distribution_name,
        required_version=requirement.required_version,
        installed_version=installed_version,
        status=status,
    )


def _base_issues(
    spec: ProviderRuntimeSpec,
    *,
    current_python: str,
    current_platform: str,
) -> list[str]:
    issues: list[str] = []
    if sys.version_info[:2] != (3, 12):
        issues.append(
            f"Python {spec.tested_python} is required for the pinned provider stack "
            f"(found {current_python})"
        )
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        issues.append(
            f"{spec.tested_platform} is the tested provider platform (found {current_platform})"
        )
    return issues


def _current_platform_label() -> str:
    return f"{platform.system()} {platform.machine()}"


def _package_state(
    package_statuses: tuple[ProviderPackageStatus, ...], distribution_name: str
) -> str:
    for item in package_statuses:
        if item.distribution_name == distribution_name:
            return item.status
    return "missing"


def _torch_runtime_check(expected_cuda: str | None) -> tuple[str | None, str | None]:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - depends on local package state
        return None, f"Torch failed to import: {exc}"

    current_cuda = getattr(getattr(torch, "version", None), "cuda", None)
    if expected_cuda is not None and current_cuda != expected_cuda:
        return (
            current_cuda,
            "CUDA "
            f"{expected_cuda} is required for the pinned provider stack "
            f"(found {current_cuda or 'none'})",
        )
    return current_cuda, None


def _provider_import_issue(provider_name: str) -> str | None:
    try:
        if provider_name == "ultralytics":
            module = import_module("ultralytics")
            _ = module.YOLO
            return None
        if provider_name == "segment_anything":
            module = import_module("segment_anything")
            _ = module.sam_model_registry
            return None
    except Exception as exc:  # pragma: no cover - depends on local package state
        return f"{provider_name} failed to import cleanly: {exc}"
    return None


def _format_package_issue(item: ProviderPackageStatus) -> str:
    if item.status == "missing":
        return f"{item.distribution_name} {item.required_version} is missing"
    if item.installed_version is None:
        return f"{item.distribution_name} should be {item.required_version}"
    return (
        f"{item.distribution_name} should be {item.required_version} "
        f"(found {item.installed_version})"
    )


def _settings_cache_key(settings: Settings | None) -> str:
    if settings is None:
        return "default"
    return str(settings.resolved_data_dir)
