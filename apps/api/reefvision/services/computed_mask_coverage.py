"""Immutable source-pixel union area and coverage from verified masks."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, LabelClass, MaskAnnotation, Project
from reefvision.db.models.computed_metric import ComputedMetricDefinition, ComputedMetricResult
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.mask_coverage_geometry import PixelRuns, intersect_runs, run_area, union_runs
from reefvision.domain.scientific_units import UNITS
from reefvision.schemas.computed_mask_coverage import (
    ComputedMaskCoverageDefinitionCreate,
    ComputedMaskCoverageDefinitionPage,
    ComputedMaskCoverageDefinitionResponse,
    ComputedMaskCoveragePreview,
    ComputedMaskCoverageResultPage,
    ComputedMaskCoverageResultResponse,
    ComputedMaskCoverageValidationResponse,
    MaskCoverageClassArea,
    MaskCoverageGroupSummary,
    MaskCoverageImageSummary,
)
from reefvision.schemas.measurements import MeasurementCalibrationUpdate
from reefvision.services.scientific_data import content_hash
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_metric_masks import png_to_runs, polygon_to_runs

FORMULA_VERSION = "reefvision.mask-coverage.v1"
SCHEMA_VERSION = "1.1.0"
ALGORITHM = "reefvision.source-pixel-mask-union.v1"
DEFINITION_KIND = "mask_coverage"
RESULT_KIND = "mask_coverage"
CALIBRATION_KEY = "measurement_calibration"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _configuration(payload: ComputedMaskCoverageDefinitionCreate) -> dict[str, Any]:
    grouping = payload.grouping_level
    roi_label = str(payload.roi_label_class_id) if payload.roi_label_class_id else None
    return {
        "schema_version": SCHEMA_VERSION,
        "grouping_level": grouping,
        "label_class_ids": [str(value) for value in payload.label_class_ids],
        "roi_label_class_id": roi_label,
        "operation": "verified_mask_union_coverage",
        "required_review_state": "reviewed",
        "independence_contract": (
            "one_unit_per_image" if grouping == "image" else "one_unit_per_image_group_key"
        ),
        "roi_contract": "verified_mask_class_union" if roi_label else "full_image",
    }


def _definition_payload(row: ComputedMetricDefinition) -> dict[str, Any]:
    return {
        "name": row.name,
        "expression": row.expression,
        "formula_version": row.formula_version,
        "output_unit": row.output_unit,
        "configuration": row.configuration_json,
    }


def _area_in_square_metres(value: float, unit: str) -> float:
    dimension, _, scale, _ = UNITS[unit]
    if dimension != "length":
        raise ValueError("Physical area requires a supported length unit")
    return value * scale * scale


class ComputedMaskCoverageService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def require_project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def create_definition(
        self, project_id: str, payload: ComputedMaskCoverageDefinitionCreate
    ) -> ComputedMetricDefinition:
        self.require_project(project_id)
        label_ids = [str(value) for value in payload.label_class_ids]
        if payload.roi_label_class_id is not None:
            label_ids.append(str(payload.roi_label_class_id))
        if label_ids:
            labels = self.session.scalars(
                select(LabelClass).where(LabelClass.id.in_(label_ids))
            ).all()
            if len(labels) != len(set(label_ids)) or any(
                row.project_id != project_id for row in labels
            ):
                raise ValidationError(
                    "All target and ROI label classes must belong to this project"
                )
        configuration = _configuration(payload)
        row = ComputedMetricDefinition(
            id=str(uuid4()),
            project_id=project_id,
            definition_kind=DEFINITION_KIND,
            name=payload.name,
            expression="union_area(verified_masks) / explicit_denominator",
            formula_version=FORMULA_VERSION,
            input_spec_json=[],
            configuration_json=configuration,
            output_unit="percent",
            definition_sha256="",
        )
        row.definition_sha256 = content_hash(_definition_payload(row))
        self.session.add(row)
        self.session.flush()
        return row

    def definition_response(
        self, row: ComputedMetricDefinition
    ) -> ComputedMaskCoverageDefinitionResponse:
        if row.definition_kind != DEFINITION_KIND or row.configuration_json is None:
            raise ValidationError("Metric definition is not a mask coverage definition")
        if content_hash(_definition_payload(row)) != row.definition_sha256:
            raise ConflictError("Mask coverage definition checksum mismatch")
        return ComputedMaskCoverageDefinitionResponse.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "name": row.name,
                "definition_kind": row.definition_kind,
                "expression": row.expression,
                "formula_version": row.formula_version,
                "output_unit": row.output_unit,
                "definition_sha256": row.definition_sha256,
                "created_at": _utc(row.created_at),
                **row.configuration_json,
            }
        )

    def get_definition(self, project_id: str, definition_id: str) -> ComputedMetricDefinition:
        row = self.session.get(ComputedMetricDefinition, definition_id)
        if row is None or row.project_id != project_id or row.definition_kind != DEFINITION_KIND:
            raise NotFoundError("Mask coverage definition not found")
        self.definition_response(row)
        return row

    def list_definitions(
        self, project_id: str, *, limit: int, offset: int
    ) -> ComputedMaskCoverageDefinitionPage:
        self.require_project(project_id)
        query = select(ComputedMetricDefinition).where(
            ComputedMetricDefinition.project_id == project_id,
            ComputedMetricDefinition.definition_kind == DEFINITION_KIND,
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ComputedMetricDefinition.created_at, ComputedMetricDefinition.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ComputedMaskCoverageDefinitionPage(
            items=[self.definition_response(row) for row in rows], total=total
        )

    def _resolve_images(self, project_id: str, image_ids: list[str]) -> list[ImageAsset]:
        rows = self.session.scalars(
            select(ImageAsset).where(ImageAsset.id.in_(image_ids)).order_by(ImageAsset.id)
        ).all()
        if len(rows) != len(image_ids) or any(row.project_id != project_id for row in rows):
            raise ValidationError("All selected images must belong to this project")
        if any(row.annotation_status != "reviewed" for row in rows):
            raise ValidationError("All selected images must have reviewed annotation status")
        return list(rows)

    def _mask_runs(self, mask: MaskAnnotation, image: ImageAsset) -> tuple[PixelRuns, str | None]:
        if mask.geometry_kind == "polygon":
            if not mask.polygon_json:
                raise ValidationError(f"Verified polygon mask has missing geometry: {mask.id}")
            try:
                return (
                    polygon_to_runs(
                        mask.polygon_json,
                        width=image.width_px,
                        height=image.height_px,
                    ),
                    None,
                )
            except ValueError as exc:
                raise ValidationError(f"Verified polygon mask is invalid: {mask.id}") from exc
        if mask.geometry_kind == "raster_mask":
            if not mask.mask_path:
                raise ValidationError(f"Verified raster mask content is missing: {mask.id}")
            try:
                payload = resolve_managed_project_path(self.settings, mask.mask_path).read_bytes()
                return (
                    png_to_runs(payload, width=image.width_px, height=image.height_px),
                    hashlib.sha256(payload).hexdigest(),
                )
            except (OSError, ValueError) as exc:
                raise ValidationError(f"Verified raster mask is unreadable: {mask.id}") from exc
        raise ValidationError(f"Verified mask geometry is unsupported: {mask.id}")

    @staticmethod
    def _calibration(image: ImageAsset) -> tuple[Any | None, str | None]:
        raw = dict(image.metadata_json or {}).get(CALIBRATION_KEY)
        if raw is None:
            return None, "missing_calibration"
        if not isinstance(raw, dict):
            return raw, "invalid_calibration"
        try:
            calibration = MeasurementCalibrationUpdate.model_validate(raw)
        except PydanticValidationError:
            return raw, "invalid_calibration"
        snapshot = calibration.model_dump(mode="json")
        if calibration.unit not in UNITS or UNITS[calibration.unit][0] != "length":
            return snapshot, "unsupported_calibration_unit"
        if calibration.perspective_homography is not None:
            return snapshot, "perspective_homography_requires_union_resampling"
        return snapshot, None

    @staticmethod
    def _class_areas(
        masks: list[MaskAnnotation],
        runs_by_id: dict[str, PixelRuns],
        labels: dict[str, str],
        *,
        scale: float | None = None,
        physical_unit: str | None = None,
    ) -> list[MaskCoverageClassArea]:
        by_label: dict[str | None, list[MaskAnnotation]] = defaultdict(list)
        for mask in masks:
            by_label[mask.label_class_id].append(mask)
        output: list[MaskCoverageClassArea] = []
        for label_id, rows in sorted(by_label.items(), key=lambda item: str(item[0] or "")):
            union_pixels = run_area(union_runs(*(runs_by_id[row.id] for row in rows)))
            output.append(
                MaskCoverageClassArea(
                    label_class_id=label_id,
                    label_name=labels.get(str(label_id), "Unclassified"),
                    mask_count=len(rows),
                    summed_mask_area_pixels=sum(run_area(runs_by_id[row.id]) for row in rows),
                    union_area_pixels=union_pixels,
                    physical_unit=physical_unit,
                    union_area_physical=(
                        union_pixels * scale * scale if scale is not None else None
                    ),
                )
            )
        return output

    @staticmethod
    def _aggregate_summaries(
        images: list[MaskCoverageImageSummary],
        *,
        unit_key: str | None = None,
    ) -> dict[str, Any]:
        mask_count = sum(item.mask_count for item in images)
        density_object_count = sum(item.density_object_count for item in images)
        summed = sum(item.summed_mask_area_pixels for item in images)
        union = sum(item.union_area_pixels for item in images)
        image_denominator = sum(item.image_denominator_pixels for item in images)
        has_roi = all(item.roi_denominator_pixels is not None for item in images)
        roi_denominator = (
            sum(int(item.roi_denominator_pixels or 0) for item in images) if has_roi else None
        )
        target_in_roi = (
            sum(int(item.target_union_in_roi_pixels or 0) for item in images) if has_roi else None
        )
        class_rows: dict[tuple[str | None, str], list[MaskCoverageClassArea]] = defaultdict(list)
        for image in images:
            for item in image.area_by_class:
                key = (str(item.label_class_id) if item.label_class_id else None, item.label_name)
                class_rows[key].append(item)
        area_by_class = [
            MaskCoverageClassArea(
                label_class_id=label_id,
                label_name=label_name,
                mask_count=sum(row.mask_count for row in rows),
                summed_mask_area_pixels=sum(row.summed_mask_area_pixels for row in rows),
                union_area_pixels=sum(row.union_area_pixels for row in rows),
                physical_unit=(
                    next(iter({row.physical_unit for row in rows}))
                    if all(row.union_area_physical is not None for row in rows)
                    and len({row.physical_unit for row in rows}) == 1
                    else ("m" if all(row.union_area_physical is not None for row in rows) else None)
                ),
                union_area_physical=(
                    sum(float(row.union_area_physical or 0) for row in rows)
                    if all(row.union_area_physical is not None for row in rows)
                    and len({row.physical_unit for row in rows}) == 1
                    else (
                        sum(
                            _area_in_square_metres(
                                float(row.union_area_physical or 0), str(row.physical_unit)
                            )
                            for row in rows
                        )
                        if all(row.union_area_physical is not None for row in rows)
                        else None
                    )
                ),
            )
            for (label_id, label_name), rows in sorted(
                class_rows.items(), key=lambda item: str(item[0][0] or "")
            )
        ]
        physical_ready = all(item.union_area_physical is not None for item in images)
        units = {item.physical_unit for item in images if item.physical_unit is not None}
        same_unit = len(units) == 1
        physical_unit = (
            next(iter(units)) if physical_ready and same_unit else ("m" if physical_ready else None)
        )
        physical_reason: str | None = None
        if not physical_ready:
            physical_reason = next(
                (
                    item.physical_unavailable_reason
                    for item in images
                    if item.physical_unavailable_reason
                ),
                "incomplete_calibration",
            )
        union_physical = (
            (
                sum(float(item.union_area_physical or 0) for item in images)
                if same_unit
                else sum(
                    _area_in_square_metres(
                        float(item.union_area_physical or 0), str(item.physical_unit)
                    )
                    for item in images
                )
            )
            if physical_ready
            else None
        )
        sampling_physical = (
            (
                sum(float(item.sampling_area_physical or 0) for item in images)
                if same_unit
                else sum(
                    _area_in_square_metres(
                        float(item.sampling_area_physical or 0), str(item.physical_unit)
                    )
                    for item in images
                )
            )
            if physical_ready
            else None
        )
        return {
            "mask_count": mask_count,
            "density_object_count": density_object_count,
            "summed_mask_area_pixels": summed,
            "union_area_pixels": union,
            "overlap_area_pixels": summed - union,
            "image_denominator_pixels": image_denominator,
            "image_coverage_percent": union / image_denominator * 100.0,
            "roi_denominator_pixels": roi_denominator,
            "target_union_in_roi_pixels": target_in_roi,
            "roi_coverage_percent": (
                target_in_roi / roi_denominator * 100.0
                if target_in_roi is not None and roi_denominator
                else None
            ),
            "area_by_class": area_by_class,
            "physical_unit": physical_unit,
            "union_area_physical": union_physical,
            "sampling_area_physical": sampling_physical,
            "object_density_per_square_unit": (
                density_object_count / sampling_physical if sampling_physical else None
            ),
            "calibration_method": (
                "scalar_distance_per_pixel" if physical_unit is not None else None
            ),
            "physical_unavailable_reason": physical_reason,
            **({"unit_key": unit_key} if unit_key is not None else {}),
        }

    def _build_preview(
        self, definition: ComputedMetricDefinition, image_ids: list[str]
    ) -> ComputedMaskCoveragePreview:
        config = definition.configuration_json or {}
        images = self._resolve_images(definition.project_id, image_ids)
        grouping = str(config["grouping_level"])
        if grouping == "image_group_key" and any(
            not image.group_key or not image.group_key.strip() for image in images
        ):
            raise ValidationError("Image group key is required for group-key aggregation")
        target_labels = set(config.get("label_class_ids", []))
        roi_label = config.get("roi_label_class_id")
        selected_ids = [image.id for image in images]
        mask_rows = list(
            self.session.scalars(
                select(MaskAnnotation)
                .where(
                    MaskAnnotation.image_id.in_(selected_ids),
                    MaskAnnotation.deleted_at.is_(None),
                    MaskAnnotation.status == "verified",
                )
                .order_by(MaskAnnotation.id)
            ).all()
        )
        target_masks = [
            row
            for row in mask_rows
            if row.label_class_id != roi_label
            and (not target_labels or row.label_class_id in target_labels)
        ]
        roi_masks = [row for row in mask_rows if roi_label and row.label_class_id == roi_label]
        observed_label_ids = {
            row.label_class_id for row in [*target_masks, *roi_masks] if row.label_class_id
        }
        labels = {
            row.id: row.name
            for row in self.session.scalars(
                select(LabelClass).where(LabelClass.id.in_(observed_label_ids))
            ).all()
        }
        masks_by_image: dict[str, list[MaskAnnotation]] = defaultdict(list)
        roi_by_image: dict[str, list[MaskAnnotation]] = defaultdict(list)
        for row in target_masks:
            masks_by_image[row.image_id].append(row)
        for row in roi_masks:
            roi_by_image[row.image_id].append(row)

        runs_by_id: dict[str, PixelRuns] = {}
        content_hash_by_id: dict[str, str | None] = {}
        image_by_id = {image.id: image for image in images}
        for mask in [*target_masks, *roi_masks]:
            runs, raster_hash = self._mask_runs(mask, image_by_id[mask.image_id])
            runs_by_id[mask.id] = runs
            content_hash_by_id[mask.id] = raster_hash

        image_summaries: list[MaskCoverageImageSummary] = []
        image_snapshots: list[dict[str, Any]] = []
        for image in images:
            targets = masks_by_image[image.id]
            rois = roi_by_image[image.id]
            target_union = union_runs(*(runs_by_id[row.id] for row in targets))
            target_union_area = run_area(target_union)
            summed = sum(run_area(runs_by_id[row.id]) for row in targets)
            roi_runs = union_runs(*(runs_by_id[row.id] for row in rois))
            roi_area = run_area(roi_runs) if roi_label else None
            if roi_label and not roi_area:
                raise ValidationError(
                    f"Selected image is missing a nonempty verified ROI: {image.id}"
                )
            target_in_roi = run_area(intersect_runs(target_union, roi_runs)) if roi_label else None
            density_object_count = (
                sum(
                    1
                    for row in targets
                    if run_area(intersect_runs(runs_by_id[row.id], roi_runs)) > 0
                )
                if roi_label
                else len(targets)
            )
            calibration, unavailable = self._calibration(image)
            physical_unit: str | None = None
            scale: float | None = None
            union_physical: float | None = None
            sampling_physical: float | None = None
            if calibration is not None and unavailable is None:
                scale = float(calibration["distance_per_pixel"])
                physical_unit = str(calibration["unit"])
                union_physical = target_union_area * scale * scale
                denominator_pixels = int(roi_area or image.width_px * image.height_px)
                sampling_physical = denominator_pixels * scale * scale
            unit_key = image.id if grouping == "image" else str(image.group_key)
            class_areas = self._class_areas(
                targets,
                runs_by_id,
                labels,
                scale=scale,
                physical_unit=physical_unit,
            )
            image_summaries.append(
                MaskCoverageImageSummary(
                    image_id=image.id,
                    unit_key=unit_key,
                    width_px=image.width_px,
                    height_px=image.height_px,
                    mask_count=len(targets),
                    density_object_count=density_object_count,
                    summed_mask_area_pixels=summed,
                    union_area_pixels=target_union_area,
                    overlap_area_pixels=summed - target_union_area,
                    image_denominator_pixels=image.width_px * image.height_px,
                    image_coverage_percent=(
                        target_union_area / (image.width_px * image.height_px) * 100.0
                    ),
                    roi_denominator_pixels=roi_area,
                    target_union_in_roi_pixels=target_in_roi,
                    roi_coverage_percent=(
                        target_in_roi / roi_area * 100.0
                        if target_in_roi is not None and roi_area
                        else None
                    ),
                    area_by_class=class_areas,
                    physical_unit=physical_unit,
                    union_area_physical=union_physical,
                    sampling_area_physical=sampling_physical,
                    object_density_per_square_unit=(
                        density_object_count / sampling_physical if sampling_physical else None
                    ),
                    calibration_method=(
                        "scalar_distance_per_pixel" if physical_unit is not None else None
                    ),
                    physical_unavailable_reason=unavailable,
                )
            )
            image_snapshots.append(
                {
                    "image_id": image.id,
                    "sha256": image.sha256,
                    "width_px": image.width_px,
                    "height_px": image.height_px,
                    "annotation_revision": image.annotation_revision,
                    "annotation_status": image.annotation_status,
                    "group_key": image.group_key,
                    "updated_at": _utc(image.updated_at).isoformat(),
                    "calibration": calibration,
                    "physical_unavailable_reason": unavailable,
                }
            )

        mask_snapshot = [
            {
                "id": row.id,
                "image_id": row.image_id,
                "role": "roi" if row.label_class_id == roi_label else "target",
                "label_class_id": row.label_class_id,
                "label_name": labels.get(str(row.label_class_id), "Unclassified"),
                "geometry_kind": row.geometry_kind,
                "polygon": row.polygon_json,
                "mask_path": row.mask_path,
                "mask_content_sha256": content_hash_by_id[row.id],
                "source_type": row.source_type,
                "status": row.status,
                "revision": row.revision,
                "area_pixels": run_area(runs_by_id[row.id]),
            }
            for row in sorted([*target_masks, *roi_masks], key=lambda item: item.id)
        ]
        evidence = {
            "definition_sha256": definition.definition_sha256,
            "algorithm": ALGORITHM,
            "coordinate_frame": "source_image_pixels",
            "images": image_snapshots,
            "masks": mask_snapshot,
        }
        overall = self._aggregate_summaries(image_summaries)
        grouped: dict[str, list[MaskCoverageImageSummary]] = defaultdict(list)
        for item in image_summaries:
            grouped[item.unit_key].append(item)
        groups = [
            MaskCoverageGroupSummary(
                image_ids=[item.image_id for item in grouped[key]],
                **self._aggregate_summaries(grouped[key], unit_key=key),
            )
            for key in sorted(grouped)
        ]
        return ComputedMaskCoveragePreview(
            definition_id=definition.id,
            definition_sha256=definition.definition_sha256,
            grouping_level=grouping,
            roi_contract=str(config["roi_contract"]),
            image_count=len(images),
            independent_unit_count=len(groups),
            algorithm=ALGORITHM,
            coordinate_frame="source_image_pixels",
            images=image_summaries,
            groups=groups,
            image_snapshot=image_snapshots,
            mask_snapshot=mask_snapshot,
            evidence_sha256=content_hash(evidence),
            **overall,
        )

    def preview(
        self, project_id: str, definition_id: str, image_ids: list[str]
    ) -> ComputedMaskCoveragePreview:
        return self._build_preview(self.get_definition(project_id, definition_id), image_ids)

    def calculate(
        self,
        project_id: str,
        definition_id: str,
        image_ids: list[str],
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> ComputedMetricResult:
        definition = self.get_definition(project_id, definition_id)
        if workflow_node_run_id is not None:
            existing = self.session.scalar(
                select(ComputedMetricResult).where(
                    ComputedMetricResult.workflow_node_run_id == workflow_node_run_id
                )
            )
            if existing is not None:
                response = self.result_response(existing)
                saved_ids = sorted(str(item["image_id"]) for item in response.image_snapshot)
                if (
                    existing.project_id != project_id
                    or existing.definition_id != definition_id
                    or saved_ids != sorted(image_ids)
                    or existing.workflow_run_id != workflow_run_id
                ):
                    raise ConflictError("Workflow mask coverage replay conflicts with its result")
                return existing
        preview = self._build_preview(definition, image_ids)
        observed_at = max(
            _utc(image.updated_at) for image in self._resolve_images(project_id, image_ids)
        )
        payload = {
            **preview.model_dump(mode="json"),
            "definition_name": definition.name,
            "expression": definition.expression,
            "formula_version": definition.formula_version,
            "output_unit": definition.output_unit,
            "observed_at": observed_at.isoformat(),
            "provenance": {
                "definition_sha256": definition.definition_sha256,
                "evidence_sha256": preview.evidence_sha256,
                "selection_is_explicit": True,
                "verified_masks_only": True,
                "predictions_counted": False,
                "algorithm": ALGORITHM,
                "coordinate_frame": "source_image_pixels",
                "density_numerator": "verified_target_masks_intersecting_sampling_region",
                "density_denominator": "verified_roi_area_or_full_image_area",
            },
        }
        row = ComputedMetricResult(
            id=str(uuid4()),
            project_id=project_id,
            result_kind=RESULT_KIND,
            definition_id=definition.id,
            observed_at=observed_at,
            payload_json=payload,
            content_sha256=content_hash(payload),
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def result_response(self, row: ComputedMetricResult) -> ComputedMaskCoverageResultResponse:
        if row.result_kind != RESULT_KIND:
            raise ValidationError("Computed result is not a mask coverage result")
        if content_hash(row.payload_json) != row.content_sha256:
            raise ConflictError("Mask coverage result checksum mismatch")
        return ComputedMaskCoverageResultResponse.model_validate(
            {
                **row.payload_json,
                "id": row.id,
                "project_id": row.project_id,
                "result_kind": row.result_kind,
                "content_sha256": row.content_sha256,
                "workflow_run_id": row.workflow_run_id,
                "workflow_node_run_id": row.workflow_node_run_id,
                "created_at": _utc(row.created_at),
            }
        )

    def list_results(
        self, project_id: str, *, limit: int, offset: int
    ) -> ComputedMaskCoverageResultPage:
        self.require_project(project_id)
        query = select(ComputedMetricResult).where(
            ComputedMetricResult.project_id == project_id,
            ComputedMetricResult.result_kind == RESULT_KIND,
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ComputedMetricResult.created_at, ComputedMetricResult.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ComputedMaskCoverageResultPage(
            items=[self.result_response(row) for row in rows], total=total
        )

    def validate_result(
        self, project_id: str, result_id: str
    ) -> ComputedMaskCoverageValidationResponse:
        self.require_project(project_id)
        row = self.session.get(ComputedMetricResult, result_id)
        if row is None or row.project_id != project_id or row.result_kind != RESULT_KIND:
            raise NotFoundError("Mask coverage result not found")
        saved = self.result_response(row)
        image_ids = sorted(str(item["image_id"]) for item in saved.image_snapshot)
        reasons: list[str] = []
        try:
            current = self.preview(project_id, str(saved.definition_id), image_ids)
            current_hash = current.evidence_sha256
            if current_hash != saved.evidence_sha256:
                reasons.append("evidence_snapshot_changed")
            comparable_fields = (
                "mask_count",
                "density_object_count",
                "summed_mask_area_pixels",
                "union_area_pixels",
                "overlap_area_pixels",
                "image_denominator_pixels",
                "image_coverage_percent",
                "roi_denominator_pixels",
                "target_union_in_roi_pixels",
                "roi_coverage_percent",
                "area_by_class",
                "physical_unit",
                "union_area_physical",
                "sampling_area_physical",
                "object_density_per_square_unit",
                "calibration_method",
                "physical_unavailable_reason",
                "images",
                "groups",
            )
            saved_payload = saved.model_dump(mode="json")
            current_payload = current.model_dump(mode="json")
            if any(saved_payload[field] != current_payload[field] for field in comparable_fields):
                reasons.append("result_summary_mismatch")
        except (ValidationError, NotFoundError, ValueError) as exc:
            reasons.append(f"recompute_failed:{exc}")
            current_hash = content_hash({"error": str(exc)})
        return ComputedMaskCoverageValidationResponse(
            result_id=row.id,
            current=current_hash == saved.evidence_sha256 and not reasons,
            saved_evidence_sha256=saved.evidence_sha256,
            current_evidence_sha256=current_hash,
            reasons=reasons,
        )

    def export_csv(self, project_id: str) -> str:
        results = self.list_results(project_id, limit=500, offset=0).items
        fieldnames = [
            "row_kind",
            "result_id",
            "definition_id",
            "unit_key",
            "image_ids_json",
            "mask_count",
            "density_object_count",
            "summed_mask_area_pixels",
            "union_area_pixels",
            "overlap_area_pixels",
            "image_denominator_pixels",
            "image_coverage_percent",
            "roi_denominator_pixels",
            "target_union_in_roi_pixels",
            "roi_coverage_percent",
            "area_by_class_json",
            "physical_unit",
            "union_area_physical",
            "sampling_area_physical",
            "object_density_per_square_unit",
            "physical_unavailable_reason",
            "algorithm",
            "coordinate_frame",
            "definition_sha256",
            "evidence_sha256",
            "content_sha256",
            "observed_at_utc",
        ]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in results:
            common = {
                "result_id": str(item.id),
                "definition_id": str(item.definition_id),
                "algorithm": item.algorithm,
                "coordinate_frame": item.coordinate_frame,
                "definition_sha256": item.definition_sha256,
                "evidence_sha256": item.evidence_sha256,
                "content_sha256": item.content_sha256,
                "observed_at_utc": item.observed_at.isoformat(),
            }
            summaries: list[tuple[str, str, list[str], Any]] = [
                (
                    "overall",
                    "",
                    [str(row["image_id"]) for row in item.image_snapshot],
                    item,
                )
            ]
            summaries.extend(
                ("image", image.unit_key, [str(image.image_id)], image) for image in item.images
            )
            summaries.extend(
                ("group", group.unit_key, [str(value) for value in group.image_ids], group)
                for group in item.groups
            )
            for row_kind, unit_key, image_ids, summary in summaries:
                writer.writerow(
                    {
                        **common,
                        "row_kind": row_kind,
                        "unit_key": unit_key,
                        "image_ids_json": json.dumps(image_ids),
                        "mask_count": summary.mask_count,
                        "density_object_count": summary.density_object_count,
                        "summed_mask_area_pixels": summary.summed_mask_area_pixels,
                        "union_area_pixels": summary.union_area_pixels,
                        "overlap_area_pixels": summary.overlap_area_pixels,
                        "image_denominator_pixels": summary.image_denominator_pixels,
                        "image_coverage_percent": summary.image_coverage_percent,
                        "roi_denominator_pixels": summary.roi_denominator_pixels,
                        "target_union_in_roi_pixels": summary.target_union_in_roi_pixels,
                        "roi_coverage_percent": summary.roi_coverage_percent,
                        "area_by_class_json": json.dumps(
                            [row.model_dump(mode="json") for row in summary.area_by_class],
                            sort_keys=True,
                        ),
                        "physical_unit": summary.physical_unit or "",
                        "union_area_physical": summary.union_area_physical,
                        "sampling_area_physical": summary.sampling_area_physical,
                        "object_density_per_square_unit": summary.object_density_per_square_unit,
                        "physical_unavailable_reason": summary.physical_unavailable_reason or "",
                    }
                )
        return output.getvalue()
