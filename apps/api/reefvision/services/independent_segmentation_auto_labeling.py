"""Independent SAM 3, VLM detector, and SAM 2 mask consensus pipeline."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request
from uuid import uuid4

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    ModelRegistration,
    PredictionProposal,
    Project,
)
from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import PixelBox
from reefvision.ml.sam_adapters import SAM2ImageAssistProvider
from reefvision.services.mask_consensus import (
    IndependentMaskCandidate,
    MaskAggregation,
    MaskConsensusGroup,
    build_mask_consensus,
)
from reefvision.services.multi_model_auto_labeling import MaskVote, _promote, _proposal_mask
from reefvision.storage.masks import remove_prediction_mask_png, write_prediction_mask_png
from reefvision.storage.models import resolve_verified_model_path
from reefvision.storage.projects import resolve_managed_project_path

_DETECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "detections": {
            "type": "array",
            "maxItems": 1000,
            "items": {
                "type": "object",
                "properties": {
                    "x_min": {"type": "number"},
                    "y_min": {"type": "number"},
                    "x_max": {"type": "number"},
                    "y_max": {"type": "number"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["x_min", "y_min", "x_max", "y_max", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["detections"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class VLMBoxDetection:
    detection_id: str
    branch_id: str
    model_name: str
    confidence: float
    box: PixelBox


@dataclass(frozen=True, slots=True)
class IndependentAutoLabelImageResult:
    image_id: str
    primary_candidate_count: int
    vlm_detection_count: int
    refined_mask_count: int
    consensus_count: int
    proposal_ids: tuple[str, ...]
    accepted_mask_annotation_ids: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndependentAutoLabelBatchResult:
    image_count: int
    consensus_count: int
    proposal_count: int
    accepted_count: int
    failed_image_count: int
    images: tuple[IndependentAutoLabelImageResult, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "image_count": self.image_count,
            "consensus_count": self.consensus_count,
            "proposal_count": self.proposal_count,
            "accepted_count": self.accepted_count,
            "failed_image_count": self.failed_image_count,
            "images": [asdict(item) for item in self.images],
        }


class VLMBoxDetector(Protocol):
    branch_id: str
    model_name: str

    def detect(
        self,
        *,
        image_png: bytes,
        width: int,
        height: int,
        concept_prompt: str,
        minimum_confidence: float,
    ) -> list[VLMBoxDetection]: ...


class BoxMaskRefiner(Protocol):
    model_id: str
    model_checksum: str

    def refine(
        self,
        *,
        image_id: str,
        image_path: Path,
        class_key: str,
        detections: list[VLMBoxDetection],
    ) -> list[IndependentMaskCandidate]: ...

    def close(self) -> None: ...


def _post_json(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = url_request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with url_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except url_error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"Remote detector failed with HTTP {exc.code}: {body}") from exc
    except (url_error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Remote detector request failed: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Remote detector returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Remote detector returned an unexpected response")
    return value


def _openai_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in payload.get("output", []) if isinstance(payload.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if isinstance(part, dict):
                text = part.get("text") or part.get("output_text")
                if isinstance(text, str) and text.strip():
                    return text
    raise RuntimeError("OpenAI did not return detector output")


def _gemini_text(payload: dict[str, Any]) -> str:
    for candidate in (
        payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []
    ):
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        for part in content.get("parts", []) if isinstance(content.get("parts"), list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text = str(part["text"]).strip()
                if text:
                    return text
    raise RuntimeError("Gemini did not return detector output")


def _instruction(concept_prompt: str, width: int, height: int) -> str:
    return (
        "Detect every visually distinct instance of the requested concept. Return one tight "
        "axis-aligned bounding box per instance in source-image pixel coordinates. Do not "
        "invent occluded or uncertain objects. The image coordinate origin is the upper-left; "
        f"width={width}, height={height}. Requested concept: {concept_prompt!r}. Return only "
        "the required JSON document."
    )


def _parse_detections(
    text: str,
    *,
    branch_id: str,
    model_name: str,
    width: int,
    height: int,
    minimum_confidence: float,
) -> list[VLMBoxDetection]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        document = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{branch_id} returned invalid detection JSON") from exc
    rows = document.get("detections") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"{branch_id} detection output has no detections array")
    detections: list[VLMBoxDetection] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        try:
            x_min = float(row["x_min"])
            y_min = float(row["y_min"])
            x_max = float(row["x_max"])
            y_max = float(row["y_max"])
            confidence = float(row["confidence"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= confidence <= 1 or confidence < minimum_confidence:
            continue
        if not (0 <= x_min < x_max <= width and 0 <= y_min < y_max <= height):
            continue
        detections.append(
            VLMBoxDetection(
                detection_id=f"{branch_id}-{index:05d}",
                branch_id=branch_id,
                model_name=model_name,
                confidence=confidence,
                box=PixelBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
            )
        )
    return detections


class OpenAIBoxDetector:
    branch_id = "openai_sam2"

    def __init__(self, settings: Settings, model_name: str) -> None:
        self.settings = settings
        self.model_name = model_name

    def detect(
        self,
        *,
        image_png: bytes,
        width: int,
        height: int,
        concept_prompt: str,
        minimum_confidence: float,
    ) -> list[VLMBoxDetection]:
        if not self.settings.openai_api_key:
            raise RuntimeError("REEFVISION_OPENAI_API_KEY is not configured")
        payload = {
            "model": self.model_name,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _instruction(concept_prompt, width, height)},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,"
                            + base64.b64encode(image_png).decode("ascii"),
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "reefvision_vlm_detections",
                    "strict": True,
                    "schema": _DETECTION_SCHEMA,
                }
            },
        }
        response = _post_json(
            url="https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            payload=payload,
            timeout_seconds=self.settings.remote_vision_timeout_seconds,
        )
        return _parse_detections(
            _openai_text(response),
            branch_id=self.branch_id,
            model_name=self.model_name,
            width=width,
            height=height,
            minimum_confidence=minimum_confidence,
        )


class GeminiBoxDetector:
    branch_id = "gemini_sam2"

    def __init__(self, settings: Settings, model_name: str) -> None:
        self.settings = settings
        self.model_name = model_name

    def detect(
        self,
        *,
        image_png: bytes,
        width: int,
        height: int,
        concept_prompt: str,
        minimum_confidence: float,
    ) -> list[VLMBoxDetection]:
        if not self.settings.gemini_api_key:
            raise RuntimeError("REEFVISION_GEMINI_API_KEY is not configured")
        model = url_parse.quote(self.model_name, safe="-._")
        query = url_parse.urlencode({"key": self.settings.gemini_api_key})
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": _instruction(concept_prompt, width, height)},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(image_png).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": _DETECTION_SCHEMA,
            },
        }
        response = _post_json(
            url=(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?{query}"
            ),
            headers={},
            payload=payload,
            timeout_seconds=self.settings.remote_vision_timeout_seconds,
        )
        return _parse_detections(
            _gemini_text(response),
            branch_id=self.branch_id,
            model_name=self.model_name,
            width=width,
            height=height,
            minimum_confidence=minimum_confidence,
        )


class SAM2BoxRefiner:
    def __init__(
        self,
        settings: Settings,
        model: ModelRegistration,
        *,
        device: str,
    ) -> None:
        if model.purpose != "assist" or model.task != "assist_segmentation":
            raise ValidationError("Independent VLM refinement requires a Prompt Assist model")
        if model.provider_name.strip().casefold() != "sam2":
            raise ValidationError("Independent VLM refinement currently requires a SAM 2 model")
        self.model_id = model.id
        self.model_checksum = model.sha256
        self.provider = SAM2ImageAssistProvider()
        model_path = resolve_verified_model_path(
            settings,
            model.managed_path,
            expected_sha256=model.sha256,
        )
        self.provider.load_model(model_path, device)

    def refine(
        self,
        *,
        image_id: str,
        image_path: Path,
        class_key: str,
        detections: list[VLMBoxDetection],
    ) -> list[IndependentMaskCandidate]:
        prepared = self.provider.prepare_image(image_path)
        candidates: list[IndependentMaskCandidate] = []
        for detection in detections:
            prediction = self.provider.predict_from_box(prepared, detection.box)
            candidates.append(
                IndependentMaskCandidate(
                    candidate_id=detection.detection_id,
                    branch_id=detection.branch_id,
                    image_id=image_id,
                    class_key=class_key,
                    confidence=float((detection.confidence + prediction.score) / 2.0),
                    mask=np.asarray(prediction.mask, dtype=bool),
                    provenance={
                        "detector_model": detection.model_name,
                        "detector_confidence": detection.confidence,
                        "detector_box": [
                            detection.box.x_min,
                            detection.box.y_min,
                            detection.box.x_max,
                            detection.box.y_max,
                        ],
                        "sam2_model_id": self.model_id,
                        "sam2_model_checksum": self.model_checksum,
                        "sam2_score": prediction.score,
                    },
                )
            )
        return candidates

    def close(self) -> None:
        self.provider.unload_model()


def _source_png(path: Path) -> tuple[bytes, int, int]:
    with Image.open(path) as source:
        source.load()
        rgb = source.convert("RGB")
    output = BytesIO()
    rgb.save(output, format="PNG", optimize=True)
    return output.getvalue(), rgb.width, rgb.height


def _group_proposal(
    settings: Settings,
    session: Session,
    *,
    project: Project,
    image: ImageAsset,
    group: MaskConsensusGroup,
    source_model: ModelRegistration,
    inference_job_id: str,
    label_class_id: str,
    predicted_label: str,
    workflow_run_id: str,
    workflow_node_id: str,
    source_candidates: dict[str, IndependentMaskCandidate],
) -> PredictionProposal:
    proposal_id = str(uuid4())
    png = BytesIO()
    Image.fromarray(np.asarray(group.mask, dtype=np.uint8) * 255, mode="L").save(
        png,
        format="PNG",
        optimize=True,
    )
    stored = write_prediction_mask_png(
        settings,
        project_storage_root=project.storage_root,
        proposal_id=proposal_id,
        png_bytes=png.getvalue(),
        expected_width=image.width_px,
        expected_height=image.height_px,
    )
    proposal = PredictionProposal(
        id=proposal_id,
        project_id=project.id,
        image_id=image.id,
        model_id=source_model.id,
        inference_job_id=inference_job_id,
        model_checksum=source_model.sha256,
        label_class_id=label_class_id,
        predicted_label=predicted_label,
        predicted_index=None,
        confidence=group.confidence,
        geometry_kind="raster_mask",
        polygon_json=None,
        mask_path=stored.relative_path,
        mask_content_sha256=stored.content_sha256,
        x_min=stored.x_min,
        y_min=stored.y_min,
        x_max=stored.x_max,
        y_max=stored.y_max,
        review_status="pending",
        inference_settings_json={
            "consensus_mode": "independent_masks",
            "required_votes": group.required_votes,
            "aggregation": group.aggregation,
        },
        provenance_json={
            "workflow_run_id": workflow_run_id,
            "workflow_node_id": workflow_node_id,
            "consensus_method": "independent_mask_generation",
            "required_votes": group.required_votes,
            "aggregation": group.aggregation,
            "candidate_ids": list(group.candidate_ids),
            "branch_ids": list(group.branch_ids),
            "pairwise_mask_iou": dict(group.pairwise_iou),
            "candidate_provenance": {
                candidate_id: dict(source_candidates[candidate_id].provenance)
                for candidate_id in group.candidate_ids
            },
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    try:
        session.add(proposal)
        session.flush()
    except Exception:
        remove_prediction_mask_png(
            settings,
            project_storage_root=project.storage_root,
            proposal_id=proposal_id,
            relative_path=stored.relative_path,
        )
        raise
    return proposal


def run_independent_segmentation_auto_labeling(
    settings: Settings,
    factory: sessionmaker[Session],
    *,
    primary_prediction_ids: list[str],
    primary_model_id: str,
    primary_inference_job_id: str,
    sam2_model_id: str,
    label_class_id: str,
    predicted_label: str,
    concept_prompt: str,
    workflow_run_id: str,
    workflow_node_id: str,
    required_votes: int = 2,
    iou_threshold: float = 0.3,
    aggregation: MaskAggregation = "pixel_majority",
    minimum_vlm_confidence: float = 0.25,
    device: str = "auto",
    auto_accept: bool = False,
    fail_closed: bool = True,
    detectors: list[VLMBoxDetector] | None = None,
    refiner: BoxMaskRefiner | None = None,
) -> IndependentAutoLabelBatchResult:
    """Run independent VLM detections, SAM 2 refinement, and mask consensus."""

    if settings.safe_mode:
        raise ValidationError("Remote independent auto-labeling is disabled in safe mode")
    if not settings.allow_remote_vision:
        raise ValidationError(
            "Independent VLM auto-labeling requires REEFVISION_ALLOW_REMOTE_VISION=true"
        )
    if not concept_prompt.strip():
        raise ValidationError("Independent auto-labeling requires a concept prompt")

    with factory() as session:
        primary_model = session.get(ModelRegistration, primary_model_id)
        sam2_model = session.get(ModelRegistration, sam2_model_id)
        if primary_model is None or sam2_model is None:
            raise ValidationError("Independent auto-labeling references a missing model")
        proposals = [
            proposal
            for proposal_id in dict.fromkeys(primary_prediction_ids)
            if (proposal := session.get(PredictionProposal, proposal_id)) is not None
        ]
        project_ids = {proposal.project_id for proposal in proposals}
        if len(project_ids) > 1:
            raise ValidationError("Independent auto-labeling proposals must share one project")
        image_ids = sorted({proposal.image_id for proposal in proposals})
        if not image_ids:
            raise ValidationError("Independent auto-labeling requires primary image proposals")

    configured_detectors = detectors or [
        GeminiBoxDetector(settings, "gemini-2.5-flash"),
        OpenAIBoxDetector(settings, "gpt-5-mini"),
    ]
    if len({item.branch_id for item in configured_detectors}) != len(configured_detectors):
        raise ValidationError("Independent detector branch IDs must be unique")
    owned_refiner = refiner is None
    active_refiner = refiner or SAM2BoxRefiner(settings, sam2_model, device=device)
    image_results: list[IndependentAutoLabelImageResult] = []
    failed_images = 0
    try:
        for image_id in image_ids:
            warnings: list[str] = []
            created_proposal_ids: list[str] = []
            accepted_ids: list[str] = []
            try:
                with factory() as session:
                    image = session.get(ImageAsset, image_id)
                    if image is None:
                        raise ValidationError("Independent auto-labeling image is missing")
                    project = session.get(Project, image.project_id)
                    if project is None:
                        raise ValidationError("Independent auto-labeling project is missing")
                    image_path = resolve_managed_project_path(settings, image.managed_path)
                    primary_for_image = [item for item in proposals if item.image_id == image_id]
                    primary_candidates = [
                        IndependentMaskCandidate(
                            candidate_id=item.id,
                            branch_id="sam3",
                            image_id=image.id,
                            class_key=predicted_label,
                            confidence=float(item.confidence),
                            mask=np.asarray(
                                _proposal_mask(
                                    settings,
                                    proposal=item,
                                    project=project,
                                    image=image,
                                ),
                                dtype=np.uint8,
                            )
                            > 0,
                            provenance={
                                "source_prediction_id": item.id,
                                "source_model_id": item.model_id,
                                "source_model_checksum": item.model_checksum,
                                "source_inference_job_id": item.inference_job_id,
                                "source_predicted_label": item.predicted_label,
                            },
                        )
                        for item in primary_for_image
                    ]
                image_png, width, height = _source_png(image_path)
                detections: list[VLMBoxDetection] = []
                for detector in configured_detectors:
                    try:
                        detections.extend(
                            detector.detect(
                                image_png=image_png,
                                width=width,
                                height=height,
                                concept_prompt=concept_prompt,
                                minimum_confidence=minimum_vlm_confidence,
                            )
                        )
                    except Exception as exc:
                        if not fail_closed:
                            raise
                        warnings.append(f"{detector.branch_id} failed: {exc}")
                refined = active_refiner.refine(
                    image_id=image_id,
                    image_path=image_path,
                    class_key=predicted_label,
                    detections=detections,
                )
                all_candidates = [*primary_candidates, *refined]
                consensus = build_mask_consensus(
                    all_candidates,
                    required_votes=required_votes,
                    iou_threshold=iou_threshold,
                    aggregation=aggregation,
                )
                warnings.extend(consensus.warnings)
                candidate_by_id = {item.candidate_id: item for item in all_candidates}
                with factory() as session:
                    image = session.get(ImageAsset, image_id)
                    project = session.get(Project, image.project_id) if image is not None else None
                    model = session.get(ModelRegistration, primary_model_id)
                    if image is None or project is None or model is None:
                        raise ValidationError("Independent consensus persistence context is missing")
                    for group in consensus.groups:
                        proposal = _group_proposal(
                            settings,
                            session,
                            project=project,
                            image=image,
                            group=group,
                            source_model=model,
                            inference_job_id=primary_inference_job_id,
                            label_class_id=label_class_id,
                            predicted_label=predicted_label,
                            workflow_run_id=workflow_run_id,
                            workflow_node_id=workflow_node_id,
                            source_candidates=candidate_by_id,
                        )
                        created_proposal_ids.append(proposal.id)
                    session.commit()
                if auto_accept:
                    for proposal_id, group in zip(
                        created_proposal_ids,
                        consensus.groups,
                        strict=True,
                    ):
                        votes = [
                            MaskVote(
                                voter=branch_id,
                                model=branch_id,
                                accepted=True,
                                confidence=group.confidence,
                                reason="Independent branch mask participated in consensus.",
                            )
                            for branch_id in group.branch_ids
                        ]
                        accepted_ids.append(
                            _promote(
                                settings,
                                factory,
                                proposal_id=proposal_id,
                                votes=votes,
                                required_votes=required_votes,
                                concept_prompt=concept_prompt,
                                workflow_run_id=workflow_run_id,
                                workflow_node_id=workflow_node_id,
                            )
                        )
                image_results.append(
                    IndependentAutoLabelImageResult(
                        image_id=image_id,
                        primary_candidate_count=len(primary_candidates),
                        vlm_detection_count=len(detections),
                        refined_mask_count=len(refined),
                        consensus_count=len(consensus.groups),
                        proposal_ids=tuple(created_proposal_ids),
                        accepted_mask_annotation_ids=tuple(accepted_ids),
                        warnings=tuple(warnings),
                    )
                )
            except Exception as exc:
                failed_images += 1
                if not fail_closed:
                    raise
                image_results.append(
                    IndependentAutoLabelImageResult(
                        image_id=image_id,
                        primary_candidate_count=0,
                        vlm_detection_count=0,
                        refined_mask_count=0,
                        consensus_count=0,
                        proposal_ids=(),
                        accepted_mask_annotation_ids=(),
                        warnings=(str(exc),),
                    )
                )
    finally:
        if owned_refiner:
            active_refiner.close()

    return IndependentAutoLabelBatchResult(
        image_count=len(image_results),
        consensus_count=sum(item.consensus_count for item in image_results),
        proposal_count=sum(len(item.proposal_ids) for item in image_results),
        accepted_count=sum(len(item.accepted_mask_annotation_ids) for item in image_results),
        failed_image_count=failed_images,
        images=tuple(image_results),
    )
