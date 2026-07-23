"""Run SAM 2 box-prompt refinement in an isolated localhost process.

Install Meta SAM 2 and its dependencies in a separate environment, then run:

python scripts/sam2_sidecar_server.py \
  --config configs/sam2.1/sam2.1_hiera_l.yaml \
  --checkpoint checkpoints/sam2.1_hiera_large.pt \
  --device cuda:0
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import os
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError


class SegmentBoxRequest(BaseModel):
    image_png_base64: str = Field(min_length=1)
    box: list[float] = Field(min_length=4, max_length=4)
    device: str = "auto"


class SegmentBoxResponse(BaseModel):
    mask_png_base64: str
    score: float
    model_version: str


def _decode_image(encoded: str) -> np.ndarray:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Image is not valid base64") from exc
    try:
        with Image.open(BytesIO(raw)) as source:
            source.load()
            rgb = source.convert("RGB")
            return np.asarray(rgb, dtype=np.uint8)
    except (OSError, UnidentifiedImageError) as exc:
        raise HTTPException(status_code=422, detail="Image is not a readable PNG") from exc


def _encode_mask(mask: np.ndarray) -> str:
    output = BytesIO()
    Image.fromarray(np.asarray(mask, dtype=np.uint8) * 255, mode="L").save(
        output,
        format="PNG",
        optimize=True,
    )
    return base64.b64encode(output.getvalue()).decode("ascii")


def _resolve_device(requested: str, configured: str) -> str:
    normalized = requested.strip().casefold()
    if normalized in {"", "auto"}:
        return configured
    if normalized == configured.casefold():
        return configured
    raise HTTPException(
        status_code=422,
        detail=(
            "The sidecar process is already bound to its configured device; "
            "start another sidecar for a different CUDA device."
        ),
    )


def build_app(
    *,
    config_path: Path,
    checkpoint_path: Path,
    configured_device: str,
    token: str | None,
) -> FastAPI:
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
        except Exception as exc:
            raise RuntimeError(
                "Meta SAM 2 is not installed in this sidecar environment"
            ) from exc
        if not config_path.is_file():
            raise RuntimeError(f"SAM 2 config is missing: {config_path}")
        if not checkpoint_path.is_file():
            raise RuntimeError(f"SAM 2 checkpoint is missing: {checkpoint_path}")
        model = build_sam2(
            str(config_path),
            str(checkpoint_path),
            device=configured_device,
        )
        state["predictor"] = SAM2ImagePredictor(model)
        state["model_version"] = checkpoint_path.name
        try:
            yield
        finally:
            state.clear()

    app = FastAPI(
        title="ReefVision SAM 2 Sidecar",
        version="1.0",
        lifespan=lifespan,
    )

    def authorize(authorization: str | None = Header(default=None)) -> None:
        if token is None:
            return
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid sidecar token")

    @app.get("/health")
    def health(_authorized: None = Depends(authorize)) -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": "sam2_sidecar",
            "model_version": state.get("model_version"),
            "device": configured_device,
        }

    @app.post("/segment-box", response_model=SegmentBoxResponse)
    def segment_box(
        payload: SegmentBoxRequest,
        _authorized: None = Depends(authorize),
    ) -> SegmentBoxResponse:
        _resolve_device(payload.device, configured_device)
        image = _decode_image(payload.image_png_base64)
        height, width = image.shape[:2]
        x_min, y_min, x_max, y_max = (float(value) for value in payload.box)
        if not (0 <= x_min < x_max <= width and 0 <= y_min < y_max <= height):
            raise HTTPException(status_code=422, detail="Box prompt is outside the image")
        predictor = state.get("predictor")
        if predictor is None:
            raise HTTPException(status_code=503, detail="SAM 2 predictor is not loaded")
        predictor.set_image(image)
        masks, scores, _logits = predictor.predict(
            point_coords=None,
            point_labels=None,
            box=np.asarray([x_min, y_min, x_max, y_max], dtype=np.float32),
            multimask_output=False,
        )
        if len(masks) == 0:
            raise HTTPException(status_code=422, detail="SAM 2 returned no mask")
        mask = np.asarray(masks[0], dtype=bool)
        if mask.shape != (height, width) or not bool(mask.any()):
            raise HTTPException(status_code=422, detail="SAM 2 returned an invalid mask")
        score = float(scores[0]) if len(scores) else 0.0
        return SegmentBoxResponse(
            mask_png_base64=_encode_mask(mask),
            score=max(0.0, min(1.0, score)),
            model_version=str(state.get("model_version", "sam2")),
        )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--token-env",
        default="REEFVISION_SAM2_SIDECAR_TOKEN",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("The SAM 2 sidecar must bind to localhost")
    token = os.environ.get(args.token_env)
    app = build_app(
        config_path=args.config.resolve(),
        checkpoint_path=args.checkpoint.resolve(),
        configured_device=args.device,
        token=token,
    )
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
