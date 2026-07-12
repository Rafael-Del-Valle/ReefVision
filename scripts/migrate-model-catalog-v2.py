"""Deterministically upgrade the bundled model catalog to schema version 2."""

from __future__ import annotations

import json
from pathlib import Path

YOLO11_DETECT = {
    "n": (
        "Nano",
        "yolo11n.pt",
        5_613_764,
        "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1",
    ),
    "s": (
        "Small",
        "yolo11s.pt",
        19_313_732,
        "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5",
    ),
    "m": (
        "Medium",
        "yolo11m.pt",
        40_684_120,
        "d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95",
    ),
    "l": (
        "Large",
        "yolo11l.pt",
        51_387_343,
        "9ebd0e09d59811db4b1d61e2bc6730649608b1ac47f8dd01e2da6bca7c20023f",
    ),
    "x": (
        "X",
        "yolo11x.pt",
        114_636_239,
        "7bc158aa95c0ebfdd87f70f01653c1131b93e92522dbe15c228bcd742e773a24",
    ),
}


def _availability(entry: dict[str, object]) -> str:
    if entry.get("installation_state") == "Unavailable":
        return "unavailable"
    if entry.get("deprecation_status") == "experimental":
        return "experimental"
    return "available"


def migrate(catalog_path: Path) -> None:
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    payload["catalog_version"] = "2.0.0"
    for entry in payload["models"]:
        entry["provider_id"] = entry["provider"]
        entry["architecture"] = entry["architecture_family"]
        entry["variant"] = entry.get("model_size") or entry["model_variant"]
        entry["inference_supported"] = bool(entry["inference"])
        entry["download_source_type"] = entry["checkpoint_source"]
        entry["expected_files"] = []
        entry["expected_size"] = entry.get("expected_file_size")
        entry["license_summary"] = entry["model_weight_license"]
        entry["provider_pack_id"] = entry.get("required_provider_pack")
        entry["recommended_ram"] = entry.get("minimum_recommended_ram_gb")
        entry["recommended_vram"] = entry.get("minimum_recommended_vram_gb")
        entry["supported_runtimes"] = entry.get("supported_runtime", [])
        entry["desktop_support"] = entry["desktop_package_status"]
        entry["availability"] = _availability(entry)

        prefix = "ultralytics/yolo11/detect/"
        if entry["catalog_id"].startswith(prefix):
            variant = entry["catalog_id"].removeprefix(prefix)
            label, filename, size, sha256 = YOLO11_DETECT[variant]
            url = f"https://github.com/ultralytics/assets/releases/download/v8.3.0/{filename}"
            entry.update(
                {
                    "display_name": f"YOLO11 {label}",
                    "display_summary": (
                        f"Official YOLO11 {label} pretrained object detector, "
                        "managed and verified by ReefVision."
                    ),
                    "inference": True,
                    "inference_supported": True,
                    "checkpoint_identifier": filename,
                    "checkpoint_source": "trusted_https_release",
                    "download_source_type": "trusted_https_release",
                    "expected_files": [
                        {
                            "filename": filename,
                            "source_url": url,
                            "revision": "ultralytics-assets-v8.3.0",
                            "sha256": sha256,
                            "size_bytes": size,
                        }
                    ],
                    "expected_checksum": sha256,
                    "expected_file_size": size,
                    "expected_size": size,
                    "model_weight_license": (
                        "Official Ultralytics YOLO11 pretrained weights; review "
                        "Ultralytics licensing before use."
                    ),
                    "license_summary": (
                        "Ultralytics pretrained weights; AGPL-3.0 or an applicable "
                        "Ultralytics enterprise license."
                    ),
                    "provider_pack_id": "ultralytics-base",
                    "required_provider_pack": "ultralytics-base",
                    "availability": "available",
                    "installation_state": "Not Installed",
                    "installation_reason": (
                        "The verified pretrained checkpoint is not installed yet."
                    ),
                    "requires_confirmation": True,
                    "selection_kind": "managed_catalog_model",
                    "architecture_reference": f"yolo11{variant}.yaml",
                    "known_limitations": [
                        "Installation requires network access for the initial trusted download.",
                        "Ultralytics must be available in the bundled provider runtime "
                        "before training or inference.",
                    ],
                }
            )

    catalog_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    migrate(Path(__file__).resolve().parents[1] / "config" / "model_catalog.json")
