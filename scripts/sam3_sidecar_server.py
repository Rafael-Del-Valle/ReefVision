#!/usr/bin/env python
"""Minimal localhost HTTP sidecar for Meta SAM 3 concept segmentation.

Run this script inside a dedicated SAM 3 environment. ReefVision communicates
with it only over loopback HTTP, keeping the desktop backend's pinned PyTorch
stack isolated from SAM 3's newer runtime requirements.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import Any

import numpy as np
import torch
from PIL import Image, UnidentifiedImageError
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.model_builder import build_sam3_image_model

MAX_REQUEST_BYTES = 64 * 1024 * 1024
MODEL_VERSION = "sam3.1"


def _as_numpy(value: Any) -> np.ndarray:
    detached = value.detach() if hasattr(value, "detach") else value
    on_cpu = detached.cpu() if hasattr(detached, "cpu") else detached
    array = on_cpu.numpy() if hasattr(on_cpu, "numpy") else on_cpu
    return np.asarray(array)


def _mask_png_base64(
    mask: np.ndarray,
    *,
    width: int,
    height: int,
) -> tuple[str, tuple[int, int, int, int]]:
    binary = np.squeeze(mask) > 0.5
    if binary.ndim != 2:
        raise ValueError("SAM 3 returned a mask with an unsupported shape")
    image = Image.fromarray(binary.astype(np.uint8) * 255, mode="L")
    if image.size != (width, height):
        image = image.resize((width, height), resample=Image.Resampling.NEAREST)
    bounds = image.getbbox()
    if bounds is None:
        raise ValueError("SAM 3 returned an empty mask")
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return base64.b64encode(stream.getvalue()).decode("ascii"), bounds


class Sam3Runtime:
    def __init__(self) -> None:
        self.model = build_sam3_image_model()
        self.processor = Sam3Processor(self.model)
        self.lock = threading.Lock()

    def segment(
        self,
        image: Image.Image,
        *,
        prompt: str,
        score_threshold: float,
    ) -> list[dict[str, Any]]:
        width, height = image.size
        with self.lock, torch.inference_mode():
            state = self.processor.set_image(image)
            output = self.processor.set_text_prompt(state=state, prompt=prompt)
        masks = _as_numpy(output["masks"])
        scores = _as_numpy(output["scores"]).reshape(-1)
        if masks.ndim == 2:
            masks = masks[None, ...]
        if masks.ndim == 4 and masks.shape[1] == 1:
            masks = masks[:, 0, ...]
        if masks.ndim != 3:
            raise ValueError("SAM 3 returned masks with an unsupported shape")
        instances: list[dict[str, Any]] = []
        limit = min(len(masks), len(scores))
        for index in range(limit):
            score = float(scores[index])
            if not np.isfinite(score) or score < score_threshold:
                continue
            try:
                mask_payload, bounds = _mask_png_base64(
                    masks[index],
                    width=width,
                    height=height,
                )
            except ValueError:
                continue
            left, top, right, bottom = bounds
            instances.append(
                {
                    "score": score,
                    "box": [float(left), float(top), float(right), float(bottom)],
                    "mask_png_base64": mask_payload,
                }
            )
        return instances


class Sam3Handler(BaseHTTPRequestHandler):
    runtime: Sam3Runtime
    bearer_token: str | None = None
    server_version = "ReefVision-SAM3/1.0"

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not self.bearer_token:
            return True
        return self.headers.get("Authorization") == f"Bearer {self.bearer_token}"

    def do_GET(self) -> None:
        if self.path != "/health":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        self._json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "model": "sam3",
                "model_version": MODEL_VERSION,
                "cuda_available": bool(torch.cuda.is_available()),
            },
        )

    def do_POST(self) -> None:
        if self.path != "/segment":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt or len(prompt) > 500:
                raise ValueError("prompt must contain 1 to 500 characters")
            threshold = float(payload.get("score_threshold", 0.35))
            if not 0 <= threshold <= 1:
                raise ValueError("score_threshold must be between 0 and 1")
            encoded = payload.get("image_png_base64")
            if not isinstance(encoded, str):
                raise ValueError("image_png_base64 is required")
            try:
                raw_image = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("image_png_base64 is invalid") from exc
            try:
                with Image.open(BytesIO(raw_image)) as source:
                    source.load()
                    image = source.convert("RGB")
            except (OSError, UnidentifiedImageError) as exc:
                raise ValueError("image is not a readable PNG") from exc
            instances = self.runtime.segment(
                image,
                prompt=prompt,
                score_threshold=threshold,
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"SAM 3 inference failed: {exc}"},
            )
            return
        self._json(
            HTTPStatus.OK,
            {
                "model": "sam3",
                "model_version": MODEL_VERSION,
                "prompt": prompt,
                "instances": instances,
            },
        )

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[sam3-sidecar] {self.address_string()} - {format_string % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--token-env",
        default="REEFVISION_SAM3_SIDECAR_TOKEN",
        help="Environment variable containing the optional bearer token.",
    )
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="Permit binding beyond localhost. This is not recommended.",
    )
    args = parser.parse_args()
    if not args.allow_non_loopback and args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("Refusing non-loopback bind without --allow-non-loopback")
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535")

    runtime = Sam3Runtime()
    Sam3Handler.runtime = runtime
    Sam3Handler.bearer_token = os.environ.get(args.token_env)
    server = ThreadingHTTPServer((args.host, args.port), Sam3Handler)
    print(
        f"SAM 3 sidecar listening on http://{args.host}:{args.port}; "
        f"token={'enabled' if Sam3Handler.bearer_token else 'disabled'}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
