"""Install the optional ReefVision catalog model pack into desktop AppData.

This script deliberately keeps optional checkpoints out of the core MSI. It
retrieves allow-listed official Ultralytics release assets, records their exact
size and SHA-256 after download, writes them to ReefVision's managed model
store, and creates an AppData catalog override consumed on the next launch.

Models whose provider/runtime is not implemented remain unavailable rather
than being represented as usable merely because a file was downloaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RELEASE_ROOT = "https://github.com/ultralytics/assets/releases/download"
RELEASE_TAGS = ("v8.3.0", "v8.2.0", "v8.1.0", "v0.0.0")
CHUNK_SIZE = 1024 * 1024
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class OptionalModel:
    catalog_id: str
    filename: str
    provider_id: str
    task: str
    architecture: str
    variant: str
    display_summary: str
    provider_version: str
    provider_pack_id: str | None
    trainable: bool = False
    inference_supported: bool = True
    preferred_tags: tuple[str, ...] = RELEASE_TAGS
    limitations: tuple[str, ...] = ()


OPTIONAL_MODELS: tuple[OptionalModel, ...] = (
    *tuple(
        OptionalModel(
            catalog_id=f"ultralytics/yolo11/segment/{size}",
            filename=f"yolo11{size}-seg.pt",
            provider_id="ultralytics",
            task="segment",
            architecture="YOLO11",
            variant=size,
            display_summary=(
                f"Official YOLO11 {size.upper()} pretrained instance-segmentation checkpoint."
            ),
            provider_version="8.3.228",
            provider_pack_id="ultralytics-base",
            trainable=True,
            limitations=(
                "Native masks are preserved as polygon proposals with a "
                "source-aligned raster fallback.",
                "Accepted masks remain editable and unverified until explicit human review.",
                "Ultralytics polygon segmentation training is supported; tiled training "
                "and packaged-desktop validation remain unavailable.",
            ),
        )
        for size in ("n", "s", "m", "l", "x")
    ),
    *tuple(
        OptionalModel(
            catalog_id=f"ultralytics/yolov8/segment/{size}",
            filename=f"yolov8{size}-seg.pt",
            provider_id="ultralytics",
            task="segment",
            architecture="YOLOv8",
            variant=size,
            display_summary=(
                f"Official YOLOv8 {size.upper()} pretrained instance-segmentation checkpoint."
            ),
            provider_version="8.3.228",
            provider_pack_id="ultralytics-base",
            trainable=True,
            preferred_tags=("v8.2.0", "v8.3.0", "v8.1.0", "v0.0.0"),
            limitations=(
                "Native masks are preserved as polygon proposals with a "
                "source-aligned raster fallback.",
                "Accepted masks remain editable and unverified until explicit human review.",
                "Ultralytics polygon segmentation training is supported; tiled training "
                "and packaged-desktop validation remain unavailable.",
            ),
        )
        for size in ("n", "s", "m", "l", "x")
    ),
    OptionalModel(
        catalog_id="ultralytics/rtdetr/l",
        filename="rtdetr-l.pt",
        provider_id="ultralytics",
        task="detect",
        architecture="RT-DETR",
        variant="l",
        display_summary="Official RT-DETR Large pretrained object detector.",
        provider_version="8.3.228",
        provider_pack_id="ultralytics-base",
        limitations=("RT-DETR training is not enabled in the current Training workspace.",),
    ),
    OptionalModel(
        catalog_id="ultralytics/rtdetr/x",
        filename="rtdetr-x.pt",
        provider_id="ultralytics",
        task="detect",
        architecture="RT-DETR",
        variant="x",
        display_summary="Official RT-DETR XLarge pretrained object detector.",
        provider_version="8.3.228",
        provider_pack_id="ultralytics-base",
        limitations=("RT-DETR training is not enabled in the current Training workspace.",),
    ),
    OptionalModel(
        catalog_id="sam/original/vit_b",
        filename="sam_b.pt",
        provider_id="segment_anything",
        task="assist_segmentation",
        architecture="SAM",
        variant="vit_b",
        display_summary="Official SAM ViT-B compatible checkpoint for Smart Mask prompting.",
        provider_version="1.0+reefvision-pack",
        provider_pack_id=None,
        limitations=(
            "This Ultralytics-distributed SAM checkpoint is loaded through the "
            "packaged Smart Mask adapter.",
        ),
    ),
    OptionalModel(
        catalog_id="sam2/image/base",
        filename="sam2_b.pt",
        provider_id="segment_anything",
        task="assist_segmentation",
        architecture="SAM 2",
        variant="base",
        display_summary="Official SAM 2 Base image checkpoint for Smart Mask prompting.",
        provider_version="1.0+reefvision-pack",
        provider_pack_id=None,
        limitations=(
            "Image prompting is supported through Ultralytics SAM.",
            "Video propagation requires the separate SAM 2 video runtime and remains unavailable.",
        ),
    ),
    OptionalModel(
        catalog_id="mobilesam/default",
        filename="mobile_sam.pt",
        provider_id="segment_anything",
        task="assist_segmentation",
        architecture="MobileSAM",
        variant="default",
        display_summary="Official MobileSAM checkpoint for lightweight Smart Mask prompting.",
        provider_version="1.0+reefvision-pack",
        provider_pack_id=None,
    ),
    OptionalModel(
        catalog_id="fastsam/default",
        filename="FastSAM-s.pt",
        provider_id="segment_anything",
        task="assist_segmentation",
        architecture="FastSAM",
        variant="default",
        display_summary="Official FastSAM Small checkpoint for fast Smart Mask proposals.",
        provider_version="1.0+reefvision-pack",
        provider_pack_id=None,
        limitations=(
            "Positive-point and box prompts are exposed; negative and mixed prompts "
            "are not advertised.",
        ),
    ),
    OptionalModel(
        catalog_id="ultralytics/yolo_world/base",
        filename="yolov8s-worldv2.pt",
        provider_id="ultralytics",
        task="open_vocabulary_detect",
        architecture="YOLO-World",
        variant="base",
        display_summary="Official YOLOv8 Small World v2 open-vocabulary detector checkpoint.",
        provider_version="8.3.228",
        provider_pack_id="ultralytics-base",
        preferred_tags=("v8.2.0", "v8.3.0", "v8.1.0", "v0.0.0"),
        limitations=(
            "Inference requires an explicit user-provided text-class prompt list.",
            "Open-vocabulary proposals remain unverified until explicit review.",
        ),
    ),
    OptionalModel(
        catalog_id="ultralytics/yoloe/base",
        filename="yoloe-11s-seg-pf.pt",
        provider_id="ultralytics",
        task="prompt_free_segment",
        architecture="YOLOE",
        variant="base",
        display_summary="Official YOLOE-11 Small prompt-free segmentation checkpoint.",
        provider_version="8.3.228",
        provider_pack_id="ultralytics-base",
        limitations=(
            "YOLOE is prompt-free segmentation, not ordinary closed-set detection.",
            "Native mask proposals remain unverified until explicit review.",
        ),
    ),
)


UNIMPLEMENTED_CATALOG_IDS: tuple[str, ...] = (
    "transformers/grounding_dino/tiny",
    "transformers/grounding_dino/base",
    "transformers/owlv2/base",
    "transformers/owlv2/large",
    "transformers/florence2/base",
    "transformers/florence2/large",
    "reefvision/unet/nano",
    "reefvision/unet/small",
    "reefvision/unet/medium",
    "reefvision/unet/large",
    "reefvision/unet/xlarge",
    "nnunet/automatic/default",
)


def default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "org.reefvision.desktop"
    return Path.home() / ".reefvision"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def release_urls(model: OptionalModel) -> list[str]:
    return [f"{RELEASE_ROOT}/{tag}/{model.filename}" for tag in model.preferred_tags]


def download_official_asset(model: OptionalModel, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    errors: list[str] = []
    for url in release_urls(model):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ReefVision-Optional-Model-Pack/1.0",
                "Accept": "application/octet-stream",
            },
        )
        try:
            print(f"Downloading {model.filename} from {url}")
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                partial.open("wb") as output,
            ):
                shutil.copyfileobj(response, output, length=CHUNK_SIZE)
            if partial.stat().st_size <= 0:
                raise OSError("downloaded file is empty")
            os.replace(partial, destination)
            return url
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            partial.unlink(missing_ok=True)
            errors.append(f"{url}: {exc}")
    raise RuntimeError(
        f"No approved official release asset was found for {model.filename}. " + " | ".join(errors)
    )


def managed_path(data_dir: Path, catalog_id: str, filename: str) -> Path:
    segments = catalog_id.split("/")
    return data_dir / "models" / "catalog-models" / Path(*segments) / filename


def relative_managed_path(data_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(data_dir.resolve()).as_posix()


def patch_entry(
    entry: dict[str, Any],
    model: OptionalModel,
    *,
    source_url: str,
    digest: str,
    size: int,
) -> None:
    revision = source_url.split("/download/", 1)[1].split("/", 1)[0]
    expected = {
        "filename": model.filename,
        "source_url": source_url,
        "revision": f"ultralytics-assets-{revision}",
        "sha256": digest,
        "size_bytes": size,
    }
    entry.update(
        {
            "display_summary": model.display_summary,
            "provider": model.provider_id,
            "provider_id": model.provider_id,
            "provider_version": model.provider_version,
            "architecture_family": model.architecture,
            "architecture": model.architecture,
            "model_variant": model.task,
            "variant": model.variant,
            "task": model.task,
            "trainable": model.trainable,
            "inference": model.inference_supported,
            "inference_supported": model.inference_supported,
            "checkpoint_identifier": model.filename,
            "checkpoint_source": "trusted_https_release",
            "download_source_type": "trusted_https_release",
            "expected_checksum": digest,
            "expected_file_size": size,
            "expected_files": [expected],
            "expected_size": size,
            "required_provider_pack": model.provider_pack_id,
            "provider_pack_id": model.provider_pack_id,
            "desktop_package_status": "optional_local_model_pack",
            "clean_machine_verification_status": "downloaded_and_hashed_locally",
            "deprecation_status": "active",
            "known_limitations": list(model.limitations),
            "availability": "available",
            "installation_state": "Ready",
            "installation_reason": "Installed and verified by the optional ReefVision model pack.",
            "advanced_only": False,
            "requires_confirmation": False,
            "selection_kind": "managed_catalog_model",
            "architecture_reference": None,
            "resolved_model_id": None,
            "license_summary": (
                "Official Ultralytics-distributed pretrained weights; AGPL-3.0 or an "
                "applicable Ultralytics enterprise license."
            ),
            "model_weight_license": (
                "Official Ultralytics-distributed pretrained weights; review applicable "
                "Ultralytics licensing before use."
            ),
            "package_license": "See the packaged provider metadata and upstream model license.",
        }
    )


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"manifest_version": MANIFEST_VERSION, "assets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"manifest_version": MANIFEST_VERSION, "assets": {}}
    if payload.get("manifest_version") != MANIFEST_VERSION or not isinstance(
        payload.get("assets"), dict
    ):
        return {"manifest_version": MANIFEST_VERSION, "assets": {}}
    return payload


def install_model_pack(
    *,
    data_dir: Path,
    source_catalog: Path,
    only: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    catalog = json.loads(source_catalog.read_text(encoding="utf-8"))
    entries = {
        str(entry.get("catalog_id")): entry
        for entry in catalog.get("models", [])
        if isinstance(entry, dict)
    }
    manifest_path = data_dir / "models" / "catalog-models" / "manifest.json"
    manifest = load_manifest(manifest_path)
    assets = dict(manifest.get("assets", {}))
    installed: list[str] = []
    failed: list[str] = []

    for model in OPTIONAL_MODELS:
        if only is not None and model.catalog_id not in only and model.filename not in only:
            continue
        entry = entries.get(model.catalog_id)
        if entry is None:
            failed.append(f"{model.catalog_id}: catalog entry is missing")
            continue
        destination = managed_path(data_dir, model.catalog_id, model.filename)
        source_url = ""
        try:
            existing = assets.get(model.catalog_id)
            if (
                destination.is_file()
                and isinstance(existing, dict)
                and existing.get("filename") == model.filename
                and existing.get("size_bytes") == destination.stat().st_size
                and existing.get("sha256") == sha256_file(destination)
                and str(existing.get("source_url") or "").startswith(RELEASE_ROOT)
            ):
                source_url = str(existing["source_url"])
                print(f"Reusing verified {model.filename}")
            else:
                destination.unlink(missing_ok=True)
                source_url = download_official_asset(model, destination)
            size = destination.stat().st_size
            digest = sha256_file(destination)
            patch_entry(entry, model, source_url=source_url, digest=digest, size=size)
            assets[model.catalog_id] = {
                "catalog_id": model.catalog_id,
                "filename": model.filename,
                "relative_path": relative_managed_path(data_dir, destination),
                "sha256": digest,
                "size_bytes": size,
                "provider_version": model.provider_version,
                "source": "optional_model_pack",
                "source_url": source_url,
                "installed_at": datetime.now(UTC).isoformat(),
            }
            installed.append(model.catalog_id)
            print(f"Installed {model.catalog_id} ({size / 1024 / 1024:.1f} MB)")
        except Exception as exc:
            failed.append(f"{model.catalog_id}: {exc}")
            print(f"FAILED {model.catalog_id}: {exc}", file=sys.stderr)

    catalog["catalog_version"] = "2.1.0-local-model-pack"
    atomic_json(data_dir / "config" / "model_catalog.json", catalog)
    atomic_json(
        manifest_path,
        {
            "manifest_version": MANIFEST_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "assets": assets,
        },
    )
    return installed, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument(
        "--catalog",
        type=Path,
        default=repository_root() / "config" / "model_catalog.json",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        help="Install only a catalog id or checkpoint filename; may be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    source_catalog = args.catalog.expanduser().resolve()
    if not source_catalog.is_file():
        print(f"Catalog not found: {source_catalog}", file=sys.stderr)
        return 2
    data_dir.mkdir(parents=True, exist_ok=True)
    installed, failed = install_model_pack(
        data_dir=data_dir,
        source_catalog=source_catalog,
        only=set(args.only) if args.only else None,
    )
    print()
    print(f"Installed or verified {len(installed)} optional catalog models.")
    if failed:
        print(f"{len(failed)} model(s) could not be installed:", file=sys.stderr)
        for failure in failed:
            print(f"  - {failure}", file=sys.stderr)
    print(
        f"Local catalog override: {data_dir / 'config' / 'model_catalog.json'}\n"
        "Restart ReefVision and choose Refresh catalog."
    )
    print("Still unavailable by design: " + ", ".join(UNIMPLEMENTED_CATALOG_IDS))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
