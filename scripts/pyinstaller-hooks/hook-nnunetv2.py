"""PyInstaller hook for the complete pinned nnU-Net provider dependency graph."""

from __future__ import annotations

from PyInstaller.utils.hooks import collect_all, copy_metadata

from reefvision.ml.nnunet_dependency_contract import NNUNET_DEPENDENCIES

binaries: list[tuple[str, str]] = []
datas: list[tuple[str, str]] = []
hiddenimports: list[str] = []

for dependency in NNUNET_DEPENDENCIES:
    package_datas, package_binaries, package_hiddenimports = collect_all(
        dependency.import_name,
        include_py_files=True,
    )
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)
    datas.extend(copy_metadata(dependency.distribution_name, recursive=True))
