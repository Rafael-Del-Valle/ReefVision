"""Quantitative comparison of segmentation proposals with verified masks."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import TypeAlias

from PIL import Image, ImageDraw, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
    Project,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.segmentation_evaluation import (
    SegmentationClassEvaluation,
    SegmentationEvaluationRequest,
    SegmentationEvaluationResponse,
    SegmentationInstanceMatch,
)
from reefvision.storage.projects import resolve_managed_project_path

BinaryMask: TypeAlias = Image.Image
GroupKey: TypeAlias = tuple[str, str | None]


def _polygon_mask(
    points: list[list[float]],
    *,
    width: int,
    height: int,
) -> BinaryMask:
    image = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.polygon([(float(point[0]), float(point[1])) for point in points], fill=1)
    return image


def _raster_mask(
    settings: Settings,
    relative_path: str,
    *,
    width: int,
    height: int,
) -> BinaryMask:
    path = resolve_managed_project_path(settings, relative_path)
    if not path.is_file():
        raise ValidationError("Segmentation mask content is missing")
    try:
        with Image.open(path) as source:
            source.load()
            if source.size != (width, height):
                raise ValidationError(
                    "Segmentation mask dimensions do not match the source image"
                )
            return source.convert("L").point(lambda value: 1 if value > 0 else 0).convert("1")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Segmentation mask content could not be read") from exc


def _pixel_statistics(
    ground_truth: BinaryMask,
    prediction: BinaryMask,
) -> tuple[int, int, float, float, float, float]:
    ground_truth_bytes = ground_truth.tobytes()
    prediction_bytes = prediction.tobytes()
    ground_truth_area = 0
    prediction_area = 0
    intersection = 0
    for ground_truth_value, prediction_value in zip(
        ground_truth_bytes,
        prediction_bytes,
        strict=True,
    ):
        ground_truth_foreground = ground_truth_value != 0
        prediction_foreground = prediction_value != 0
        ground_truth_area += int(ground_truth_foreground)
        prediction_area += int(prediction_foreground)
        intersection += int(ground_truth_foreground and prediction_foreground)
    union = ground_truth_area + prediction_area - intersection
    iou = intersection / union if union else 1.0
    denominator = ground_truth_area + prediction_area
    dice = 2 * intersection / denominator if denominator else 1.0
    precision = intersection / prediction_area if prediction_area else 0.0
    recall = intersection / ground_truth_area if ground_truth_area else 0.0
    return intersection, union, iou, dice, precision, recall


class SegmentationEvaluationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _model(self, project_id: str, model_id: str) -> ModelRegistration:
        model = self.session.get(ModelRegistration, model_id)
        if model is None:
            raise NotFoundError("Model not found")
        if model.project_id != project_id:
            raise ValidationError("The evaluation model must belong to the project")
        if model.task not in {"segment", "semantic_segment"} and model.purpose not in {
            "segmenter",
            "semantic_segmenter",
        }:
            raise ValidationError("Segmentation evaluation requires a segmentation model")
        return model

    def _images(
        self,
        project_id: str,
        requested_ids: list[str],
    ) -> list[ImageAsset]:
        query = select(ImageAsset).where(ImageAsset.project_id == project_id)
        if requested_ids:
            query = query.where(ImageAsset.id.in_(requested_ids))
        images = list(self.session.scalars(query.order_by(ImageAsset.created_at, ImageAsset.id)))
        if requested_ids and len(images) != len(set(requested_ids)):
            raise ValidationError(
                "All requested evaluation images must exist in the selected project"
            )
        return images

    def _verified_masks(
        self,
        image_ids: list[str],
    ) -> list[MaskAnnotation]:
        if not image_ids:
            return []
        return list(
            self.session.scalars(
                select(MaskAnnotation)
                .where(
                    MaskAnnotation.image_id.in_(image_ids),
                    MaskAnnotation.deleted_at.is_(None),
                    MaskAnnotation.status == "verified",
                )
                .order_by(MaskAnnotation.image_id, MaskAnnotation.created_at, MaskAnnotation.id)
            )
        )

    def _proposals(
        self,
        request: SegmentationEvaluationRequest,
        image_ids: list[str],
    ) -> list[PredictionProposal]:
        if not image_ids:
            return []
        statuses: list[str] = []
        if request.include_pending_predictions:
            statuses.append("pending")
        if request.include_accepted_predictions:
            statuses.append("accepted")
        if not statuses:
            raise ValidationError("Include pending, accepted, or both prediction states")
        return list(
            self.session.scalars(
                select(PredictionProposal)
                .where(
                    PredictionProposal.model_id == request.model_id,
                    PredictionProposal.image_id.in_(image_ids),
                    PredictionProposal.confidence >= request.confidence_threshold,
                    PredictionProposal.geometry_kind != "bounding_box",
                    PredictionProposal.review_status.in_(statuses),
                )
                .order_by(
                    PredictionProposal.image_id,
                    PredictionProposal.confidence.desc(),
                    PredictionProposal.id,
                )
            )
        )

    def _mask_geometry(
        self,
        item: MaskAnnotation | PredictionProposal,
        image: ImageAsset,
    ) -> BinaryMask:
        if item.polygon_json:
            return _polygon_mask(
                item.polygon_json,
                width=image.width_px,
                height=image.height_px,
            )
        relative_path = (
            item.mask_path
            if isinstance(item, MaskAnnotation)
            else item.mask_path
        )
        if relative_path:
            return _raster_mask(
                self.settings,
                relative_path,
                width=image.width_px,
                height=image.height_px,
            )
        raise ValidationError("Segmentation record has no polygon or raster geometry")

    def evaluate(
        self,
        project_id: str,
        request: SegmentationEvaluationRequest,
    ) -> SegmentationEvaluationResponse:
        self._project(project_id)
        self._model(project_id, request.model_id)
        images = self._images(project_id, request.image_ids)
        image_by_id = {image.id: image for image in images}
        verified_masks = self._verified_masks(list(image_by_id))
        proposals = self._proposals(request, list(image_by_id))
        warnings: list[str] = []

        ground_truth_by_group: dict[GroupKey, list[tuple[MaskAnnotation, BinaryMask]]] = (
            defaultdict(list)
        )
        prediction_by_group: dict[
            GroupKey,
            list[tuple[PredictionProposal, BinaryMask]],
        ] = defaultdict(list)

        for mask in verified_masks:
            try:
                ground_truth_by_group[(mask.image_id, mask.label_class_id)].append(
                    (mask, self._mask_geometry(mask, image_by_id[mask.image_id]))
                )
            except ValidationError as exc:
                warnings.append(f"Mask {mask.id} was skipped: {exc}")

        unresolved_prediction_count = 0
        for proposal in proposals:
            if proposal.label_class_id is None:
                unresolved_prediction_count += 1
            try:
                prediction_by_group[(proposal.image_id, proposal.label_class_id)].append(
                    (
                        proposal,
                        self._mask_geometry(proposal, image_by_id[proposal.image_id]),
                    )
                )
            except ValidationError as exc:
                warnings.append(f"Prediction {proposal.id} was skipped: {exc}")
        if unresolved_prediction_count:
            warnings.append(
                f"{unresolved_prediction_count} predictions have no resolved project class "
                "and are evaluated as unmapped false positives unless matched to an "
                "unclassified verified mask."
            )

        matches: list[SegmentationInstanceMatch] = []
        summaries: list[SegmentationClassEvaluation] = []
        all_groups = sorted(
            set(ground_truth_by_group) | set(prediction_by_group),
            key=lambda item: (item[1] or "", item[0]),
        )
        for image_id, label_class_id in all_groups:
            ground_truth_items = ground_truth_by_group[(image_id, label_class_id)]
            prediction_items = prediction_by_group[(image_id, label_class_id)]
            candidates: list[
                tuple[
                    float,
                    int,
                    int,
                    tuple[int, int, float, float, float, float],
                ]
            ] = []
            for ground_truth_index, (_, ground_truth_mask) in enumerate(
                ground_truth_items
            ):
                for prediction_index, (_, prediction_mask) in enumerate(
                    prediction_items
                ):
                    statistics = _pixel_statistics(ground_truth_mask, prediction_mask)
                    candidates.append(
                        (
                            statistics[2],
                            ground_truth_index,
                            prediction_index,
                            statistics,
                        )
                    )
            used_ground_truth: set[int] = set()
            used_predictions: set[int] = set()
            group_matches: list[SegmentationInstanceMatch] = []
            for iou, ground_truth_index, prediction_index, statistics in sorted(
                candidates,
                key=lambda item: item[0],
                reverse=True,
            ):
                if iou < request.match_iou_threshold:
                    break
                if (
                    ground_truth_index in used_ground_truth
                    or prediction_index in used_predictions
                ):
                    continue
                used_ground_truth.add(ground_truth_index)
                used_predictions.add(prediction_index)
                ground_truth = ground_truth_items[ground_truth_index][0]
                prediction = prediction_items[prediction_index][0]
                intersection, union, _, dice, pixel_precision, pixel_recall = statistics
                match = SegmentationInstanceMatch(
                    image_id=image_id,
                    label_class_id=label_class_id,
                    ground_truth_mask_id=ground_truth.id,
                    prediction_id=prediction.id,
                    intersection_pixels=intersection,
                    union_pixels=union,
                    iou=iou,
                    dice=dice,
                    pixel_precision=pixel_precision,
                    pixel_recall=pixel_recall,
                )
                group_matches.append(match)
                matches.append(match)

            ground_truth_count = len(ground_truth_items)
            prediction_count = len(prediction_items)
            matched_count = len(group_matches)
            summaries.append(
                SegmentationClassEvaluation(
                    label_class_id=label_class_id,
                    ground_truth_count=ground_truth_count,
                    prediction_count=prediction_count,
                    matched_count=matched_count,
                    false_positive_count=prediction_count - matched_count,
                    false_negative_count=ground_truth_count - matched_count,
                    instance_precision=(
                        matched_count / prediction_count if prediction_count else 0.0
                    ),
                    instance_recall=(
                        matched_count / ground_truth_count if ground_truth_count else 0.0
                    ),
                    mean_iou=(mean(item.iou for item in group_matches) if group_matches else None),
                    mean_dice=(
                        mean(item.dice for item in group_matches)
                        if group_matches
                        else None
                    ),
                    mean_pixel_precision=(
                        mean(item.pixel_precision for item in group_matches)
                        if group_matches
                        else None
                    ),
                    mean_pixel_recall=(
                        mean(item.pixel_recall for item in group_matches)
                        if group_matches
                        else None
                    ),
                )
            )

        ground_truth_count = sum(item.ground_truth_count for item in summaries)
        prediction_count = sum(item.prediction_count for item in summaries)
        matched_count = len(matches)
        return SegmentationEvaluationResponse(
            project_id=project_id,
            model_id=request.model_id,
            image_count=len(images),
            ground_truth_count=ground_truth_count,
            prediction_count=prediction_count,
            matched_count=matched_count,
            false_positive_count=prediction_count - matched_count,
            false_negative_count=ground_truth_count - matched_count,
            instance_precision=(
                matched_count / prediction_count if prediction_count else 0.0
            ),
            instance_recall=(
                matched_count / ground_truth_count if ground_truth_count else 0.0
            ),
            mean_iou=mean(item.iou for item in matches) if matches else None,
            mean_dice=mean(item.dice for item in matches) if matches else None,
            confidence_threshold=request.confidence_threshold,
            match_iou_threshold=request.match_iou_threshold,
            per_class=sorted(
                summaries,
                key=lambda item: item.label_class_id or "",
            ),
            matches=sorted(
                matches,
                key=lambda item: (
                    item.image_id,
                    item.label_class_id or "",
                    -item.iou,
                    item.prediction_id,
                ),
            ),
            warnings=list(dict.fromkeys(warnings)),
        )
