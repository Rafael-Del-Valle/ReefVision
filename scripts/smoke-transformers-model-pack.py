#!/usr/bin/env python3
"""Load and execute every staged Transformers vision model on requested devices."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from reefvision.ml.providers import DetectionSettings
from reefvision.ml.transformers_provider import TransformersVisionDetectionProvider


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), dict):
        raise RuntimeError("Transformers model-pack manifest is invalid")
    if int(payload.get("model_count") or 0) != 6 or len(payload["models"]) != 6:
        raise RuntimeError("Transformers model-pack smoke requires exactly six staged models")
    return payload


def _test_image(path: Path) -> None:
    image = Image.new("RGB", (128, 128), (18, 44, 55))
    draw = ImageDraw.Draw(image)
    draw.ellipse((36, 32, 92, 88), fill=(215, 176, 122), outline=(250, 235, 210), width=3)
    draw.line((64, 88, 64, 120), fill=(180, 120, 90), width=8)
    image.save(path, format="PNG")


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _cleanup() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass


def run_smoke(root: Path, devices: list[str], prompt: str) -> list[dict[str, Any]]:
    manifest = _load_manifest(root)
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    with tempfile.TemporaryDirectory(prefix="reefvision-transformers-smoke-") as temporary:
        image_path = Path(temporary) / "smoke.png"
        _test_image(image_path)
        for catalog_id, raw_record in manifest["models"].items():
            if not isinstance(raw_record, dict):
                failures.append(f"{catalog_id}: invalid manifest record")
                continue
            provider_id = str(raw_record.get("provider_id") or "")
            model_dir = root / str(raw_record.get("relative_path") or "")
            for device in devices:
                started = time.perf_counter()
                provider = TransformersVisionDetectionProvider(provider_id)
                outcome: dict[str, Any] = {
                    "catalog_id": catalog_id,
                    "provider_id": provider_id,
                    "device": device,
                    "status": "failed",
                    "prediction_count": 0,
                }
                try:
                    metadata = provider.inspect_model(model_dir)
                    provider.load_model(model_dir, device)
                    predictions = provider.predict(
                        image_path,
                        DetectionSettings(
                            confidence_threshold=0.2,
                            iou_threshold=0.45,
                            device=device,
                        ),
                        text_prompt=prompt,
                    )
                    outcome.update(
                        status="passed",
                        prediction_count=len(predictions),
                        framework=metadata.framework,
                        task=metadata.task,
                    )
                except Exception as exc:
                    outcome["error"] = f"{type(exc).__name__}: {exc}"
                    failures.append(f"{catalog_id} on {device}: {outcome['error']}")
                finally:
                    provider.unload_model()
                    _cleanup()
                    outcome["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                    results.append(outcome)
                    print(json.dumps(outcome, sort_keys=True), flush=True)

    if failures:
        raise RuntimeError("; ".join(failures))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--devices", default="cpu,cuda")
    parser.add_argument("--prompt", default="coral polyp")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--allow-missing-cuda", action="store_true")
    args = parser.parse_args()

    devices = [item.strip().casefold() for item in args.devices.split(",") if item.strip()]
    if not devices or any(item not in {"cpu", "cuda"} for item in devices):
        raise RuntimeError("Devices must be a comma-separated subset of cpu,cuda")
    if "cuda" in devices and not _cuda_available():
        if args.allow_missing_cuda:
            devices.remove("cuda")
        else:
            raise RuntimeError(
                "CUDA smoke testing was requested but torch.cuda.is_available() is false"
            )

    results = run_smoke(args.root.resolve(), devices, args.prompt.strip())
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
    print(f"Transformers model-pack smoke passed: {len(results)} model/device executions.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Transformers model-pack smoke failed: {exc}", file=sys.stderr)
        raise
