"""Conservative projected measurements from registered ecological evidence.

These source-linked values are *not* verified longitudinal observations:
identity, timepoint, experimental independence and projection remain subject
to scientist review. No predictions or unreviewed source masks are accepted.
"""

from __future__ import annotations

import math
from datetime import UTC

from sqlalchemy.orm import Session

from reefvision.db.models.annotation import Annotation
from reefvision.db.models.image import ImageAsset
from reefvision.db.models.mask_annotation import MaskAnnotation
from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyMeasurementCandidatesResponse,
    EcologyMeasurementExclusion,
    EcologyProjectedEndpointChange,
    EcologySamplingDateQC,
)
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.storage.datasets import canonical_json_sha256


def summarize_sampling_date_qc(
    candidates: list[EcologyMeasurementCandidate],
) -> list[EcologySamplingDateQC]:
    """Audit candidate dates without converting unverified evidence into growth.

    Each organism/metric is evaluated separately. Multiple captures on the
    same UTC day are technical replicates, not independent time points.
    """
    groups: dict[tuple[str, str], list[EcologyMeasurementCandidate]] = {}
    for candidate in candidates:
        key = (candidate.organism_key, candidate.metric)
        groups.setdefault(key, []).append(candidate)

    rows: list[EcologySamplingDateQC] = []
    for (organism_key, metric), records in sorted(groups.items()):
        date_counts: dict[str, int] = {}
        missing_timestamp_image_ids: set[str] = set()
        for record in records:
            captured = record.capture_timestamp_utc
            if (
                record.capture_time_status != "timezone_aware"
                or captured is None
                or captured.tzinfo is None
                or captured.utcoffset() is None
            ):
                missing_timestamp_image_ids.add(record.image_id)
                continue
            utc_date = captured.astimezone(UTC).date().isoformat()
            date_counts[utc_date] = date_counts.get(utc_date, 0) + 1

        units = sorted({record.unit for record in records})
        duplicate_dates = sorted(date for date, count in date_counts.items() if count > 1)
        contexts = {
            (
                record.identity_revision,
                record.parent_colony_key,
                record.experimental_unit_type,
                record.experimental_unit_id,
            )
            for record in records
        }
        if len(contexts) > 1:
            qc_status = "identity_context_changed"
        elif len(units) > 1:
            qc_status = "mixed_units"
        elif missing_timestamp_image_ids:
            qc_status = "missing_timestamps"
        elif duplicate_dates:
            qc_status = "same_day_technical_replicates"
        elif len(date_counts) < 2:
            qc_status = "insufficient_dates"
        else:
            qc_status = "date_series_candidate"

        rows.append(
            EcologySamplingDateQC(
                organism_key=organism_key,
                metric=metric,
                candidate_count=len(records),
                source_image_ids=sorted({record.image_id for record in records}),
                units=units,
                sampling_dates_utc=sorted(date_counts),
                duplicate_sampling_dates_utc=duplicate_dates,
                missing_timestamp_image_ids=sorted(missing_timestamp_image_ids),
                qc_status=qc_status,
            )
        )
    return rows


def summarize_projected_endpoint_changes(
    candidates: list[EcologyMeasurementCandidate],
    sampling_date_qc: list[EcologySamplingDateQC],
) -> list[EcologyProjectedEndpointChange]:
    """Compare source-linked projected endpoints without inferring biological growth.

    Exclude series with technical replicates, inconsistent identity/unit
    provenance, missing acquisition timezones, or fewer than two UTC dates.
    Every included value still requires independent scientist review.
    """
    groups: dict[tuple[str, str], list[EcologyMeasurementCandidate]] = {}
    for candidate in candidates:
        groups.setdefault((candidate.organism_key, candidate.metric), []).append(candidate)

    changes: list[EcologyProjectedEndpointChange] = []
    for audit in sampling_date_qc:
        if audit.qc_status != "date_series_candidate":
            continue
        records = sorted(
            groups[(audit.organism_key, audit.metric)],
            key=lambda row: (
                row.capture_timestamp_utc,
                row.image_id,
                row.annotation_evidence_id,
            ),
        )
        first, last = records[0], records[-1]
        start = first.capture_timestamp_utc
        end = last.capture_timestamp_utc
        if start is None or end is None:
            raise ValidationError("Projected endpoint series requires dated source images")
        elapsed_days = (end - start).total_seconds() / 86400
        difference = last.value - first.value
        percent_change = 100 * (difference / first.value)
        if not all(
            math.isfinite(value) for value in (elapsed_days, difference, percent_change)
        ) or elapsed_days <= 0:
            raise ValidationError("Projected endpoint change is nonfinite or unordered")
        changes.append(
            EcologyProjectedEndpointChange(
                organism_key=first.organism_key,
                metric=first.metric,
                identity_revision=first.identity_revision,
                parent_colony_key=first.parent_colony_key,
                experimental_unit_type=first.experimental_unit_type,
                experimental_unit_id=first.experimental_unit_id,
                unit=first.unit,
                baseline_capture_timestamp_utc=start.astimezone(UTC),
                final_capture_timestamp_utc=end.astimezone(UTC),
                baseline_image_id=first.image_id,
                final_image_id=last.image_id,
                baseline_annotation_evidence_id=first.annotation_evidence_id,
                final_annotation_evidence_id=last.annotation_evidence_id,
                baseline_calibration_evidence_id=first.calibration_evidence_id,
                final_calibration_evidence_id=last.calibration_evidence_id,
                baseline_value=first.value,
                final_value=last.value,
                absolute_change=difference,
                percent_change=percent_change,
                elapsed_days=elapsed_days,
                observed_timepoint_count=len(records),
            )
        )
    return changes


class EcologyMeasurementCandidateService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def candidates(
        self,
        project_id: str,
        *,
        registry: EcologyIdentityRegistryResponse | None = None,
    ) -> EcologyMeasurementCandidatesResponse:
        # The existing registry validates project ownership, human review,
        # annotation revisions, source-image fingerprints and frozen calibration.
        snapshot = registry or EcologyIdentityService(self.session).registry(project_id)
        if snapshot.project_id != project_id:
            raise ValidationError("Measurement registry belongs to another project")
        identities = {row.organism_key: row for row in snapshot.identities}
        image_links = {row.id: row for row in snapshot.image_evidence_links}
        annotations = {row.id: row for row in snapshot.annotation_evidence_links}
        candidates: list[EcologyMeasurementCandidate] = []
        exclusions: list[EcologyMeasurementExclusion] = []
        for calibration in sorted(snapshot.calibration_evidence_links, key=lambda row: row.id):
            annotation = annotations[calibration.annotation_evidence_id]
            image_link = image_links[annotation.image_evidence_id]
            identity = identities[image_link.organism_key]
            image = self.session.get(ImageAsset, calibration.image_id)
            if image is None or image.project_id != project_id:
                raise ValidationError("Ecological measurement source image is missing")
            # A perspective homography needs per-point reprojection, not a
            # naive scalar area/length conversion. Never mislabel it as growth.
            if calibration.calibration_json.get("perspective_homography") is not None:
                exclusions.append(
                    EcologyMeasurementExclusion(
                        calibration_evidence_id=calibration.id,
                        reason="perspective_transform_requires_review",
                    )
                )
                continue
            scale = float(calibration.calibration_json["distance_per_pixel"])
            unit = str(calibration.calibration_json["unit"])
            source = (
                self.session.get(Annotation, annotation.annotation_id)
                if annotation.annotation_kind == "box"
                else self.session.get(MaskAnnotation, annotation.annotation_id)
            )
            if source is None:
                raise ValidationError("Ecological measurement annotation is missing")
            if annotation.annotation_kind == "box":
                assert isinstance(source, Annotation)
                values = [
                    ("box_width", (source.x_max - source.x_min) * scale, unit),
                    ("box_height", (source.y_max - source.y_min) * scale, unit),
                ]
            else:
                assert isinstance(source, MaskAnnotation)
                values = (
                    [
                        (
                            "mask_projected_area",
                            float(source.area_pixels) * scale * scale,
                            f"{unit}^2",
                        )
                    ]
                    if source.area_pixels is not None
                    else []
                )
            if not values:
                exclusions.append(
                    EcologyMeasurementExclusion(
                        calibration_evidence_id=calibration.id,
                        reason="unsupported_geometry",
                    )
                )
                continue
            captured = image.capture_timestamp
            if captured is None:
                time_status = "missing"
                captured_utc = None
            elif captured.tzinfo is None or captured.utcoffset() is None:
                time_status = "timezone_missing"
                captured_utc = None
            else:
                time_status = "timezone_aware"
                captured_utc = captured.astimezone(UTC)
            for metric, value, metric_unit in values:
                if not math.isfinite(value) or value <= 0:
                    raise ValidationError(
                        "Ecological projected measurement must be positive and finite"
                    )
                candidates.append(
                    EcologyMeasurementCandidate(
                        organism_key=identity.organism_key,
                        identity_revision=image_link.identity_revision,
                        parent_colony_key=identity.parent_colony_key,
                        experimental_unit_type=identity.experimental_unit_type,
                        experimental_unit_id=identity.experimental_unit_id,
                        image_id=image.id,
                        image_sha256=image.sha256,
                        annotation_evidence_id=annotation.id,
                        calibration_evidence_id=calibration.id,
                        annotation_kind=annotation.annotation_kind,
                        annotation_id=annotation.annotation_id,
                        annotation_revision=annotation.annotation_revision,
                        annotation_sha256=annotation.annotation_sha256,
                        calibration_sha256=calibration.calibration_sha256,
                        metric=metric,
                        value=value,
                        unit=metric_unit,
                        capture_timestamp_utc=captured_utc,
                        capture_time_status=time_status,
                    )
                )
        candidates.sort(
            key=lambda row: (
                row.organism_key,
                row.image_id,
                row.annotation_kind,
                row.annotation_id,
                row.metric,
            )
        )
        sampling_date_qc = summarize_sampling_date_qc(candidates)
        projected_changes = summarize_projected_endpoint_changes(candidates, sampling_date_qc)
        rows = [row.model_dump(mode="json") for row in candidates]
        qc_rows = [row.model_dump(mode="json") for row in sampling_date_qc]
        change_rows = [row.model_dump(mode="json") for row in projected_changes]
        skipped = [row.model_dump(mode="json") for row in exclusions]
        fingerprint = canonical_json_sha256(
            {
                "algorithm_version": "ecology-measurement-candidates-0003",
                "project_id": project_id,
                "registry_history_sha256": snapshot.history_sha256,
                "registry_image_evidence_sha256": snapshot.image_evidence_sha256,
                "registry_annotation_evidence_sha256": snapshot.annotation_evidence_sha256,
                "registry_calibration_evidence_sha256": snapshot.calibration_evidence_sha256,
                "candidates": rows,
                "sampling_date_qc": qc_rows,
                "projected_endpoint_changes": change_rows,
                "exclusions": skipped,
            }
        )
        return EcologyMeasurementCandidatesResponse(
            project_id=project_id,
            source_registry_history_sha256=snapshot.history_sha256,
            source_calibration_evidence_sha256=snapshot.calibration_evidence_sha256,
            candidates=candidates,
            candidate_count=len(candidates),
            sampling_date_qc=sampling_date_qc,
            projected_endpoint_changes=projected_changes,
            exclusions=exclusions,
            input_sha256=fingerprint,
        )
