"""Consensus-driven multi-model segmentation auto-labeling.

A primary segmenter proposes source-aligned masks. Remote vision reviewers cast
independent semantic quality votes. Only candidates reaching the configured
quorum are promoted to verified raster mask annotations.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Protocol
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request
from uuid import uuid4

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    MaskAnnotation,
    MaskAnnotationEvent,
    PredictionProposal,
    Project,
)
from reefvision.domain.errors import ValidationError
from reefvision.services.annotations import mask_annotation_snapshot
from reefvision.storage.masks import (
    remove_mask_annotation_png,
    resolve_prediction_mask_png,
    write_mask_png,
)
from reefvision.storage.projects import resolve_managed_project_path

_REMOTE_VOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "accept": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["accept", "confidence", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class MaskVote:
    voter: str
    model: str
    accepted: bool
    confidence: float
    reason: str
    error: str | None = None


@dataclass(frozen=True)
class ConsensusCandidateResult:
    proposal_id: str
    image_id: str
    accepted_vote_count: int
    required_votes: int
    consensus_reached: bool
    auto_promoted: bool
    mask_annotation_id: str | None
    votes: list[MaskVote]


@dataclass(frozen=True)
class ConsensusBatchResult:
    requested_count: int
    evaluated_count: int
    consensus_count: int
    promoted_count: int
    pending_count: int
    failed_count: int
    candidates: list[ConsensusCandidateResult]

    def as_payload(self) -> dict[str, Any]:
        return {
            "requested_count": self.requested_count,
            "evaluated_count": self.evaluated_count,
            "consensus_count": self.consensus_count,
            "promoted_count": self.promoted_count,
            "pending_count": self.pending_count,
            "failed_count": self.failed_count,
            "candidates": [
                {
                    **asdict(candidate),
                    "votes": [asdict(vote) for vote in candidate.votes],
                }
                for candidate in self.candidates
            ],
        }


class MaskVoter(Protocol):
    voter_name: str
    model_name: str

    def vote(
        self,
        *,
        prompt: str,
        candidate_label: str,
        source_crop_png: bytes,
        overlay_crop_png: bytes,
    ) -> MaskVote: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _bounded_float(value: Any, *, default: float, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number") from exc
    if not 0 <= result <= 1:
        raise ValidationError(f"{name} must be between 0 and 1")
    return result


def _configuration(raw: dict[str, Any]) -> dict[str, Any]:
    required_votes = int(raw.get("required_votes", 2))
    if required_votes not in {2, 3}:
        raise ValidationError("Consensus required_votes must be 2 or 3")
    prompt = str(raw.get("prompt", "")).strip()
    if not prompt:
        raise ValidationError("Consensus auto-labeling requires a non-empty concept prompt")
    return {
        "required_votes": required_votes,
        "prompt": prompt,
        "sam_vote_threshold": _bounded_float(
            raw.get("sam_vote_threshold", 0.35),
            default=0.35,
            name="sam_vote_threshold",
        ),
        "minimum_reviewer_confidence": _bounded_float(
            raw.get("minimum_reviewer_confidence", 0.60),
            default=0.60,
            name="minimum_reviewer_confidence",
        ),
        "auto_accept": bool(raw.get("auto_accept", True)),
        "allow_remote_review": bool(raw.get("allow_remote_review", False)),
        "fail_closed": bool(raw.get("fail_closed", True)),
        "crop_padding_fraction": _bounded_float(
            raw.get("crop_padding_fraction", 0.10),
            default=0.10,
            name="crop_padding_fraction",
        ),
        "openai_model": str(raw.get("openai_model", "gpt-5-mini")).strip(),
        "gemini_model": str(raw.get("gemini_model", "gemini-2.5-flash")).strip(),
    }


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
        raise RuntimeError(f"Remote vision request failed with HTTP {exc.code}: {body}") from exc
    except (url_error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Remote vision request failed: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Remote vision provider returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Remote vision provider returned an unexpected response")
    return parsed


def _extract_openai_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text") or part.get("output_text")
                if isinstance(text, str) and text.strip():
                    return text
    raise RuntimeError("OpenAI did not return a structured vote")


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text = str(part["text"]).strip()
                    if text:
                        return text
    raise RuntimeError("Gemini did not return a structured vote")


def _parse_vote(text: str, *, voter: str, model: str) -> MaskVote:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{voter} returned an invalid vote document") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{voter} returned an invalid vote document")
    accepted = value.get("accept")
    confidence = value.get("confidence")
    reason = value.get("reason")
    if not isinstance(accepted, bool):
        raise RuntimeError(f"{voter} vote is missing a boolean accept field")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{voter} vote is missing a numeric confidence") from exc
    if not 0 <= confidence_value <= 1:
        raise RuntimeError(f"{voter} vote confidence is outside 0 to 1")
    if not isinstance(reason, str) or not reason.strip():
        raise RuntimeError(f"{voter} vote is missing a reason")
    return MaskVote(
        voter=voter,
        model=model,
        accepted=accepted,
        confidence=confidence_value,
        reason=reason.strip()[:2000],
    )


def _review_instruction(prompt: str, candidate_label: str) -> str:
    return (
        "You are independently reviewing one proposed scientific segmentation mask. "
        "The first image is the source crop. The second image is the same crop with the "
        "candidate mask highlighted in translucent red. Decide whether the highlighted "
        "region accurately covers one coherent instance of the requested concept, with "
        "minimal missing target pixels and minimal unrelated background. Reject masks "
        "that merge multiple instances, omit a substantial portion, cover the wrong "
        "object, or include excessive background. "
        f"Requested concept: {prompt!r}. Candidate class label: {candidate_label!r}. "
        "Return only the required JSON object."
    )


class OpenAIMaskVoter:
    voter_name = "openai"

    def __init__(self, settings: Settings, model_name: str) -> None:
        self.settings = settings
        self.model_name = model_name

    def vote(
        self,
        *,
        prompt: str,
        candidate_label: str,
        source_crop_png: bytes,
        overlay_crop_png: bytes,
    ) -> MaskVote:
        api_key = self.settings.openai_api_key
        if not api_key:
            raise RuntimeError("REEFVISION_OPENAI_API_KEY is not configured")
        instruction = _review_instruction(prompt, candidate_label)
        payload = {
            "model": self.model_name,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instruction},
                        {
                            "type": "input_image",
                            "image_url": (
                                "data:image/png;base64,"
                                + base64.b64encode(source_crop_png).decode("ascii")
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": (
                                "data:image/png;base64,"
                                + base64.b64encode(overlay_crop_png).decode("ascii")
                            ),
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "reefvision_mask_vote",
                    "strict": True,
                    "schema": _REMOTE_VOTE_SCHEMA,
                }
            },
        }
        response = _post_json(
            url="https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            payload=payload,
            timeout_seconds=self.settings.remote_vision_timeout_seconds,
        )
        return _parse_vote(
            _extract_openai_text(response),
            voter=self.voter_name,
            model=self.model_name,
        )


class GeminiMaskVoter:
    voter_name = "gemini"

    def __init__(self, settings: Settings, model_name: str) -> None:
        self.settings = settings
        self.model_name = model_name

    def vote(
        self,
        *,
        prompt: str,
        candidate_label: str,
        source_crop_png: bytes,
        overlay_crop_png: bytes,
    ) -> MaskVote:
        api_key = self.settings.gemini_api_key
        if not api_key:
            raise RuntimeError("REEFVISION_GEMINI_API_KEY is not configured")
        model = url_parse.quote(self.model_name, safe="-._")
        query = url_parse.urlencode({"key": api_key})
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": _review_instruction(prompt, candidate_label)},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(source_crop_png).decode("ascii"),
                            }
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(overlay_crop_png).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": _REMOTE_VOTE_SCHEMA,
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
        return _parse_vote(
            _extract_gemini_text(response),
            voter=self.voter_name,
            model=self.model_name,
        )


def _png_bytes(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return stream.getvalue()


def _proposal_mask(
    settings: Settings,
    *,
    proposal: PredictionProposal,
    project: Project,
    image: ImageAsset,
) -> Image.Image:
    if proposal.geometry_kind == "polygon_mask" and proposal.polygon_json:
        mask = Image.new("L", (image.width_px, image.height_px), 0)
        ImageDraw.Draw(mask).polygon(
            [(float(point[0]), float(point[1])) for point in proposal.polygon_json],
            fill=255,
        )
        return mask
    if proposal.geometry_kind == "raster_mask" and proposal.mask_path:
        path = resolve_prediction_mask_png(
            settings,
            project_storage_root=project.storage_root,
            proposal_id=proposal.id,
            relative_path=proposal.mask_path,
        )
        with Image.open(path) as source:
            source.load()
            mask = source.convert("L").point(lambda value: 255 if value else 0)
        if mask.size != (image.width_px, image.height_px):
            raise ValidationError("Consensus candidate mask dimensions do not match its image")
        return mask
    raise ValidationError("Consensus voting requires a polygon or raster mask proposal")


def _candidate_images(
    settings: Settings,
    *,
    proposal: PredictionProposal,
    project: Project,
    image: ImageAsset,
    padding_fraction: float,
) -> tuple[bytes, bytes, bytes]:
    image_path = resolve_managed_project_path(settings, image.managed_path)
    if not image_path.is_file():
        raise ValidationError("Consensus candidate source image is missing")
    with Image.open(image_path) as source:
        source.load()
        source_rgb = source.convert("RGB")
    mask = _proposal_mask(
        settings,
        proposal=proposal,
        project=project,
        image=image,
    )
    width = max(float(proposal.x_max - proposal.x_min), 1.0)
    height = max(float(proposal.y_max - proposal.y_min), 1.0)
    left = max(0, int(proposal.x_min - width * padding_fraction))
    top = max(0, int(proposal.y_min - height * padding_fraction))
    right = min(image.width_px, int(proposal.x_max + width * padding_fraction + 0.999))
    bottom = min(image.height_px, int(proposal.y_max + height * padding_fraction + 0.999))
    if right <= left or bottom <= top:
        raise ValidationError("Consensus candidate has invalid crop bounds")
    source_crop = source_rgb.crop((left, top, right, bottom))
    mask_crop = mask.crop((left, top, right, bottom))
    overlay = source_crop.convert("RGBA")
    red = Image.new("RGBA", source_crop.size, (255, 0, 0, 118))
    transparent = Image.new("RGBA", source_crop.size, (0, 0, 0, 0))
    highlight = Image.composite(red, transparent, mask_crop)
    overlay = Image.alpha_composite(overlay, highlight).convert("RGB")
    return _png_bytes(source_crop), _png_bytes(overlay), _png_bytes(mask)


def _error_vote(voter: MaskVoter, exc: Exception) -> MaskVote:
    return MaskVote(
        voter=voter.voter_name,
        model=voter.model_name,
        accepted=False,
        confidence=0.0,
        reason="Voter failed and was treated as an abstention.",
        error=str(exc)[:2000],
    )


def _promote(
    settings: Settings,
    factory: sessionmaker[Session],
    *,
    proposal_id: str,
    votes: list[MaskVote],
    required_votes: int,
    concept_prompt: str,
    workflow_run_id: str,
    workflow_node_id: str,
) -> str:
    with factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        if proposal is None:
            raise ValidationError("Consensus proposal disappeared before promotion")
        if proposal.review_status in {"accepted", "edited_and_accepted"}:
            if proposal.accepted_mask_annotation_id:
                return proposal.accepted_mask_annotation_id
            raise ValidationError("Accepted consensus proposal is missing its annotation link")
        if proposal.review_status != "pending":
            raise ValidationError("Only pending proposals can be consensus-promoted")
        if proposal.label_class_id is None:
            raise ValidationError("Consensus proposal has no mapped project class")
        image = session.get(ImageAsset, proposal.image_id)
        project = session.get(Project, proposal.project_id)
        if image is None or project is None:
            raise ValidationError("Consensus proposal references a missing image or project")
        _source, _overlay, full_mask_png = _candidate_images(
            settings,
            proposal=proposal,
            project=project,
            image=image,
            padding_fraction=0,
        )
        mask_annotation_id = str(uuid4())
        encoded_mask = base64.b64encode(full_mask_png).decode("ascii")
        stored_path: str | None = None
        try:
            (
                stored_path,
                _path,
                area_pixels,
                x_min,
                y_min,
                x_max,
                y_max,
            ) = write_mask_png(
                settings,
                project_storage_root=project.storage_root,
                image_id=image.id,
                mask_annotation_id=mask_annotation_id,
                png_base64=encoded_mask,
                expected_width=image.width_px,
                expected_height=image.height_px,
            )
            provenance = {
                "workflow_run_id": workflow_run_id,
                "workflow_node_id": workflow_node_id,
                "consensus_method": "two_of_three_mask_vote",
                "required_votes": required_votes,
                "accepted_vote_count": sum(vote.accepted for vote in votes),
                "concept_prompt": concept_prompt,
                "votes": [asdict(vote) for vote in votes],
                "source_prediction_id": proposal.id,
                "source_model_id": proposal.model_id,
                "source_model_checksum": proposal.model_checksum,
                "source_inference_job_id": proposal.inference_job_id,
                "source_geometry_kind": proposal.geometry_kind,
                "source_mask_content_sha256": proposal.mask_content_sha256,
                "source_proposal_provenance": dict(proposal.provenance_json or {}),
                "promoted_at": _utc_now().isoformat(),
            }
            annotation = MaskAnnotation(
                id=mask_annotation_id,
                image_id=image.id,
                label_class_id=proposal.label_class_id,
                geometry_kind="raster_mask",
                mask_path=stored_path,
                polygon_json=None,
                x_min=x_min,
                y_min=y_min,
                x_max=x_max,
                y_max=y_max,
                area_pixels=area_pixels,
                measurement_json={},
                source_type="workflow_consensus",
                provenance_json=provenance,
                status="verified",
                created_by="workflow_consensus",
                revision=1,
            )
            session.add(annotation)
            session.flush()
            session.add(
                MaskAnnotationEvent(
                    mask_annotation_id=annotation.id,
                    image_id=image.id,
                    event_type="created",
                    before_json=None,
                    after_json=mask_annotation_snapshot(annotation),
                    actor="workflow_consensus",
                )
            )
            proposal.review_status = "accepted"
            proposal.reviewer_action_at = _utc_now()
            proposal.accepted_mask_annotation_id = annotation.id
            proposal.provenance_json = {
                **dict(proposal.provenance_json or {}),
                "workflow_consensus": provenance,
                "accepted_mask_annotation_id": annotation.id,
            }
            image.annotation_revision += 1
            if image.annotation_status == "unannotated":
                image.annotation_status = "in_progress"
            session.commit()
            return annotation.id
        except Exception:
            session.rollback()
            if stored_path is not None:
                try:
                    remove_mask_annotation_png(
                        settings,
                        project_storage_root=project.storage_root,
                        image_id=image.id,
                        mask_annotation_id=mask_annotation_id,
                        relative_path=stored_path,
                    )
                except Exception:
                    pass
            raise


def apply_multi_model_mask_consensus(
    settings: Settings,
    factory: sessionmaker[Session],
    *,
    prediction_ids: list[str],
    consensus_configuration: dict[str, Any],
    workflow_run_id: str,
    workflow_node_id: str,
    voters: list[MaskVoter] | None = None,
) -> ConsensusBatchResult:
    """Evaluate and optionally promote workflow segmentation proposals."""

    config = _configuration(consensus_configuration)
    if settings.safe_mode:
        raise ValidationError("Remote multi-model auto-labeling is disabled in safe mode")
    if not settings.allow_remote_vision or not config["allow_remote_review"]:
        raise ValidationError(
            "Remote mask review requires both REEFVISION_ALLOW_REMOTE_VISION=true "
            "and allow_remote_review=true in the workflow node"
        )
    configured_voters: list[MaskVoter] = voters or [
        GeminiMaskVoter(settings, config["gemini_model"]),
        OpenAIMaskVoter(settings, config["openai_model"]),
    ]
    if len(configured_voters) != 2:
        raise ValidationError("Consensus auto-labeling requires exactly two remote reviewers")

    results: list[ConsensusCandidateResult] = []
    failed_count = 0
    for proposal_id in list(dict.fromkeys(prediction_ids)):
        try:
            with factory() as session:
                proposal = session.get(PredictionProposal, proposal_id)
                if proposal is None:
                    raise ValidationError("Consensus proposal does not exist")
                image = session.get(ImageAsset, proposal.image_id)
                project = session.get(Project, proposal.project_id)
                if image is None or project is None:
                    raise ValidationError("Consensus proposal references missing project data")
                if proposal.geometry_kind not in {"polygon_mask", "raster_mask"}:
                    raise ValidationError("Consensus voting only supports segmentation masks")
                source_png, overlay_png, _full_mask = _candidate_images(
                    settings,
                    proposal=proposal,
                    project=project,
                    image=image,
                    padding_fraction=config["crop_padding_fraction"],
                )
                if proposal.label_class_id is None:
                    raise ValidationError(
                        "Consensus proposal must map to a project class before remote review"
                    )
                candidate_label = proposal.predicted_label
                proposal_confidence = float(proposal.confidence)
                primary_model_id = proposal.model_id
                image_id = proposal.image_id

            votes = [
                MaskVote(
                    voter="primary_segmenter",
                    model=primary_model_id,
                    accepted=proposal_confidence >= config["sam_vote_threshold"],
                    confidence=proposal_confidence,
                    reason=(
                        "Primary segmenter confidence met the configured threshold."
                        if proposal_confidence >= config["sam_vote_threshold"]
                        else "Primary segmenter confidence was below the configured threshold."
                    ),
                )
            ]
            for voter in configured_voters:
                try:
                    vote = voter.vote(
                        prompt=config["prompt"],
                        candidate_label=candidate_label,
                        source_crop_png=source_png,
                        overlay_crop_png=overlay_png,
                    )
                except Exception as exc:
                    vote = _error_vote(voter, exc)
                    if not config["fail_closed"]:
                        raise
                votes.append(vote)

            accepted_votes = sum(
                vote.accepted
                and vote.confidence
                >= (
                    config["sam_vote_threshold"]
                    if vote.voter == "primary_segmenter"
                    else config["minimum_reviewer_confidence"]
                )
                for vote in votes
            )
            reached = accepted_votes >= config["required_votes"]
            annotation_id = None
            promoted = False
            if reached and config["auto_accept"]:
                annotation_id = _promote(
                    settings,
                    factory,
                    proposal_id=proposal_id,
                    votes=votes,
                    required_votes=config["required_votes"],
                    concept_prompt=config["prompt"],
                    workflow_run_id=workflow_run_id,
                    workflow_node_id=workflow_node_id,
                )
                promoted = True
            else:
                with factory() as session:
                    current = session.get(PredictionProposal, proposal_id)
                    if current is not None:
                        current.provenance_json = {
                            **dict(current.provenance_json or {}),
                            "workflow_consensus": {
                                "workflow_run_id": workflow_run_id,
                                "workflow_node_id": workflow_node_id,
                                "required_votes": config["required_votes"],
                                "accepted_vote_count": accepted_votes,
                                "consensus_reached": reached,
                                "auto_accept": config["auto_accept"],
                                "concept_prompt": config["prompt"],
                                "votes": [asdict(vote) for vote in votes],
                                "evaluated_at": _utc_now().isoformat(),
                            },
                        }
                        session.commit()
            results.append(
                ConsensusCandidateResult(
                    proposal_id=proposal_id,
                    image_id=image_id,
                    accepted_vote_count=accepted_votes,
                    required_votes=config["required_votes"],
                    consensus_reached=reached,
                    auto_promoted=promoted,
                    mask_annotation_id=annotation_id,
                    votes=votes,
                )
            )
        except Exception:
            failed_count += 1
            if not config["fail_closed"]:
                raise

    consensus_count = sum(item.consensus_reached for item in results)
    promoted_count = sum(item.auto_promoted for item in results)
    return ConsensusBatchResult(
        requested_count=len(list(dict.fromkeys(prediction_ids))),
        evaluated_count=len(results),
        consensus_count=consensus_count,
        promoted_count=promoted_count,
        pending_count=len(results) - promoted_count,
        failed_count=failed_count,
        candidates=results,
    )
