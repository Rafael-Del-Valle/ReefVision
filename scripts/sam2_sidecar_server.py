"""Run SAM 2 interactive refinement in an isolated localhost process.

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
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field


class SegmentBoxRequest(BaseModel):
    image_png_base64: str = Field(min_length=1)
    box: list[float] = Field(min_length=4, max_length=4)
    device: str = "auto"


class SegmentPointsRequest(BaseModel):
    image_png_base64: str = Field(min_length=1)
    positive_points: list[list[float]] = Field(default_factory=list, max_length=10000)
    negative_points: list[list[float]] = Field(default_factory=list, max_length=10000)
    context_box: list[float] | None = None
    device: str = "auto"


class SegmentResponse(BaseModel):
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


def _validated_box(
    values: list[float] | None,
    *,
    width: int,
    height: int,
    required: bool,
) -> np.ndarray | None:
    if values is None:
        if required:
            raise HTTPException(status_code=422, detail="Box prompt is required")
        return None
    if len(values) != 4:
        raise HTTPException(status_code=422, detail="Box prompt must contain four values")
    x_min, y_min, x_max, y_max = (float(value) for value in values)
    if not all(isfinite(value) for value in (x_min, y_min, x_max, y_max)) or not (
        0 <= x_min < x_max <= width and 0 <= y_min < y_max <= height
    ):
        raise HTTPException(status_code=422, detail="Box prompt is outside the image")
    return np.asarray([x_min, y_min, x_max, y_max], dtype=np.float32)


def _validated_points(
    values: list[list[float]],
    *,
    width: int,
    height: int,
    label: str,
) -> list[list[float]]:
    output: list[list[float]] = []
    for value in values:
        if len(value) != 2:
            raise HTTPException(
                status_code=422,
                detail=f"{label} point prompts must contain x and y",
            )
        x, y = (float(component) for component in value)
        if not (isfinite(x) and isfinite(y)) or not (0 <= x < width and 0 <= y < height):
            raise HTTPException(
                status_code=422,
                detail=f"{label} point prompt is outside the image",
            )
        output.append([x, y])
    return output


def _best_prediction(
    masks: Any,
    scores: Any,
    *,
    width: int,
    height: int,
) -> tuple[np.ndarray, float]:
    masks_array = np.asarray(masks)
    scores_array = np.asarray(scores, dtype=np.float64).reshape(-1)
    if masks_array.ndim < 3 or len(masks_array) == 0:
        raise HTTPException(status_code=422, detail="SAM 2 returned no mask")
    if len(scores_array) == len(masks_array):
        order = np.argsort(scores_array)[::-1]
    else:
        order = np.arange(len(masks_array))
    for raw_index in order:
        index = int(raw_index)
        mask = np.asarray(masks_array[index], dtype=bool)
        if mask.shape == (height, width) and bool(mask.any()):
            score = float(scores_array[index]) if index < len(scores_array) else 0.0
            return mask, max(0.0, min(1.0, score))
    raise HTTPException(status_code=422, detail="SAM 2 returned an invalid mask")


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
            raise RuntimeError("Meta SAM 2 is not installed in this sidecar environment") from exc
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
        version="1.1",
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
            "capabilities": ["box_prompt", "point_prompt", "negative_points", "context_box"],
        }

    @app.post("/segment-box", response_model=SegmentResponse)
    def segment_box(
        payload: SegmentBoxRequest,
        _authorized: None = Depends(authorize),
    ) -> SegmentResponse:
        _resolve_device(payload.device, configured_device)
        image = _decode_image(payload.image_png_base64)
        height, width = image.shape[:2]
        box = _validated_box(payload.box, width=width, height=height, required=True)
        predictor = state.get("predictor")
        if predictor is None:
            raise HTTPException(status_code=503, detail="SAM 2 predictor is not loaded")
        predictor.set_image(image)
        masks, scores, _logits = predictor.predict(
            point_coords=None,
            point_labels=None,
            box=box,
            multimask_output=False,
        )
        mask, score = _best_prediction(masks, scores, width=width, height=height)
        return SegmentResponse(
            mask_png_base64=_encode_mask(mask),
            score=score,
            model_version=str(state.get("model_version", "sam2")),
        )

    @app.post("/segment-points", response_model=SegmentResponse)
    def segment_points(
        payload: SegmentPointsRequest,
        _authorized: None = Depends(authorize),
    ) -> SegmentResponse:
        _resolve_device(payload.device, configured_device)
        image = _decode_image(payload.image_png_base64)
        height, width = image.shape[:2]
        positive = _validated_points(
            payload.positive_points,
            width=width,
            height=height,
            label="Positive",
        )
        negative = _validated_points(
            payload.negative_points,
            width=width,
            height=height,
            label="Negative",
        )
        context_box = _validated_box(
            payload.context_box,
            width=width,
            height=height,
            required=False,
        )
        if not positive and context_box is None:
            raise HTTPException(
                status_code=422,
                detail="Point prompting requires a positive point or context box",
            )
        points = [*positive, *negative]
        point_coords = np.asarray(points, dtype=np.float32) if points else None
        point_labels = (
            np.asarray([1] * len(positive) + [0] * len(negative), dtype=np.int32)
            if points
            else None
        )
        predictor = state.get("predictor")
        if predictor is None:
            raise HTTPException(status_code=503, detail="SAM 2 predictor is not loaded")
        predictor.set_image(image)
        masks, scores, _logits = predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            box=context_box,
            multimask_output=True,
        )
        mask, score = _best_prediction(masks, scores, width=width, height=height)
        return SegmentResponse(
            mask_png_base64=_encode_mask(mask),
            score=score,
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
