"""Interactive SAM-style annotation assist services."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ImageAsset,
    MaskAnnotation,
    MaskAnnotationEvent,
    ModelRegistration,
    PredictionProposal,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.assist_runtime import AssistRuntime, AssistSessionState
from reefvision.ml.mask_tools import (
    Ring,
    mask_iou,
    mask_to_rings,
    polygon_quality,
    polygon_to_mask,
    simplify_ring,
)
from reefvision.ml.provider_hub import get_model_provider
from reefvision.ml.providers import BrushStroke, PixelBox, PixelPoint
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.repositories.models import ModelRepository
from reefvision.repositories.predictions import PredictionRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.annotations import AnnotationResponse, MaskAnnotationResponse
from reefvision.schemas.assist import (
    AssistAcceptRequest,
    AssistAcceptResponse,
    AssistBoxRequest,
    AssistBrushRequest,
    AssistCandidateBox,
    AssistSessionCreateRequest,
    AssistSessionResponse,
)
from reefvision.services.annotations import annotation_snapshot, mask_annotation_snapshot
from reefvision.storage.masks import write_mask_png
from reefvision.storage.models import resolve_verified_model_path
from reefvision.storage.projects import resolve_managed_project_path

ASSIST_POLYGON_MAX_CONTOUR_VERTICES = 20_000
ASSIST_POLYGON_INSET_EPSILON_PX = 1e-6
ASSIST_POLYGON_MIN_IOU = 1.0
ASSIST_POLYGON_MAX_AREA_ERROR_FRACTION = 0.0


def _validated_candidate_mask(
    candidate: object,
    *,
    width: int,
    height: int,
) -> NDArray[np.bool_]:
    try:
        values = np.asarray(candidate)
    except (TypeError, ValueError) as exc:
        raise ValidationError("The candidate mask could not be read as a raster") from exc
    if values.ndim != 2:
        raise ValidationError("The candidate mask must be a two-dimensional raster")
    if values.shape != (height, width):
        raise ValidationError(
            "The candidate mask dimensions do not match the source image; "
            "accept a correctly aligned raster mask instead"
        )
    if values.dtype.kind not in {"b", "u", "i", "f"}:
        raise ValidationError("The candidate mask contains an unsupported pixel type")
    if values.dtype.kind == "f" and not bool(np.isfinite(values).all()):
        raise ValidationError("The candidate mask contains non-finite pixel values")
    mask = np.asarray(values > 0, dtype=bool)
    if not bool(mask.any()):
        raise ValidationError("The candidate mask is empty")
    return mask


def _inset_ring_for_pillow(ring: Ring, mask: NDArray[np.bool_]) -> Ring:
    """Nudge pixel-edge vertices toward local foreground for Pillow rasterization."""

    height, width = mask.shape
    inset: Ring = []
    for x, y in ring:
        grid_x = round(x)
        grid_y = round(y)
        if not math.isclose(x, grid_x, abs_tol=1e-9) or not math.isclose(y, grid_y, abs_tol=1e-9):
            raise ValidationError("The candidate contour is not aligned to the mask pixel grid")
        direction_x = 0.0
        direction_y = 0.0
        adjacent_count = 0
        for pixel_y in (grid_y - 1, grid_y):
            for pixel_x in (grid_x - 1, grid_x):
                if 0 <= pixel_x < width and 0 <= pixel_y < height and mask[pixel_y, pixel_x]:
                    direction_x += pixel_x + 0.5 - x
                    direction_y += pixel_y + 0.5 - y
                    adjacent_count += 1
        if adjacent_count == 0:
            raise ValidationError("The candidate contour is detached from its raster mask")
        adjusted_x = (
            x + math.copysign(ASSIST_POLYGON_INSET_EPSILON_PX, direction_x) if direction_x else x
        )
        adjusted_y = (
            y + math.copysign(ASSIST_POLYGON_INSET_EPSILON_PX, direction_y) if direction_y else y
        )
        inset.append((adjusted_x, adjusted_y))
    return inset


def _polygon_from_candidate_mask(
    candidate: object,
    *,
    width: int,
    height: int,
) -> tuple[list[list[float]], int, float, float, float, float, float, float]:
    mask = _validated_candidate_mask(candidate, width=width, height=height)
    try:
        rings = mask_to_rings(mask)
    except RecursionError as exc:
        raise ValidationError(
            "The candidate mask is too complex to convert safely; accept it as a raster mask"
        ) from exc
    if len(rings) != 1:
        raise ValidationError(
            "Editable polygon conversion cannot preserve masks with holes or disconnected "
            "regions; accept this candidate as a raster mask"
        )
    source_ring = rings[0]
    if len(source_ring) > ASSIST_POLYGON_MAX_CONTOUR_VERTICES:
        raise ValidationError(
            "The candidate contour is too complex to edit safely; accept it as a raster mask"
        )

    try:
        simplified = simplify_ring(source_ring, tolerance=1.0)
    except RecursionError as exc:
        raise ValidationError(
            "The candidate contour is too complex to simplify safely; accept it as a raster mask"
        ) from exc
    candidates = [(simplified, 1.0)]
    if simplified != source_ring:
        candidates.append((source_ring, 0.0))

    source_area = int(np.count_nonzero(mask))
    best_iou = 0.0
    best_area_error = float("inf")
    for candidate_ring, tolerance in candidates:
        try:
            ring = _inset_ring_for_pillow(candidate_ring, mask)
            quality = polygon_quality(ring, width=width, height=height)
        except ValidationError:
            continue
        if quality.vertex_count < 3 or quality.area <= 0:
            continue
        if quality.outside_vertex_count or quality.self_intersections:
            continue
        rerasterized = polygon_to_mask(ring, width=width, height=height)
        converted_area = int(np.count_nonzero(rerasterized))
        iou = mask_iou(mask, rerasterized)
        area_error = abs(converted_area - source_area) / source_area
        best_iou = max(best_iou, iou)
        best_area_error = min(best_area_error, area_error)
        if iou >= ASSIST_POLYGON_MIN_IOU and area_error <= ASSIST_POLYGON_MAX_AREA_ERROR_FRACTION:
            x_values = [x for x, _ in ring]
            y_values = [y for _, y in ring]
            return (
                [[x, y] for x, y in ring],
                source_area,
                min(x_values),
                min(y_values),
                max(x_values),
                max(y_values),
                tolerance,
                iou,
            )

    details = (
        f"best IoU {best_iou:.6f}, area error {best_area_error:.6f}"
        if math.isfinite(best_area_error)
        else "no valid simple contour"
    )
    raise ValidationError(
        "The candidate mask cannot be converted without changing its pixels "
        f"({details}); accept it as a raster mask"
    )


def _require_ready_assist_provider(settings: Settings, provider_name: str) -> None:
    try:
        descriptor = get_model_provider(provider_name, settings)
    except NotFoundError as exc:
        raise ValidationError(f"Unsupported Prompt Assist provider: {provider_name}") from exc

    if descriptor.provider_id != "segment_anything" or not descriptor.registerable:
        raise ValidationError(f"Unsupported Prompt Assist provider: {provider_name}")

    status = descriptor.availability_status
    if status == "dependency_missing":
        missing = ", ".join(
            package.distribution_name
            for package in descriptor.required_packages
            if package.status == "missing"
        )
        detail = missing or descriptor.availability_reason or "unknown dependency"
        raise ValidationError(f"Segment Anything dependencies are missing: {detail}")
    if status == "dependency_incompatible":
        incompatible = ", ".join(
            package.distribution_name
            for package in descriptor.required_packages
            if package.status == "incompatible"
        )
        detail = incompatible or descriptor.availability_reason or "unknown dependency"
        raise ValidationError(f"Segment Anything dependencies are incompatible: {detail}")
    if status != "ready":
        raise ValidationError(
            descriptor.availability_reason or "The Segment Anything provider runtime is not ready"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AssistService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        runtime: AssistRuntime,
    ) -> None:
        self.session = session
        self.settings = settings
        self.runtime = runtime
        self.projects = ProjectRepository(session)
        self.images = ImageRepository(session)
        self.models = ModelRepository(session)
        self.annotations = AnnotationRepository(session)
        self.mask_annotations = MaskAnnotationRepository(session)
        self.predictions = PredictionRepository(session)

    def _image(self, image_id: str) -> ImageAsset:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _model(self, model_id: str) -> ModelRegistration:
        model = self.models.get(model_id)
        if model is None:
            raise NotFoundError("Model not found")
        return model

    def _source_prediction(
        self,
        image: ImageAsset,
        proposal_id: str,
    ) -> PredictionProposal:
        proposal = self.predictions.get(proposal_id)
        if proposal is None:
            raise NotFoundError("Prediction proposal not found")
        if proposal.project_id != image.project_id or proposal.image_id != image.id:
            raise ValidationError(
                "Prompt Assist proposals must belong to the same project image "
                "as the assist session"
            )
        if proposal.review_status != "pending":
            raise ConflictError(
                "Only pending prediction proposals can be segmented with Prompt Assist"
            )
        return proposal

    def _response(self, session_state: AssistSessionState) -> AssistSessionResponse:
        candidate_box = None
        if session_state.candidate_prediction is not None:
            candidate_box = AssistCandidateBox(
                x_min=session_state.candidate_prediction.box.x_min,
                y_min=session_state.candidate_prediction.box.y_min,
                x_max=session_state.candidate_prediction.box.x_max,
                y_max=session_state.candidate_prediction.box.y_max,
            )
        return AssistSessionResponse(
            session_id=session_state.session_id,
            project_id=session_state.project_id,
            image_id=session_state.image_id,
            model_id=session_state.model_id,
            model_display_name=session_state.model_display_name,
            provider_name=session_state.provider_name,
            provider_version=session_state.provider_version,
            created_at=session_state.created_at,
            last_used_at=session_state.last_used_at,
            expires_at=session_state.expires_at,
            add_stroke_count=len(session_state.add_strokes),
            subtract_stroke_count=len(session_state.subtract_strokes),
            brush_radius=session_state.brush_radius,
            source_prediction_id=session_state.source_prediction_id,
            prompt_type=session_state.prompt_type,
            candidate_box=candidate_box,
            candidate_mask_png_base64=session_state.candidate_mask_png_base64,
        )

    def create_session(
        self,
        image_id: str,
        payload: AssistSessionCreateRequest,
    ) -> AssistSessionResponse:
        image = self._image(image_id)
        model = self._model(payload.model_id)
        if model.project_id != image.project_id:
            raise ValidationError("The assist model belongs to a different project")
        if model.purpose != "assist" or model.task != "assist_segmentation":
            raise ValidationError("The selected model has an incompatible task for Prompt Assist")
        model_path = resolve_verified_model_path(
            self.settings,
            model.managed_path,
            expected_sha256=model.sha256,
        )
        _require_ready_assist_provider(self.settings, model.provider_name)
        source_prediction_id = None
        if payload.source_prediction_id:
            source_prediction_id = self._source_prediction(
                image,
                payload.source_prediction_id,
            ).id
        image_path = resolve_managed_project_path(self.settings, image.managed_path)
        session_state = self.runtime.create_session(
            project_id=image.project_id,
            image_id=image.id,
            image_sha256=image.sha256,
            image_path=image_path,
            model_id=model.id,
            model_display_name=model.display_name,
            model_checksum=model.sha256,
            model_path=model_path,
            provider_name=model.provider_name,
            provider_version=model.provider_version,
            device=payload.device,
            source_prediction_id=source_prediction_id,
        )
        return self._response(session_state)

    def brush(
        self,
        session_id: str,
        payload: AssistBrushRequest,
    ) -> AssistSessionResponse:
        image_id = self.runtime._session(session_id).image_id
        image = self._image(image_id)
        strokes = [
            BrushStroke(
                points=[PixelPoint(x=point.x, y=point.y) for point in stroke.points],
                brush_radius=float(payload.brush_radius),
            )
            for stroke in payload.strokes
        ]
        state = self.runtime.apply_brush_prompts(
            session_id=session_id,
            strokes=strokes,
            mode=payload.mode,
            image_width=image.width_px,
            image_height=image.height_px,
        )
        return self._response(state)

    def box(
        self,
        session_id: str,
        payload: AssistBoxRequest,
    ) -> AssistSessionResponse:
        if payload.x_max <= payload.x_min or payload.y_max <= payload.y_min:
            raise ValidationError("Bounding boxes must have positive width and height")
        state = self.runtime.apply_box_prompt(
            session_id=session_id,
            box=PixelBox(
                x_min=payload.x_min,
                y_min=payload.y_min,
                x_max=payload.x_max,
                y_max=payload.y_max,
            ),
        )
        return self._response(state)

    def reset(self, session_id: str) -> AssistSessionResponse:
        return self._response(self.runtime.reset_session(session_id))

    def accept(
        self,
        session_id: str,
        payload: AssistAcceptRequest,
    ) -> AssistAcceptResponse:
        session_state, box, provenance = self.runtime.accept_session(session_id)
        image = self._image(session_state.image_id)
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        project_class_ids = {label_class.id for label_class in project.label_classes}
        if payload.label_class_id not in project_class_ids:
            raise ValidationError("Annotation class does not belong to this image's project")
        if session_state.candidate_mask_png_base64 is None:
            raise ValidationError("There is no current Smart Mask raster to accept")

        annotation_id = str(uuid4())
        mask_annotation_id = str(uuid4())
        destination_path: Path | None = None
        annotation: Annotation | None = None
        mask_annotation: MaskAnnotation | None = None
        try:
            polygon_json: list[list[float]] | None = None
            relative_mask_path: str | None = None
            polygon_conversion_tolerance: float | None = None
            polygon_conversion_iou: float | None = None
            if payload.output_kind == "raster_mask":
                (
                    relative_mask_path,
                    destination_path,
                    area_pixels,
                    mask_x_min,
                    mask_y_min,
                    mask_x_max,
                    mask_y_max,
                ) = write_mask_png(
                    self.settings,
                    project_storage_root=project.storage_root,
                    image_id=image.id,
                    mask_annotation_id=mask_annotation_id,
                    png_base64=session_state.candidate_mask_png_base64,
                    expected_width=image.width_px,
                    expected_height=image.height_px,
                )
            else:
                prediction = session_state.candidate_prediction
                if prediction is None:
                    raise ValidationError("There is no current Smart Mask candidate to convert")
                (
                    polygon_json,
                    area_pixels,
                    mask_x_min,
                    mask_y_min,
                    mask_x_max,
                    mask_y_max,
                    polygon_conversion_tolerance,
                    polygon_conversion_iou,
                ) = _polygon_from_candidate_mask(
                    prediction.mask,
                    width=image.width_px,
                    height=image.height_px,
                )
            shared_provenance = {
                **provenance,
                "assist_model_id": session_state.model_id,
                "accepted_box_annotation_id": annotation_id,
                "accepted_mask_annotation_id": mask_annotation_id,
                "prompt_box": {
                    "x_min": box.x_min,
                    "y_min": box.y_min,
                    "x_max": box.x_max,
                    "y_max": box.y_max,
                },
                "output_kind": payload.output_kind,
                "polygon_conversion_tolerance_px": polygon_conversion_tolerance,
                "polygon_conversion_iou": polygon_conversion_iou,
                "polygon_conversion_max_area_error_fraction": (
                    ASSIST_POLYGON_MAX_AREA_ERROR_FRACTION
                    if payload.output_kind == "polygon"
                    else None
                ),
                "polygon_coordinate_inset_px": (
                    ASSIST_POLYGON_INSET_EPSILON_PX if payload.output_kind == "polygon" else None
                ),
                "mask_bounds": {
                    "x_min": mask_x_min,
                    "y_min": mask_y_min,
                    "x_max": mask_x_max,
                    "y_max": mask_y_max,
                },
            }
            annotation = Annotation(
                id=annotation_id,
                image_id=image.id,
                label_class_id=payload.label_class_id,
                x_min=box.x_min,
                y_min=box.y_min,
                x_max=box.x_max,
                y_max=box.y_max,
                source_type="assist_mask",
                source_model_id=session_state.model_id,
                source_prediction_id=session_state.source_prediction_id,
                provenance_json=shared_provenance,
            )
            mask_annotation = MaskAnnotation(
                id=mask_annotation_id,
                image_id=image.id,
                label_class_id=payload.label_class_id,
                geometry_kind=payload.output_kind,
                mask_path=relative_mask_path,
                polygon_json=polygon_json,
                x_min=mask_x_min,
                y_min=mask_y_min,
                x_max=mask_x_max,
                y_max=mask_y_max,
                area_pixels=area_pixels,
                source_type="assist_mask",
                provenance_json=shared_provenance,
                status="verified",
                created_by="local_user",
                revision=1,
            )
            if session_state.source_prediction_id is not None:
                self._attach_source_prediction(
                    image=image,
                    proposal_id=session_state.source_prediction_id,
                    annotation=annotation,
                    label_class_id=payload.label_class_id,
                    mask_annotation_id=mask_annotation.id,
                )
            self.annotations.add(annotation)
            self.annotations.add_event(
                AnnotationEvent(
                    annotation_id=annotation.id,
                    image_id=image.id,
                    event_type="created",
                    before_json=None,
                    after_json=annotation_snapshot(annotation),
                    actor="local_user",
                )
            )
            self.mask_annotations.add(mask_annotation)
            self.mask_annotations.add_event(
                MaskAnnotationEvent(
                    mask_annotation_id=mask_annotation.id,
                    image_id=image.id,
                    event_type="created",
                    before_json=None,
                    after_json=mask_annotation_snapshot(mask_annotation),
                    actor="local_user",
                )
            )
            image.annotation_revision += 1
            if image.annotation_status == "unannotated":
                image.annotation_status = "in_progress"
            self.session.commit()
        except Exception:
            self.session.rollback()
            if destination_path is not None:
                destination_path.unlink(missing_ok=True)
            raise

        assert annotation is not None
        assert mask_annotation is not None
        self.session.refresh(annotation)
        self.session.refresh(mask_annotation)
        self.runtime.delete_session(session_id)
        return AssistAcceptResponse(
            session_id=session_id,
            annotation=AnnotationResponse.model_validate(annotation),
            mask_annotation=MaskAnnotationResponse.model_validate(mask_annotation),
        )

    def cancel(self, session_id: str) -> None:
        self.runtime.delete_session(session_id)

    def _attach_source_prediction(
        self,
        *,
        image: ImageAsset,
        proposal_id: str,
        annotation: Annotation,
        label_class_id: str,
        mask_annotation_id: str,
    ) -> PredictionProposal:
        proposal = self._source_prediction(image, proposal_id)
        edited = (
            label_class_id != proposal.label_class_id
            or annotation.x_min != proposal.x_min
            or annotation.y_min != proposal.y_min
            or annotation.x_max != proposal.x_max
            or annotation.y_max != proposal.y_max
        )
        proposal.review_status = "edited_and_accepted" if edited else "accepted"
        proposal.was_edited = edited
        proposal.reviewer_action_at = _utc_now()
        proposal.accepted_annotation_id = annotation.id
        proposal.accepted_mask_annotation_id = mask_annotation_id
        proposal.provenance_json = {
            **(proposal.provenance_json or {}),
            "assist_acceptance": {
                "assist_model_id": annotation.source_model_id,
                "accepted_annotation_id": annotation.id,
                "accepted_mask_annotation_id": mask_annotation_id,
                "accepted_label_class_id": label_class_id,
                "accepted_box": {
                    "x_min": annotation.x_min,
                    "y_min": annotation.y_min,
                    "x_max": annotation.x_max,
                    "y_max": annotation.y_max,
                },
                "accepted_at": _utc_now().isoformat(),
            },
        }
        annotation.provenance_json = {
            **(annotation.provenance_json or {}),
            "source_prediction": {
                "proposal_id": proposal.id,
                "inference_job_id": proposal.inference_job_id,
                "model_id": proposal.model_id,
                "model_checksum": proposal.model_checksum,
                "original_predicted_label": proposal.predicted_label,
                "original_confidence": proposal.confidence,
                "original_box": {
                    "x_min": proposal.x_min,
                    "y_min": proposal.y_min,
                    "x_max": proposal.x_max,
                    "y_max": proposal.y_max,
                },
                "review_status_after_accept": proposal.review_status,
            },
        }
        return proposal
