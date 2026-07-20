"""Advanced quantitative comparison of segmentation proposals with verified masks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, TypeAlias, cast

import numpy as np
from numpy.typing import NDArray
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
from reefvision.ml.segmentation_metrics import (
    area_stratum,
    average_precision,
    boundary_metrics,
    confidence_calibration,
    panoptic_metrics,
)
from reefvision.schemas.segmentation_evaluation import (
    SegmentationAveragePrecisionRow,
    SegmentationCalibrationBin,
    SegmentationClassEvaluation,
    SegmentationEvaluationRequest,
    SegmentationEvaluationResponse,
    SegmentationImageEvaluation,
    SegmentationInstanceMatch,
    SegmentationSizeEvaluation,
    SegmentationThresholdSweepRow,
)
from reefvision.storage.projects import resolve_managed_project_path

BinaryMask: TypeAlias = Image.Image
GroupKey: TypeAlias = tuple[str, str | None]


@dataclass
class _ClassAccumulator:
    ground_truth_count: int = 0
    prediction_count: int = 0
    matches: list[SegmentationInstanceMatch] = field(default_factory=list)


@dataclass
class _ImageAccumulator:
    ground_truth_count: int = 0
    prediction_count: int = 0
    matches: list[SegmentationInstanceMatch] = field(default_factory=list)


@dataclass
class _SizeAccumulator:
    ground_truth_count: int = 0
    matches: list[SegmentationInstanceMatch] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidate:
    iou: float
    ground_truth_index: int
    prediction_index: int
    statistics: tuple[int, int, int, int, float, float, float, float]


def _polygon_points(payload: object) -> list[list[float]]:
    raw = payload
    if isinstance(raw, dict):
        raw = raw.get("points", raw.get("outer", raw.get("polygon", [])))
    if not isinstance(raw, list):
        return []
    points: list[list[float]] = []
    for item in raw:
        if isinstance(item, dict):
            x, y = item.get("x"), item.get("y")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x, y = item[0], item[1]
        else:
            continue
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            points.append([float(x), float(y)])
    return points


def _polygon_mask(
    payload: object,
    *,
    width: int,
    height: int,
) -> BinaryMask:
    points = _polygon_points(payload)
    if len(points) < 3:
        raise ValidationError("Segmentation polygon has fewer than three valid points")
    image = Image.new("L", (width, height), 0)
    ImageDraw.Draw(image).polygon(
        [(float(point[0]), float(point[1])) for point in points],
        fill=255,
    )
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
                raise ValidationError("Segmentation mask dimensions do not match the source image")
            return cast(
                Image.Image,
                source.convert("L").point(lambda value: 255 if value > 0 else 0),
            )
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Segmentation mask content could not be read") from exc


def _array(mask: BinaryMask) -> NDArray[Any]:
    return np.asarray(mask, dtype=np.uint8) > 0


def _pixel_statistics(
    ground_truth: BinaryMask,
    prediction: BinaryMask,
) -> tuple[int, int, int, int, float, float, float, float]:
    ground_truth_array = _array(ground_truth)
    prediction_array = _array(prediction)
    ground_truth_area = int(ground_truth_array.sum())
    prediction_area = int(prediction_array.sum())
    intersection = int((ground_truth_array & prediction_array).sum())
    union = ground_truth_area + prediction_area - intersection
    iou = intersection / union if union else 1.0
    denominator = ground_truth_area + prediction_area
    dice = 2 * intersection / denominator if denominator else 1.0
    precision = intersection / prediction_area if prediction_area else 0.0
    recall = intersection / ground_truth_area if ground_truth_area else 0.0
    return (
        intersection,
        union,
        ground_truth_area,
        prediction_area,
        iou,
        dice,
        precision,
        recall,
    )


def _touches_boundary(mask: BinaryMask) -> bool:
    values = _array(mask)
    return bool(
        values.size
        and (values[0, :].any() or values[-1, :].any() or values[:, 0].any() or values[:, -1].any())
    )


def _mean_optional(values: list[float | None]) -> float | None:
    observed = [value for value in values if value is not None]
    return mean(observed) if observed else None


def _main_matches(
    ground_truth_items: list[tuple[MaskAnnotation, BinaryMask]],
    prediction_items: list[tuple[PredictionProposal, BinaryMask]],
    *,
    iou_threshold: float,
) -> tuple[list[_Candidate], set[int], set[int]]:
    candidates: list[_Candidate] = []
    for ground_truth_index, (_, ground_truth_mask) in enumerate(ground_truth_items):
        for prediction_index, (_, prediction_mask) in enumerate(prediction_items):
            statistics = _pixel_statistics(ground_truth_mask, prediction_mask)
            candidates.append(
                _Candidate(
                    iou=statistics[4],
                    ground_truth_index=ground_truth_index,
                    prediction_index=prediction_index,
                    statistics=statistics,
                )
            )
    used_ground_truth: set[int] = set()
    used_predictions: set[int] = set()
    accepted: list[_Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.iou, reverse=True):
        if candidate.iou < iou_threshold:
            break
        if (
            candidate.ground_truth_index in used_ground_truth
            or candidate.prediction_index in used_predictions
        ):
            continue
        used_ground_truth.add(candidate.ground_truth_index)
        used_predictions.add(candidate.prediction_index)
        accepted.append(candidate)
    return accepted, used_ground_truth, used_predictions


def _ranked_prediction_matches(
    ground_truth_items: list[tuple[MaskAnnotation, BinaryMask]],
    prediction_items: list[tuple[PredictionProposal, BinaryMask]],
    *,
    iou_threshold: float,
    confidence_threshold: float = 0,
) -> list[tuple[float, bool]]:
    available_ground_truth = set(range(len(ground_truth_items)))
    ranked: list[tuple[float, bool]] = []
    predictions = sorted(
        (
            (index, item)
            for index, item in enumerate(prediction_items)
            if float(item[0].confidence) >= confidence_threshold
        ),
        key=lambda item: (-float(item[1][0].confidence), item[1][0].id),
    )
    for _, (proposal, prediction_mask) in predictions:
        best_index = None
        best_iou = -1.0
        for ground_truth_index in available_ground_truth:
            iou = _pixel_statistics(
                ground_truth_items[ground_truth_index][1],
                prediction_mask,
            )[4]
            if iou > best_iou:
                best_iou = iou
                best_index = ground_truth_index
        matched = best_index is not None and best_iou >= iou_threshold
        if matched and best_index is not None:
            available_ground_truth.remove(best_index)
        ranked.append((float(proposal.confidence), matched))
    return ranked


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

    def _images(self, project_id: str, requested_ids: list[str]) -> list[ImageAsset]:
        query = select(ImageAsset).where(ImageAsset.project_id == project_id)
        if requested_ids:
            query = query.where(ImageAsset.id.in_(requested_ids))
        images = list(self.session.scalars(query.order_by(ImageAsset.created_at, ImageAsset.id)))
        if requested_ids and len(images) != len(set(requested_ids)):
            raise ValidationError(
                "All requested evaluation images must exist in the selected project"
            )
        return images

    def _verified_masks(self, image_ids: list[str]) -> list[MaskAnnotation]:
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
                .order_by(
                    MaskAnnotation.image_id,
                    MaskAnnotation.created_at,
                    MaskAnnotation.id,
                )
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
        minimum_confidence = min(request.confidence_threshold, *request.confidence_sweep)
        return list(
            self.session.scalars(
                select(PredictionProposal)
                .where(
                    PredictionProposal.model_id == request.model_id,
                    PredictionProposal.image_id.in_(image_ids),
                    PredictionProposal.confidence >= minimum_confidence,
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
        if item.mask_path:
            return _raster_mask(
                self.settings,
                item.mask_path,
                width=image.width_px,
                height=image.height_px,
            )
        raise ValidationError("Segmentation record has no polygon or raster geometry")

    @staticmethod
    def _class_summary(
        label_class_id: str | None,
        accumulator: _ClassAccumulator,
    ) -> SegmentationClassEvaluation:
        matched_count = len(accumulator.matches)
        false_positives = accumulator.prediction_count - matched_count
        false_negatives = accumulator.ground_truth_count - matched_count
        panoptic = panoptic_metrics(
            [item.iou for item in accumulator.matches],
            true_positive_count=matched_count,
            false_positive_count=false_positives,
            false_negative_count=false_negatives,
        )
        return SegmentationClassEvaluation(
            label_class_id=label_class_id,
            ground_truth_count=accumulator.ground_truth_count,
            prediction_count=accumulator.prediction_count,
            matched_count=matched_count,
            false_positive_count=false_positives,
            false_negative_count=false_negatives,
            instance_precision=(
                matched_count / accumulator.prediction_count
                if accumulator.prediction_count
                else 0.0
            ),
            instance_recall=(
                matched_count / accumulator.ground_truth_count
                if accumulator.ground_truth_count
                else 0.0
            ),
            mean_iou=_mean_optional([item.iou for item in accumulator.matches]),
            mean_dice=_mean_optional([item.dice for item in accumulator.matches]),
            mean_pixel_precision=_mean_optional(
                [item.pixel_precision for item in accumulator.matches]
            ),
            mean_pixel_recall=_mean_optional([item.pixel_recall for item in accumulator.matches]),
            mean_boundary_f1=_mean_optional([item.boundary_f1 for item in accumulator.matches]),
            mean_hausdorff_distance_pixels=_mean_optional(
                [item.hausdorff_distance_pixels for item in accumulator.matches]
            ),
            mean_average_symmetric_surface_distance_pixels=_mean_optional(
                [item.average_symmetric_surface_distance_pixels for item in accumulator.matches]
            ),
            panoptic_quality=panoptic.panoptic_quality,
            segmentation_quality=panoptic.segmentation_quality,
            recognition_quality=panoptic.recognition_quality,
        )

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
        class_accumulators: dict[str | None, _ClassAccumulator] = defaultdict(_ClassAccumulator)
        image_accumulators: dict[str, _ImageAccumulator] = defaultdict(_ImageAccumulator)
        size_accumulators: dict[str, _SizeAccumulator] = defaultdict(_SizeAccumulator)
        calibration_rows: list[tuple[float, bool]] = []
        all_groups = sorted(
            set(ground_truth_by_group) | set(prediction_by_group),
            key=lambda item: (item[0], item[1] or ""),
        )

        for image_id, label_class_id in all_groups:
            ground_truth_items = ground_truth_by_group[(image_id, label_class_id)]
            all_prediction_items = prediction_by_group[(image_id, label_class_id)]
            prediction_items = [
                item
                for item in all_prediction_items
                if float(item[0].confidence) >= request.confidence_threshold
            ]
            class_accumulator = class_accumulators[label_class_id]
            image_accumulator = image_accumulators[image_id]
            class_accumulator.ground_truth_count += len(ground_truth_items)
            class_accumulator.prediction_count += len(prediction_items)
            image_accumulator.ground_truth_count += len(ground_truth_items)
            image_accumulator.prediction_count += len(prediction_items)

            ground_truth_strata: list[str] = []
            for _, ground_truth_mask in ground_truth_items:
                stratum = area_stratum(
                    int(_array(ground_truth_mask).sum()),
                    small_max_pixels=request.small_object_max_pixels,
                    large_min_pixels=request.large_object_min_pixels,
                )
                ground_truth_strata.append(stratum)
                size_accumulators[stratum].ground_truth_count += 1

            accepted, _, used_predictions = _main_matches(
                ground_truth_items,
                prediction_items,
                iou_threshold=request.match_iou_threshold,
            )
            for candidate in accepted:
                ground_truth, ground_truth_mask = ground_truth_items[candidate.ground_truth_index]
                prediction, prediction_mask = prediction_items[candidate.prediction_index]
                (
                    intersection,
                    union,
                    ground_truth_area,
                    prediction_area,
                    iou,
                    dice,
                    pixel_precision,
                    pixel_recall,
                ) = candidate.statistics
                boundary = boundary_metrics(
                    ground_truth_mask,
                    prediction_mask,
                    tolerance_pixels=request.boundary_tolerance_pixels,
                )
                stratum = ground_truth_strata[candidate.ground_truth_index]
                match = SegmentationInstanceMatch(
                    image_id=image_id,
                    label_class_id=label_class_id,
                    ground_truth_mask_id=ground_truth.id,
                    prediction_id=prediction.id,
                    intersection_pixels=intersection,
                    union_pixels=union,
                    ground_truth_area_pixels=ground_truth_area,
                    prediction_area_pixels=prediction_area,
                    size_stratum=stratum,
                    touches_image_boundary=_touches_boundary(ground_truth_mask),
                    iou=iou,
                    dice=dice,
                    pixel_precision=pixel_precision,
                    pixel_recall=pixel_recall,
                    boundary_precision=boundary.precision,
                    boundary_recall=boundary.recall,
                    boundary_f1=boundary.f1,
                    hausdorff_distance_pixels=boundary.hausdorff_distance,
                    average_symmetric_surface_distance_pixels=(
                        boundary.average_symmetric_surface_distance
                    ),
                )
                matches.append(match)
                class_accumulator.matches.append(match)
                image_accumulator.matches.append(match)
                size_accumulators[stratum].matches.append(match)

            for prediction_index, (proposal, _) in enumerate(prediction_items):
                calibration_rows.append(
                    (float(proposal.confidence), prediction_index in used_predictions)
                )

        summaries = [
            self._class_summary(label_class_id, accumulator)
            for label_class_id, accumulator in sorted(
                class_accumulators.items(),
                key=lambda item: item[0] or "",
            )
        ]
        per_image: list[SegmentationImageEvaluation] = []
        for image_id in sorted(image_by_id):
            accumulator = image_accumulators[image_id]
            matched = len(accumulator.matches)
            false_positives = accumulator.prediction_count - matched
            false_negatives = accumulator.ground_truth_count - matched
            pq = panoptic_metrics(
                [item.iou for item in accumulator.matches],
                true_positive_count=matched,
                false_positive_count=false_positives,
                false_negative_count=false_negatives,
            )
            per_image.append(
                SegmentationImageEvaluation(
                    image_id=image_id,
                    ground_truth_count=accumulator.ground_truth_count,
                    prediction_count=accumulator.prediction_count,
                    matched_count=matched,
                    false_positive_count=false_positives,
                    false_negative_count=false_negatives,
                    mean_iou=_mean_optional([item.iou for item in accumulator.matches]),
                    mean_dice=_mean_optional([item.dice for item in accumulator.matches]),
                    mean_boundary_f1=_mean_optional(
                        [item.boundary_f1 for item in accumulator.matches]
                    ),
                    panoptic_quality=pq.panoptic_quality,
                )
            )

        per_size = [
            SegmentationSizeEvaluation(
                size_stratum=stratum,
                ground_truth_count=accumulator.ground_truth_count,
                matched_count=len(accumulator.matches),
                mean_iou=_mean_optional([item.iou for item in accumulator.matches]),
                mean_boundary_f1=_mean_optional([item.boundary_f1 for item in accumulator.matches]),
            )
            for stratum, accumulator in sorted(size_accumulators.items())
        ]

        ground_truth_count = sum(item.ground_truth_count for item in summaries)
        prediction_count = sum(item.prediction_count for item in summaries)
        matched_count = len(matches)
        false_positive_count = prediction_count - matched_count
        false_negative_count = ground_truth_count - matched_count
        panoptic = panoptic_metrics(
            [item.iou for item in matches],
            true_positive_count=matched_count,
            false_positive_count=false_positive_count,
            false_negative_count=false_negative_count,
        )

        threshold_sweep: list[SegmentationThresholdSweepRow] = []
        for threshold in request.confidence_sweep:
            ranked: list[tuple[float, bool]] = []
            for group in all_groups:
                ranked.extend(
                    _ranked_prediction_matches(
                        ground_truth_by_group[group],
                        prediction_by_group[group],
                        iou_threshold=request.match_iou_threshold,
                        confidence_threshold=threshold,
                    )
                )
            true_positives = sum(matched for _, matched in ranked)
            false_positives = len(ranked) - true_positives
            false_negatives = max(0, ground_truth_count - true_positives)
            precision = true_positives / len(ranked) if ranked else 0.0
            recall = true_positives / ground_truth_count if ground_truth_count else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            threshold_sweep.append(
                SegmentationThresholdSweepRow(
                    confidence_threshold=threshold,
                    true_positive_count=true_positives,
                    false_positive_count=false_positives,
                    false_negative_count=false_negatives,
                    precision=precision,
                    recall=recall,
                    f1=f1,
                )
            )

        average_precision_rows: list[SegmentationAveragePrecisionRow] = []
        for iou_threshold in request.average_precision_iou_thresholds:
            ranked = []
            for group in all_groups:
                ranked.extend(
                    _ranked_prediction_matches(
                        ground_truth_by_group[group],
                        prediction_by_group[group],
                        iou_threshold=iou_threshold,
                    )
                )
            average_precision_rows.append(
                SegmentationAveragePrecisionRow(
                    iou_threshold=iou_threshold,
                    average_precision=average_precision(
                        ranked,
                        ground_truth_count=ground_truth_count,
                    ),
                )
            )

        calibration, expected_calibration_error = confidence_calibration(
            calibration_rows,
            bin_count=request.calibration_bin_count,
        )
        calibration_bins = [
            SegmentationCalibrationBin(
                lower=item.lower,
                upper=item.upper,
                count=item.count,
                mean_confidence=item.mean_confidence,
                empirical_match_rate=item.empirical_match_rate,
                calibration_gap=item.calibration_gap,
            )
            for item in calibration
        ]
        return SegmentationEvaluationResponse(
            project_id=project_id,
            model_id=request.model_id,
            image_count=len(images),
            ground_truth_count=ground_truth_count,
            prediction_count=prediction_count,
            matched_count=matched_count,
            false_positive_count=false_positive_count,
            false_negative_count=false_negative_count,
            instance_precision=(matched_count / prediction_count if prediction_count else 0.0),
            instance_recall=(matched_count / ground_truth_count if ground_truth_count else 0.0),
            mean_iou=_mean_optional([item.iou for item in matches]),
            mean_dice=_mean_optional([item.dice for item in matches]),
            mean_boundary_f1=_mean_optional([item.boundary_f1 for item in matches]),
            mean_hausdorff_distance_pixels=_mean_optional(
                [item.hausdorff_distance_pixels for item in matches]
            ),
            mean_average_symmetric_surface_distance_pixels=_mean_optional(
                [item.average_symmetric_surface_distance_pixels for item in matches]
            ),
            panoptic_quality=panoptic.panoptic_quality,
            segmentation_quality=panoptic.segmentation_quality,
            recognition_quality=panoptic.recognition_quality,
            expected_calibration_error=expected_calibration_error,
            mean_average_precision=(
                mean(item.average_precision for item in average_precision_rows)
                if average_precision_rows
                else 0.0
            ),
            confidence_threshold=request.confidence_threshold,
            match_iou_threshold=request.match_iou_threshold,
            boundary_tolerance_pixels=request.boundary_tolerance_pixels,
            per_class=summaries,
            per_image=per_image,
            per_size=per_size,
            threshold_sweep=threshold_sweep,
            average_precision=average_precision_rows,
            calibration_bins=calibration_bins,
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
