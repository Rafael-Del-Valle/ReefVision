"""Build and verify the offline wheel from the canonical ReefVision SDK source."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from email.parser import BytesParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

SDK = "reefvision_sdk"
ENTRY = f"{SDK}/__init__.py"
ROOT = Path(__file__).resolve().parents[1]


def project_metadata(root: Path) -> dict[str, str]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return {name: project[name] for name in ("version", "requires-python", "license")}


def verify_wheel(root: Path, wheel: Path, project: dict[str, str]) -> None:
    version = project["version"]
    if wheel.name != f"{SDK}-{version}-py3-none-any.whl":
        raise ValueError("The SDK wheel must use the ReefVision version and a pure Python tag.")
    dist = f"{SDK}-{version}.dist-info"
    required = {
        ENTRY,
        f"{dist}/METADATA",
        f"{dist}/WHEEL",
        f"{dist}/RECORD",
        f"{dist}/licenses/LICENSE",
    }
    source = (root / "apps" / "api" / ENTRY).read_bytes()
    module = ast.parse(source)
    versions = [
        node.value.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
    ]
    if versions != [version]:
        raise ValueError("The canonical SDK source version does not match the ReefVision release.")
    with ZipFile(wheel) as archive:
        members = archive.namelist()
        if len(members) != len(set(members)) or set(members) not in (
            required,
            required | {f"{dist}/top_level.txt"},
        ):
            raise ValueError("The SDK wheel contains unexpected files or lacks required metadata.")
        if archive.read(ENTRY) != source:
            raise ValueError("Wheel member does not match the canonical SDK source.")
        if archive.read(f"{dist}/licenses/LICENSE") != (root / "LICENSE").read_bytes():
            raise ValueError("The SDK wheel does not include the ReefVision license.")
        metadata = BytesParser().parsebytes(archive.read(f"{dist}/METADATA"))
        wheel_info = BytesParser().parsebytes(archive.read(f"{dist}/WHEEL"))
        if (
            metadata["Name"] != "reefvision-sdk"
            or metadata["Version"] != version
            or metadata["Requires-Python"] != project["requires-python"]
            or metadata["License-Expression"] != project["license"]
            or metadata.get_all("Requires-Dist")
            or wheel_info["Root-Is-Purelib"] != "true"
            or wheel_info.get_all("Tag") != ["py3-none-any"]
        ):
            raise ValueError("SDK wheel metadata does not match the pure, dependency-free package.")


def build_wheel(root: Path, output: Path, project: dict[str, str]) -> Path:
    with tempfile.TemporaryDirectory(prefix="rv-sdk-") as scratch:
        stage = Path(scratch)
        (stage / SDK).mkdir()
        shutil.copyfile(root / "apps" / "api" / ENTRY, stage / ENTRY)
        shutil.copyfile(root / "LICENSE", stage / "LICENSE")
        (stage / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools>=77"]\n'
            'build-backend = "setuptools.build_meta"\n\n'
            '[project]\nname = "reefvision-sdk"\n'
            'description = "Local automation SDK for ReefVision"\n'
            + "\n".join(f"{key} = {json.dumps(value)}" for key, value in project.items())
            + '\nlicense-files = ["LICENSE"]\n\n[tool.setuptools]\npackages = ["reefvision_sdk"]\n',
            encoding="utf-8",
        )
        dist = stage / "dist"
        environment = dict(os.environ)
        environment.setdefault("SOURCE_DATE_EPOCH", "315532800")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(dist),
                str(stage),
            ],
            check=True,
            env=environment,
            stdout=sys.stderr,
        )
        (built,) = dist.glob("*.whl")
        verify_wheel(root, built, project)
        output.mkdir(parents=True, exist_ok=True)
        path = output / built.name
        with tempfile.NamedTemporaryFile(dir=output, prefix=".rv-sdk-", delete=False) as temporary:
            staged = Path(temporary.name)
        try:
            shutil.copyfile(built, staged)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
        return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    purpose = parser.add_mutually_exclusive_group(required=True)
    purpose.add_argument("--output", type=Path)
    purpose.add_argument("--verify-wheel", type=Path)
    args = parser.parse_args()
    try:
        project = project_metadata(args.root)
        if args.verify_wheel:
            wheel = args.verify_wheel
            verify_wheel(args.root, wheel, project)
        else:
            wheel = build_wheel(args.root, args.output, project)
    except (
        BadZipFile,
        KeyError,
        OSError,
        SyntaxError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"ReefVision SDK wheel: {error}", file=sys.stderr)
        return 1
    print(wheel.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
