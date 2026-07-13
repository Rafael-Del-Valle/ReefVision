import json
from pathlib import Path


def test_yolov8_detection_catalog_uses_managed_pretrained_weights() -> None:
    catalog_path = Path(__file__).resolve().parents[1] / "config" / "model_catalog.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = {
        entry["catalog_id"]: entry
        for entry in payload["models"]
        if entry["catalog_id"].startswith("ultralytics/yolov8/detect/")
    }

    expected_ids = {
        f"ultralytics/yolov8/detect/{variant}" for variant in ("n", "s", "m", "l", "x")
    }
    assert set(entries) == expected_ids

    for catalog_id, entry in entries.items():
        variant = catalog_id.rsplit("/", 1)[-1]
        filename = f"yolov8{variant}.pt"
        assert entry["selection_kind"] == "managed_catalog_model"
        assert entry["checkpoint_identifier"] == filename
        assert entry["checkpoint_source"] == "trusted_https_release"
        assert entry["architecture_reference"] == f"yolov8{variant}.yaml"
        assert entry["inference"] is True
        assert entry["inference_supported"] is True
        assert entry["installation_state"] == "Not Installed"
        assert entry["provider_pack_id"] == "ultralytics-base"
        assert entry["expected_checksum"]
        assert entry["expected_file_size"] > 0
        assert entry["expected_files"] == [
            {
                "filename": filename,
                "source_url": entry["expected_files"][0]["source_url"],
                "revision": entry["expected_files"][0]["revision"],
                "sha256": entry["expected_checksum"],
                "size_bytes": entry["expected_file_size"],
            }
        ]
        assert entry["expected_files"][0]["source_url"].startswith(
            "https://github.com/ultralytics/assets/releases/download/"
        )
