"""Resolve selected live sources and retain immutable, scientist-reviewed analyses."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date
from math import hypot, isfinite
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models.annotation import Annotation
from reefvision.db.models.ecology_analysis import EcologyAnalysisRecord
from reefvision.db.models.ecology_identity_annotation_evidence import (
    EcologyIdentityAnnotationEvidence,
)
from reefvision.db.models.ecology_identity_calibration_evidence import (
    EcologyIdentityCalibrationEvidence,
)
from reefvision.db.models.ecology_identity_image_evidence import EcologyIdentityImageEvidence
from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.db.models.image import ImageAsset
from reefvision.db.models.label_class import LabelClass
from reefvision.db.models.mask_annotation import MaskAnnotation
from reefvision.db.models.project import Project
from reefvision.domain.ecology_lineage_policy import (
    classify_ecological_unit_level,
    require_unique_ecological_unit_spellings,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.domain.population_unit_summaries import summarize_population_units
from reefvision.schemas.ecology_analysis import (
    AbundanceResult,
    AbundanceSelection,
    AbundanceSource,
    AbundanceUnitSummary,
    AbundanceVisit,
    CountAnnotation,
    EcologyAnalysisCreate,
    EcologyAnalysisPage,
    EcologyAnalysisRead,
    EcologyAnalysisSnapshot,
    GrowthObservation,
    GrowthResult,
    GrowthSelection,
    Metric,
    Selection,
    SourceExclusion,
    ecology_analysis_source_ids,
    validate_ecology_analysis_snapshot,
)
from reefvision.schemas.longitudinal_monitoring import (
    LongitudinalAnalysisRequest,
    MonitoringObservation,
)
from reefvision.schemas.measurements import MeasurementCalibrationUpdate
from reefvision.services.calibration_geometry import polygon_measurements_float, transform_points
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.images import recover_explicit_exif_capture_time


@dataclass(slots=True)
class DeclaredUnit:
    experimental_unit_type: str | None
    experimental_unit_id: str | None


class EcologyAnalysisService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _require_project(self, project_id: str) -> None:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")

    def _project_image(self, project_id: str, image_id: UUID) -> ImageAsset:
        image = self.session.get(ImageAsset, str(image_id))
        if image is None or image.project_id != project_id:
            raise ValidationError("Selected image must belong to the current project")
        return image

    def _growth_observation(
        self,
        project_id: str,
        metric: Metric,
        link: EcologyIdentityCalibrationEvidence,
    ) -> GrowthObservation | SourceExclusion:
        annotation = self.session.get(
            EcologyIdentityAnnotationEvidence, link.annotation_evidence_id
        )
        image_link = (
            self.session.get(EcologyIdentityImageEvidence, annotation.image_evidence_id)
            if annotation is not None
            else None
        )
        if (
            annotation is None
            or image_link is None
            or annotation.project_id != project_id
            or image_link.project_id != project_id
            or image_link.image_id != link.image_id
        ):
            raise ValidationError("Selected calibration has missing or foreign source evidence")
        image = self._project_image(project_id, UUID(link.image_id))
        identity = self.session.scalar(
            select(EcologyIdentityRevision)
            .where(EcologyIdentityRevision.project_id == project_id)
            .where(EcologyIdentityRevision.organism_key == image_link.organism_key)
            .order_by(EcologyIdentityRevision.revision.desc())
            .limit(1)
        )
        if identity is None or identity.revision != image_link.identity_revision:
            return SourceExclusion(
                source=link.id,
                reason="identity_revision_requires_review",
                source_kind="calibration",
            )
        service = EcologyIdentityService(self.session)
        service._assert_image_source_metadata(image)
        revision, annotation_sha = service._annotation_source(
            annotation.annotation_kind, annotation.annotation_id, image.id
        )
        calibration, calibration_sha = service._calibration_source(image)
        if (
            revision != annotation.annotation_revision
            or annotation_sha != annotation.annotation_sha256
            or calibration_sha != link.calibration_sha256
            or calibration != link.calibration_json
            or image.sha256 != link.image_sha256
            or image.sha256 != image_link.image_sha256
        ):
            raise ValidationError("Selected growth annotation or calibration changed after linking")
        captured = image.capture_timestamp
        recovered = service.frozen_explicit_capture_time(image, image_link.source_metadata_sha256)
        if image_link.source_metadata_sha256 is None:
            return SourceExclusion(
                source=link.id, reason="capture_metadata_not_frozen", source_kind="calibration"
            )
        if (
            recovered is None
            and image_link.source_metadata_sha256 != service._source_metadata_fingerprint(image)
        ):
            raise ValidationError("Selected growth source metadata changed after linking")
        observed = (
            captured.astimezone(UTC)
            if captured is not None
            and captured.tzinfo is not None
            and captured.utcoffset() is not None
            else recovered
        )
        if observed is None:
            return SourceExclusion(
                source=link.id, reason="missing_aware_capture_time", source_kind="calibration"
            )
        calibration_payload = MeasurementCalibrationUpdate.model_validate(calibration)
        measurement = self._growth_measurement(metric, annotation, calibration_payload)
        if measurement is None:
            return SourceExclusion(
                source=link.id, reason="incompatible_geometry", source_kind="calibration"
            )
        value, unit = measurement
        if not isfinite(value) or value <= 0:
            raise ValidationError("Selected growth does not yield a finite positive measurement")
        return GrowthObservation(
            calibration_evidence_id=UUID(link.id),
            annotation_evidence_id=UUID(annotation.id),
            image_evidence_id=UUID(image_link.id),
            identity_id=UUID(identity.id),
            annotation_id=UUID(annotation.annotation_id),
            annotation_kind="box" if annotation.annotation_kind == "box" else "mask",
            image_id=UUID(image.id),
            organism_key=identity.organism_key,
            parent_colony_key=identity.parent_colony_key,
            identity_revision=image_link.identity_revision,
            annotation_revision=revision,
            image_sha256=image.sha256,
            annotation_sha256=annotation_sha,
            calibration_sha256=calibration_sha,
            calibration_source=calibration_payload.source,
            measurement_method=(
                "reference_plane_homography"
                if calibration_payload.perspective_homography
                else "scalar_image_plane"
            ),
            experimental_unit_type=identity.experimental_unit_type,
            experimental_unit_id=identity.experimental_unit_id,
            observed_at=observed,
            value=value,
            unit=unit,
        )

    def _growth_measurement(
        self,
        metric: Metric,
        annotation: EcologyIdentityAnnotationEvidence,
        calibration: MeasurementCalibrationUpdate,
    ) -> tuple[float, str] | None:
        matrix = calibration.perspective_homography
        if metric == "mask_projected_area":
            mask = self.session.get(MaskAnnotation, annotation.annotation_id)
            if annotation.annotation_kind != "mask" or mask is None or mask.area_pixels is None:
                return None
            unit = f"{calibration.unit}^2"
            if matrix is None:
                if mask.polygon_json:
                    points = [(x, y) for x, y in mask.polygon_json]
                    area = polygon_measurements_float(points)[0]
                else:
                    area = mask.area_pixels
                scale = calibration.distance_per_pixel
                return area * scale * scale, unit
            if not mask.polygon_json:
                return None
            polygon = [(x, y) for x, y in mask.polygon_json]
            projected = self._project_growth_points(matrix, polygon)
            return polygon_measurements_float(projected)[0], unit
        box = self.session.get(Annotation, annotation.annotation_id)
        if annotation.annotation_kind != "box" or box is None:
            return None
        # Measure across each box's central width or height axis on the reference plane.
        x_center = (box.x_min + box.x_max) / 2
        y_center = (box.y_min + box.y_max) / 2
        points = (
            [(box.x_min, y_center), (box.x_max, y_center)]
            if metric == "box_width"
            else [(x_center, box.y_min), (x_center, box.y_max)]
        )
        if matrix is not None:
            points = self._project_growth_points(matrix, points)
        (x0, y0), (x1, y1) = points
        scale = calibration.distance_per_pixel if matrix is None else 1
        return hypot(x1 - x0, y1 - y0) * scale, calibration.unit

    @staticmethod
    def _project_growth_points(
        matrix: list[list[float]], points: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        denominators = [matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] for x, y in points]
        if not all(isfinite(value) for value in denominators) or min(denominators) <= 0 <= max(
            denominators
        ):
            raise ValidationError("Selected geometry crosses the projective horizon")
        return transform_points(matrix, points)

    def _growth(self, project_id: str, selection: GrowthSelection) -> GrowthResult:
        selected_ids = [str(row.calibration_evidence_id) for row in selection.sources]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValidationError("An observation cannot be selected twice")
        observations: list[GrowthObservation] = []
        exclusions: list[SourceExclusion] = []
        occupied: set[tuple[str, str]] = set()
        for item in sorted(selection.sources, key=lambda row: str(row.calibration_evidence_id)):
            item_id = str(item.calibration_evidence_id)
            link = self.session.get(EcologyIdentityCalibrationEvidence, item_id)
            if link is None or link.project_id != project_id:
                raise ValidationError(
                    "Selected calibration evidence must belong to the current project"
                )
            if item.exclusion_reason is not None:
                exclusions.append(
                    SourceExclusion(
                        source=item_id, reason=item.exclusion_reason, source_kind="calibration"
                    )
                )
                continue
            observation = self._growth_observation(project_id, selection.metric, link)
            if isinstance(observation, SourceExclusion):
                exclusions.append(observation)
                continue
            key = (observation.organism_key, observation.image_sha256.casefold())
            if key in occupied:
                raise ValidationError("Select only one measurement per organism and image")
            occupied.add(key)
            observations.append(observation)
        grouped: dict[str, list[GrowthObservation]] = defaultdict(list)
        for row in observations:
            grouped[row.organism_key].append(row)
        # Keep the complete reviewed input roster so exclusions can be audited.
        comparable: list[GrowthObservation] = []
        complete_organisms: set[str] = set()
        for organism_key, repeats in grouped.items():
            if len(repeats) < 2:
                reason = "missing_follow_up"
            elif len({row.unit for row in repeats}) != 1:
                reason = "incomparable_units"
            elif len({row.measurement_method for row in repeats}) != 1:
                reason = "incomparable_calibration_methods"
            elif len({row.observed_at.date() for row in repeats}) != len(repeats):
                reason = "duplicate_utc_sampling_date"
            else:
                comparable.extend(repeats)
                complete_organisms.add(organism_key)
                continue
            exclusions.append(
                SourceExclusion(source=organism_key, reason=reason, source_kind="organism")
            )
        if len(comparable) < 2:
            return GrowthResult(observations=observations, exclusions=exclusions)
        units = {row.experimental_unit_id for row in comparable}
        # A project with partial declarations has organism endpoints only.
        use_units = None not in units and not any(
            row.source_kind == "calibration" for row in exclusions
        )
        if not use_units and any(unit is not None for unit in units):
            exclusions.append(
                SourceExclusion(
                    source="Declared sampling units",
                    source_kind="unit",
                    reason="Unit summaries require comparable sources and complete assignments",
                )
            )
        try:
            calculation = analyze_longitudinal(
                LongitudinalAnalysisRequest(
                    observations=[
                        MonitoringObservation(
                            organism_id=row.organism_key,
                            parent_colony_id=row.parent_colony_key,
                            source_record_id=str(row.calibration_evidence_id),
                            metric_name=selection.metric,
                            observed_at=row.observed_at,
                            value=row.value,
                            unit=row.unit,
                            experimental_unit_id=row.experimental_unit_id if use_units else None,
                            experimental_unit_type=row.experimental_unit_type
                            if use_units
                            else None,
                        )
                        for row in comparable
                    ],
                )
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        # Units with selected but unusable series cannot enter population summaries.
        incomplete_unit_ids = {
            row.experimental_unit_id
            for row in observations
            if row.organism_key not in complete_organisms
        }
        unit_summaries = [
            row
            for row in calculation.unit_summaries
            if row.experimental_unit_id not in incomplete_unit_ids
        ]
        exclusions.extend(
            SourceExclusion(source=row.experimental_unit_id, reason=row.reason, source_kind="unit")
            for row in calculation.excluded_units
        )
        return GrowthResult(
            observations=observations,
            changes=calculation.changes,
            unit_summaries=unit_summaries,
            population_summaries=summarize_population_units(unit_summaries),
            exclusions=exclusions,
        )

    def _abundance_visit(
        self, image: ImageAsset, class_id: str, item: AbundanceSource, unit_type: str
    ) -> AbundanceVisit:
        if image.annotation_status != "reviewed" or image.width_px <= 0 or image.height_px <= 0:
            raise ValidationError("Abundance requires a reviewed image and valid source geometry")
        captured = image.capture_timestamp
        explicit = None
        if captured is not None:
            explicit = (
                captured.astimezone(UTC)
                if captured.tzinfo is not None
                else recover_explicit_exif_capture_time(captured, image.metadata_json)
            )
        if explicit is not None and explicit.date() != item.observed_at.date():
            raise ValidationError("Survey date disagrees with the source image UTC capture date")
        annotations = self.session.scalars(
            select(Annotation)
            .where(
                Annotation.image_id == image.id,
                Annotation.label_class_id == class_id,
                Annotation.deleted_at.is_(None),
            )
            .order_by(Annotation.id)
        )
        rows = []
        geometry = set()
        for annotation in annotations:
            bounds = (annotation.x_min, annotation.y_min, annotation.x_max, annotation.y_max)
            if (
                not all(isfinite(value) for value in bounds)
                or not 0 <= annotation.x_min < annotation.x_max <= image.width_px
                or not 0 <= annotation.y_min < annotation.y_max <= image.height_px
                or annotation.revision < 1
                or annotation.source_type
                not in {"human", "accepted_prediction", "imported_yolo", "imported"}
            ):
                raise ValidationError("Selected survey contains a noncanonical annotation")
            if bounds in geometry:
                raise ValidationError("Selected survey contains duplicate bounding boxes")
            geometry.add(bounds)
            rows.append(
                CountAnnotation(
                    annotation_id=UUID(annotation.id),
                    revision=annotation.revision,
                    source_type=annotation.source_type,
                    geometry_sha256=canonical_json_sha256(bounds),
                    bounds=bounds,
                )
            )
        count = len(rows)
        area = item.surveyed_area_m2
        density = count / area if area is not None else None
        if density is not None and not isfinite(density):
            raise ValidationError("Surveyed area does not yield a finite density")
        return AbundanceVisit(
            image_id=UUID(image.id),
            image_sha256=image.sha256,
            annotation_revision=image.annotation_revision,
            width_px=image.width_px,
            height_px=image.height_px,
            captured_at=explicit,
            sample_id=item.sample_id,
            experimental_unit_type=unit_type,
            experimental_unit_id=item.experimental_unit_id,
            observed_at=item.observed_at,
            annotations=rows,
            count=count,
            surveyed_area_m2=area,
            density_per_m2=density,
        )

    def _abundance(self, project_id: str, selection: AbundanceSelection) -> AbundanceResult:
        label_class = self.session.get(LabelClass, str(selection.class_id))
        if label_class is None or label_class.project_id != project_id:
            raise ValidationError("Survey class must belong to the current project")
        try:
            require_unique_ecological_unit_spellings(
                DeclaredUnit(item.experimental_unit_type, item.experimental_unit_id)
                for item in selection.sources
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        visits: list[AbundanceVisit] = []
        exclusions: list[SourceExclusion] = []
        visited: set[tuple[str, str, str, date]] = set()
        unit_by_sample: dict[str, tuple[str, str]] = {}
        used_images: set[str] = set()
        used_unit_types: set[str] = set()
        groups: dict[tuple[date, str, str], list[AbundanceVisit]] = defaultdict(list)
        missing_groups: dict[tuple[date, str, str], int] = defaultdict(int)
        for item in sorted(selection.sources, key=lambda row: (row.observed_at, row.sample_id)):
            unit_type = classify_ecological_unit_level(item.experimental_unit_type)
            if unit_type is None:
                raise ValidationError("Use an organism, colony, tank or site survey sampling level")
            used_unit_types.add(unit_type)
            unit = (unit_type, item.experimental_unit_id)
            sample_key = item.sample_id.casefold()
            if unit_by_sample.setdefault(sample_key, unit) != unit:
                raise ValidationError("A repeated survey sample cannot change experimental unit")
            observed_on = item.observed_at.date()
            key = (*unit, sample_key, observed_on)
            if key in visited:
                raise ValidationError("Duplicate survey sample on one UTC date")
            visited.add(key)
            image = self._project_image(project_id, item.image_id) if item.image_id else None
            if image is not None:
                if image.sha256 in used_images:
                    raise ValidationError("The same image cannot represent multiple survey samples")
                used_images.add(image.sha256)
            group_key = (observed_on, *unit)
            if item.exclusion_reason is not None:
                exclusions.append(
                    SourceExclusion(
                        source=item.sample_id, reason=item.exclusion_reason, source_kind="sample"
                    )
                )
                missing_groups[group_key] += 1
                continue
            if image is None:
                raise ValidationError("Missing survey image requires an exclusion reason")
            visit = self._abundance_visit(image, label_class.id, item, unit_type)
            visits.append(visit)
            groups[group_key].append(visit)
        if len(used_unit_types) > 1:
            raise ValidationError("Survey uses mixed experimental-unit levels")
        summaries = []
        for (observed_on, unit_type, unit_id), rows in sorted(groups.items()):
            total = sum(row.count for row in rows)
            areas = [row.surveyed_area_m2 for row in rows if row.surveyed_area_m2 is not None]
            complete = (observed_on, unit_type, unit_id) not in missing_groups
            area = sum(areas) if complete and len(areas) == len(rows) else None
            density = total / area if area else None
            if (area is not None and not isfinite(area)) or (
                density is not None and not isfinite(density)
            ):
                raise ValidationError("Survey unit does not yield a finite aggregate density")
            summaries.append(
                AbundanceUnitSummary(
                    observed_on=observed_on,
                    experimental_unit_type=unit_type,
                    experimental_unit_id=unit_id,
                    sample_count=len(rows),
                    excluded_sample_count=missing_groups.get((observed_on, unit_type, unit_id), 0),
                    total_count=total,
                    surveyed_area_m2=area,
                    density_per_m2=density,
                )
            )
        return AbundanceResult(
            class_name=label_class.name,
            visits=visits,
            unit_summaries=summaries,
            exclusions=exclusions,
        )

    def _compute(self, project_id: str, selection: Selection) -> GrowthResult | AbundanceResult:
        if isinstance(selection, GrowthSelection):
            return self._growth(project_id, selection)
        return self._abundance(project_id, selection)

    def _record(self, project_id: str, analysis_id: str) -> EcologyAnalysisRecord:
        row = self.session.get(EcologyAnalysisRecord, analysis_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Ecological analysis not found in project")
        return row

    def _response(self, row: EcologyAnalysisRecord) -> EcologyAnalysisRead:
        snapshot = validate_ecology_analysis_snapshot(row.snapshot_json, row.content_sha256)
        stale_reason = None
        try:
            if row.source_id_map_json:
                if not self._recheck_mapped_sources(row, snapshot):
                    stale_reason = "Selected imported evidence changed after review."
            elif self._compute(row.project_id, snapshot.selection) != snapshot.result:
                stale_reason = "Selected source evidence changed after review."
        except (ValidationError, ConflictError, NotFoundError, ValueError):
            stale_reason = "Selected source evidence is missing, stale or no longer comparable."
        return EcologyAnalysisRead(
            id=UUID(row.id),
            project_id=UUID(row.project_id),
            supersedes_id=UUID(row.supersedes_id) if row.supersedes_id else None,
            created_at=row.created_at.replace(tzinfo=UTC)
            if row.created_at.tzinfo is None
            else row.created_at,
            content_sha256=row.content_sha256,
            stale=stale_reason is not None,
            stale_reason=stale_reason,
            source_id_map=row.source_id_map_json,
            snapshot=snapshot,
        )

    def _recheck_mapped_sources(
        self, row: EcologyAnalysisRecord, snapshot: EcologyAnalysisSnapshot
    ) -> bool:
        source_ids = ecology_analysis_source_ids(row.snapshot_json)
        mapping = row.source_id_map_json
        if set(mapping) != source_ids or len(set(mapping.values())) != len(mapping):
            return False
        saved = deepcopy(row.snapshot_json)
        selection = snapshot.selection
        expected = saved["result"]
        if isinstance(selection, GrowthSelection):
            result = self._compute(
                row.project_id,
                selection.model_copy(
                    update={
                        "sources": [
                            item.model_copy(
                                update={
                                    "calibration_evidence_id": UUID(
                                        mapping[str(item.calibration_evidence_id)]
                                    )
                                }
                            )
                            for item in selection.sources
                        ]
                    }
                ),
            )
            current = result.model_dump(mode="json")
            keys = (
                "calibration_evidence_id",
                "annotation_evidence_id",
                "image_evidence_id",
                "identity_id",
                "annotation_id",
                "image_id",
            )
            for item in expected["observations"]:
                for key in keys:
                    item[key] = mapping[item[key]]
            # Local annotation/calibration digests carry IDs. Live source
            # resolution already rechecks each imported link against its data.
            for item in expected["observations"] + current["observations"]:
                item.pop("annotation_sha256")
                item.pop("calibration_sha256")
            for change in expected["changes"]:
                for key in ("baseline_source_record_id", "final_source_record_id"):
                    change[key] = mapping[change[key]]
            for exclusion in expected["exclusions"]:
                if exclusion["source_kind"] == "calibration":
                    exclusion["source"] = mapping[exclusion["source"]]
            for payload in (expected, current):
                payload["observations"].sort(key=lambda item: item["calibration_evidence_id"])
                payload["exclusions"].sort(key=lambda item: (item["source"], item["reason"]))
            return bool(expected == current)
        mapped = selection.model_copy(
            update={
                "class_id": UUID(mapping[str(selection.class_id)]),
                "sources": [
                    item.model_copy(update={"image_id": UUID(mapping[str(item.image_id)])})
                    if item.image_id
                    else item
                    for item in selection.sources
                ],
            },
        )
        current = self._compute(row.project_id, mapped).model_dump(mode="json")
        for visit in expected["visits"]:
            visit["image_id"] = mapping[visit["image_id"]]
            for annotation in visit["annotations"]:
                annotation["annotation_id"] = mapping[annotation["annotation_id"]]
            visit["annotations"].sort(key=lambda item: item["annotation_id"])
        return bool(expected == current)

    def get(self, project_id: str, analysis_id: str) -> EcologyAnalysisRead:
        return self._response(self._record(project_id, analysis_id))

    def list(self, project_id: str, page: int, page_size: int) -> EcologyAnalysisPage:
        self._require_project(project_id)
        query = select(EcologyAnalysisRecord).where(EcologyAnalysisRecord.project_id == project_id)
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(EcologyAnalysisRecord.created_at.desc(), EcologyAnalysisRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return EcologyAnalysisPage(
            items=[self._response(row) for row in rows], total=total, page=page, page_size=page_size
        )

    def save(self, project_id: str, payload: EcologyAnalysisCreate) -> EcologyAnalysisRead:
        self._require_project(project_id)
        supersedes_id = str(payload.supersedes_id) if payload.supersedes_id else None
        if supersedes_id:
            previous = self._record(project_id, supersedes_id)
            if previous.kind != payload.selection.kind:
                raise ValidationError("Recalculation must retain the original analysis kind")
        result = self._compute(project_id, payload.selection)
        limitations = [
            "Selected evidence supports descriptive analysis only. "
            "Population inference and survival estimates require additional evidence.",
            "Sampling units are researcher-declared. "
            "Biological independence requires study-design verification.",
        ]
        if isinstance(result, GrowthResult):
            limitations.append(
                "Growth describes calibrated image-plane geometry. "
                "Depth and volume require separate measurements."
            )
        else:
            limitations.append(
                "Counts describe annotated sample detections. Density requires reviewed, "
                "nonoverlapping surveyed areas. Missing visits are recorded as exclusions."
            )
        snapshot: dict[str, Any] = EcologyAnalysisSnapshot(
            selection=payload.selection,
            reviewed_by=payload.reviewed_by,
            review_note=payload.review_note,
            result=result,
            limitations=limitations,
        ).model_dump(mode="json")
        row = EcologyAnalysisRecord(
            project_id=project_id,
            supersedes_id=supersedes_id,
            kind=payload.selection.kind,
            snapshot_json=snapshot,
            content_sha256=canonical_json_sha256(snapshot),
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._response(row)
