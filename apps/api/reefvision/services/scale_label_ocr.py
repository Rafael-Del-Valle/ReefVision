"""Opt-in printed scale-label OCR proposals for measurement calibration."""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.optional_transformers_runtime import (
    OPTIONAL_MODEL_SPECS,
    ensure_optional_model,
    resolve_torch_device,
)
from reefvision.repositories.images import ImageRepository
from reefvision.schemas.image_calibration import CalibrationRoi
from reefvision.schemas.scale_label_ocr import ScaleLabelOcrCandidate, ScaleLabelOcrRequest
from reefvision.storage.projects import resolve_managed_project_path

_SCALE_PATTERN = re.compile(
    r"(?P<value>(?:\d+(?:[.,]\d+)?|[.,]\d+))\s*(?P<unit>µm|μm|um|mm|cm|nm|m)\b",
    re.IGNORECASE,
)
_UNIT_MAP = {
    "µm": "µm",
    "μm": "µm",
    "um": "µm",
    "mm": "mm",
    "cm": "cm",
    "nm": "nm",
    "m": "m",
}


@dataclass(frozen=True, slots=True)
class ParsedScaleLabel:
    value: float
    unit: str
    normalized_unit: str


def parse_scale_label(text: str) -> ParsedScaleLabel | None:
    cleaned = text.strip().replace("μ", "µ")
    match = _SCALE_PATTERN.search(cleaned)
    if match is None:
        return None
    value = float(match.group("value").replace(",", "."))
    if value <= 0:
        return None
    unit = match.group("unit").lower().replace("μ", "µ")
    normalized = _UNIT_MAP.get(unit)
    if normalized is None:
        return None
    return ParsedScaleLabel(value=value, unit=match.group("unit"), normalized_unit=normalized)


def _roi_candidates(image: Image.Image, requested: CalibrationRoi | None) -> list[CalibrationRoi]:
    width, height = image.size
    if requested is not None:
        if requested.x_max > width or requested.y_max > height:
            raise ValidationError("Scale-label OCR ROI exceeds image bounds")
        return [requested]
    # Scale labels commonly sit near image borders. These crops cover likely locations
    # without OCR-scanning the whole image pixel-by-pixel.
    return [
        CalibrationRoi(x_min=0, y_min=height * 0.62, x_max=width, y_max=height),
        CalibrationRoi(x_min=0, y_min=0, x_max=width, y_max=height * 0.28),
        CalibrationRoi(x_min=0, y_min=height * 0.45, x_max=width * 0.45, y_max=height),
        CalibrationRoi(x_min=width * 0.55, y_min=height * 0.45, x_max=width, y_max=height),
    ]


def _crop(image: Image.Image, roi: CalibrationRoi) -> Image.Image:
    region = image.crop((round(roi.x_min), round(roi.y_min), round(roi.x_max), round(roi.y_max)))
    gray = ImageOps.autocontrast(region.convert("L"))
    return gray.convert("RGB")


class ScaleLabelOcrService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.images = ImageRepository(session)
        self.settings = settings

    def detect(self, image_id: str, request: ScaleLabelOcrRequest) -> ScaleLabelOcrCandidate:
        image_record = self.images.get_basic(image_id)
        if image_record is None:
            raise NotFoundError("Image not found")
        image_path = resolve_managed_project_path(self.settings, image_record.managed_path)
        if not image_path.is_file():
            raise ValidationError("The managed image file is missing")

        model_path = ensure_optional_model(
            self.settings,
            "scale_label_ocr",
            allow_download=request.allow_model_download,
        )
        spec = OPTIONAL_MODEL_SPECS["scale_label_ocr"]
        try:
            import torch
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        except Exception as exc:
            raise ValidationError(f"TrOCR runtime is unavailable: {exc}") from exc

        device = resolve_torch_device("auto")
        processor = TrOCRProcessor.from_pretrained(model_path, local_files_only=True)
        model = VisionEncoderDecoderModel.from_pretrained(model_path, local_files_only=True).to(
            device
        )
        model.eval()

        with Image.open(image_path) as source:
            source.load()
            image = source.convert("RGB")

        best: tuple[float, str, ParsedScaleLabel | None, CalibrationRoi] | None = None
        for roi in _roi_candidates(image, request.roi):
            crop = _crop(image, roi)
            pixel_values = processor(images=crop, return_tensors="pt").pixel_values.to(device)
            with torch.no_grad():
                generated = model.generate(
                    pixel_values,
                    max_new_tokens=24,
                    return_dict_in_generate=True,
                    output_scores=True,
                )
            text = processor.batch_decode(generated.sequences, skip_special_tokens=True)[0].strip()
            parsed = parse_scale_label(text)
            token_confidence = 0.0
            scores = list(generated.scores or [])
            if scores:
                maxima = [float(torch.softmax(score[0], dim=-1).max().item()) for score in scores]
                token_confidence = sum(maxima) / len(maxima)
            confidence = min(1.0, token_confidence * (1.0 if parsed else 0.55))
            rank = confidence + (0.35 if parsed else 0.0)
            if best is None or rank > best[0]:
                best = (rank, text, parsed, roi)

        if best is None:
            raise ValidationError("Scale-label OCR did not produce a candidate")
        _, text, parsed, roi = best
        warnings: list[str] = []
        if parsed is None:
            warnings.append(
                "OCR text did not contain a supported physical scale value "
                "and unit; review the text manually."
            )
        else:
            warnings.append(
                "OCR is advisory. Confirm the printed value/unit and the "
                "detected scale-bar geometry before applying calibration."
            )
        confidence = 0.9 if parsed is not None else 0.45
        return ScaleLabelOcrCandidate(
            image_id=image_id,
            raw_text=text,
            parsed_value=parsed.value if parsed else None,
            parsed_unit=parsed.unit if parsed else None,
            normalized_unit=parsed.normalized_unit if parsed else None,
            roi=roi,
            confidence=confidence,
            model_id=spec.repo_id,
            model_revision=spec.revision,
            warnings=warnings,
        )
