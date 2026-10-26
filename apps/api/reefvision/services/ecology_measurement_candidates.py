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
from reefvision.domain.ecology_lineage_policy import classify_ecological_unit_level
from reefvision.domain.errors import ValidationError
from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyCandidateReport,
    EcologyMeasurementCandidate,
    EcologyMeasurementCandidatesResponse,
    EcologyMeasurementExclusion,
    EcologyProjectedEndpointChange,
    EcologyProjectedPopulationSummary,
    EcologyProjectedUnitSummary,
    EcologyProjectedVisitCoverage,
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
    # A photograph can contain several organisms and measurement types. Check
    # replayed source IDs and identical bytes across the *entire* observation
    # batch: per-organism/metric checks alone miss cross-series date forgery.
    source_image_dates: dict[str, set[str]] = {}
    source_content_dates: dict[str, set[str]] = {}
    # The same physical photograph cannot have two acquisition instants or
    # different content under one image ID, even within one UTC sampling day.
    # Normalize offsets first so equivalent instants remain valid.
    source_image_metadata: dict[str, set[tuple[str, str, str | None]]] = {}
    source_content_instants: dict[str, set[str]] = {}
    # A reimported photograph with missing acquisition metadata must not
    # inherit a dated copy's timepoint without scientist review.
    source_content_missing_times: set[str] = set()
    for candidate in candidates:
        captured = candidate.capture_timestamp_utc
        aware = (
            candidate.capture_time_status == "timezone_aware"
            and captured is not None
            and captured.tzinfo is not None
            and captured.utcoffset() is not None
        )
        utc_instant = captured.astimezone(UTC).isoformat() if aware and captured else None
        source_image_metadata.setdefault(candidate.image_id, set()).add(
            (candidate.image_sha256, candidate.capture_time_status, utc_instant)
        )
        if utc_instant is None:
            source_content_missing_times.add(candidate.image_sha256)
            continue
        utc_date = utc_instant[:10]
        source_image_dates.setdefault(candidate.image_id, set()).add(utc_date)
        source_content_dates.setdefault(candidate.image_sha256, set()).add(utc_date)
        source_content_instants.setdefault(candidate.image_sha256, set()).add(utc_instant)

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
        reused_image_ids = sorted(
            {
                record.image_id
                for record in records
                if len(source_image_dates.get(record.image_id, set())) > 1
            }
        )
        reused_image_sha256 = sorted(
            {
                record.image_sha256
                for record in records
                if len(source_content_dates.get(record.image_sha256, set())) > 1
            }
        )
        conflicting_source_image_ids = sorted(
            {
                record.image_id
                for record in records
                if len(source_image_metadata[record.image_id]) > 1
            }
        )
        conflicting_source_image_sha256 = sorted(
            {
                record.image_sha256
                for record in records
                if len(source_content_instants.get(record.image_sha256, set())) > 1
                or (
                    record.image_sha256 in source_content_missing_times
                    and bool(source_content_instants.get(record.image_sha256))
                )
            }
        )
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
        elif reused_image_ids:
            qc_status = "reused_image_across_dates"
        elif reused_image_sha256:
            qc_status = "reused_image_content_across_dates"
        elif conflicting_source_image_ids or conflicting_source_image_sha256:
            qc_status = "source_capture_conflict"
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
                reused_image_ids=reused_image_ids,
                reused_image_sha256=reused_image_sha256,
                conflicting_source_image_ids=conflicting_source_image_ids,
                conflicting_source_image_sha256=conflicting_source_image_sha256,
                qc_status=qc_status,
            )
        )
    return rows


def summarize_projected_visit_coverage(
    candidates: list[EcologyMeasurementCandidate],
) -> list[EcologyProjectedVisitCoverage]:
    """Audit linked measurements per observed UTC date, never organism presence.

    The comparison set contains only organisms with linked measurements in
    this unit/metric/physical-unit series. It is not a planned study roster;
    missing links are not evidence of absence, mortality or zero abundance.
    """
    groups: dict[tuple[str | None, str | None, str, str], list[EcologyMeasurementCandidate]] = {}
    for candidate in candidates:
        unit_type = candidate.experimental_unit_type
        unit_id = candidate.experimental_unit_id
        # Without a declared biological unit, unrelated organisms must not
        # be silently pooled into one synthetic "None" sampling group.
        if not unit_type or not unit_id or not unit_id.strip():
            continue
        try:
            require_ecological_unit_type(unit_type)
        except ValueError:
            # Image/frame/crop labels are technical replicates, not units.
            continue
        # Canonicalize known biological aliases before computing observed-visit
        # coverage. Otherwise tank/aquarium labels on the same physical unit
        # create separate rosters and conceal missing linked measurements.
        # Unknown study-specific labels remain unverified and unchanged.
        canonical_type = classify_ecological_unit_level(unit_type) or unit_type
        group_key = (canonical_type, unit_id, candidate.metric, candidate.unit)
        groups.setdefault(group_key, []).append(candidate)

    coverage: list[EcologyProjectedVisitCoverage] = []
    for unit_type, unit_id, metric, unit in sorted(
        groups, key=lambda group_key: tuple(part or "" for part in group_key)
    ):
        records = groups[(unit_type, unit_id, metric, unit)]
        series_keys = sorted({record.organism_key for record in records})
        undated_keys: set[str] = set()
        by_date: dict[str, list[str]] = {}
        for record in records:
            captured = record.capture_timestamp_utc
            if (
                record.capture_time_status != "timezone_aware"
                or captured is None
                or captured.tzinfo is None
                or captured.utcoffset() is None
            ):
                undated_keys.add(record.organism_key)
                continue
            date = captured.astimezone(UTC).date().isoformat()
            by_date.setdefault(date, []).append(record.organism_key)

        for date, measured in sorted(by_date.items()):
            counts: dict[str, int] = {}
            for organism_key in measured:
                counts[organism_key] = counts.get(organism_key, 0) + 1
            measured_keys = sorted(counts)
            coverage.append(
                EcologyProjectedVisitCoverage(
                    experimental_unit_type=unit_type,
                    experimental_unit_id=unit_id,
                    metric=metric,
                    unit=unit,
                    sampling_date_utc=date,
                    series_organism_keys=series_keys,
                    measured_organism_keys=measured_keys,
                    no_linked_measurement_organism_keys=sorted(
                        set(series_keys) - set(measured_keys)
                    ),
                    undated_organism_keys=sorted(undated_keys),
                    same_day_repeat_organism_keys=sorted(
                        organism_key for organism_key, count in counts.items() if count > 1
                    ),
                    linked_measurement_count=len(measured),
                )
            )
    return coverage


def summarize_projected_endpoint_changes(
    candidates: list[EcologyMeasurementCandidate],
    sampling_date_qc: list[EcologySamplingDateQC],
) -> list[EcologyProjectedEndpointChange]:
    """Compare source-linked projected endpoints without inferring biological growth.

    Exclude series with technical replicates, inconsistent identity/unit
    provenance, missing acquisition timezones, or fewer than two UTC dates.
    Every included value still requires independent scientist review.
    """
    # A previously calculated QC decision must never authorize endpoint
    # changes after source dates, units or identity context have changed.
    expected_qc = {
        (row.organism_key, row.metric): row.model_dump(mode="json")
        for row in summarize_sampling_date_qc(candidates)
    }
    supplied_qc = {
        (row.organism_key, row.metric): row.model_dump(mode="json") for row in sampling_date_qc
    }
    if len(supplied_qc) != len(sampling_date_qc) or supplied_qc != expected_qc:
        raise ValidationError("Projected endpoint sampling-date QC does not match sources")

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
        if not math.isfinite(elapsed_days) or elapsed_days <= 0:
            raise ValidationError("Projected endpoint change is nonfinite or unordered")
        difference = last.value - first.value
        percent_change = 100 * (difference / first.value)
        # Normalize by actual elapsed UTC time, not the number of sampling
        # dates. These slopes describe projected geometry, never growth.
        absolute_per_day = difference / elapsed_days
        baseline_percent_per_day = percent_change / elapsed_days
        finite_values = [
            difference,
            percent_change,
            absolute_per_day,
            baseline_percent_per_day,
        ]
        if not all(math.isfinite(value) for value in finite_values):
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
                projected_absolute_change_per_day=absolute_per_day,
                projected_baseline_percent_change_per_day=baseline_percent_per_day,
                observed_timepoint_count=len(records),
            )
        )
    return changes


def summarize_projected_unit_summaries(
    candidates: list[EcologyMeasurementCandidate],
    changes: list[EcologyProjectedEndpointChange],
) -> list[EcologyProjectedUnitSummary]:
    """Provisional one-row-per-unit summaries, never biological inference.

    Incomplete organisms or mismatched UTC windows exclude the whole unit.
    Image/frame/annotation records cannot be independent ecological units.
    """
    # An organism's identity revision, parent colony and experimental-unit
    # assignment must agree across *all* metrics, not only within each
    # metric's time series. Otherwise one specimen can enter different
    # unit-level analyses under contradictory design assignments.
    organism_contexts: dict[str, tuple[int, str | None, str | None, str | None]] = {}
    for candidate in candidates:
        context = (
            candidate.identity_revision,
            candidate.parent_colony_key,
            candidate.experimental_unit_type,
            candidate.experimental_unit_id,
        )
        previous = organism_contexts.setdefault(candidate.organism_key, context)
        if previous != context:
            raise ValidationError(
                "Projected organism identity or experimental unit changed across metrics"
            )

    groups: dict[tuple[str | None, str | None, str], list[EcologyMeasurementCandidate]] = {}
    for candidate in candidates:
        key = (
            candidate.experimental_unit_type,
            candidate.experimental_unit_id,
            candidate.metric,
        )
        groups.setdefault(key, []).append(candidate)
    change_index: dict[tuple[str, str], EcologyProjectedEndpointChange] = {
        (row.organism_key, row.metric): row for row in changes
    }
    if len(change_index) != len(changes):
        raise ValidationError("Duplicate projected organism endpoint changes")
    # Revalidate the supplied endpoint changes against current source records.
    # A stale or fabricated endpoint cannot become an experimental-unit mean.
    recomputed = summarize_projected_endpoint_changes(
        candidates, summarize_sampling_date_qc(candidates)
    )
    expected_changes = {
        (row.organism_key, row.metric): row.model_dump(mode="json") for row in recomputed
    }
    provided_changes = {key: row.model_dump(mode="json") for key, row in change_index.items()}
    if provided_changes != expected_changes:
        raise ValidationError("Projected unit endpoint changes do not match source candidates")

    results: list[EcologyProjectedUnitSummary] = []
    for unit_type, unit_id, metric in sorted(
        groups, key=lambda key: tuple(part or "" for part in key)
    ):
        records = groups[(unit_type, unit_id, metric)]
        organism_keys = sorted({row.organism_key for row in records})
        units = sorted({row.unit for row in records})
        parent_keys = sorted({row.parent_colony_key for row in records if row.parent_colony_key})
        completed = [
            change_index[(organism_key, metric)]
            for organism_key in organism_keys
            if (organism_key, metric) in change_index
        ]
        complete_keys = sorted(row.organism_key for row in completed)
        incomplete_keys = sorted(set(organism_keys) - set(complete_keys))
        windows = sorted(
            {
                f"{row.baseline_capture_timestamp_utc.astimezone(UTC).date()}/"
                f"{row.final_capture_timestamp_utc.astimezone(UTC).date()}"
                for row in completed
            }
        )
        if not unit_type or not unit_id or not unit_id.strip():
            status = "missing_unit_declaration"
        else:
            try:
                require_ecological_unit_type(unit_type)
            except ValueError:
                status = "technical_replicate_unit"
            else:
                status = "candidate"
        if status == "candidate":
            if len(units) != 1:
                status = "mixed_units"
            elif incomplete_keys:
                status = "incomplete_followup"
            elif len(windows) != 1:
                status = "sampling_window_mismatch"

        mean_absolute: float | None = None
        mean_percent: float | None = None
        if status == "candidate":
            count = len(completed)
            try:
                mean_absolute = math.fsum(row.absolute_change / count for row in completed)
                mean_percent = math.fsum(row.percent_change / count for row in completed)
            except OverflowError as exc:
                raise ValidationError("Projected unit summary is nonfinite") from exc
            if not math.isfinite(mean_absolute) or not math.isfinite(mean_percent):
                raise ValidationError("Projected unit summary is nonfinite")

        results.append(
            EcologyProjectedUnitSummary(
                experimental_unit_type=unit_type,
                experimental_unit_id=unit_id,
                metric=metric,
                units=units,
                organism_keys=organism_keys,
                complete_organism_keys=complete_keys,
                incomplete_organism_keys=incomplete_keys,
                parent_colony_keys=parent_keys,
                sampling_windows_utc=windows,
                unit_status=status,
                mean_absolute_change=mean_absolute,
                mean_percent_change=mean_percent,
            )
        )
    return results


def summarize_projected_population_summaries(
    unit_summaries: list[EcologyProjectedUnitSummary],
) -> list[EcologyProjectedPopulationSummary]:
    """Stratified descriptive means with one vote per eligible declared unit.

    Units with failed QC are never pooled. Different measurement dimensions,
    normalized biological unit levels and UTC sampling windows remain separate strata.
    Parent-colony reuse across units is disclosed, not assumed independent.
    """
    # One biological organism cannot contribute as an independent replicate
    # in two declared experimental units, even across sampling strata.
    organism_unit_owners: dict[str, tuple[str, str]] = {}
    for row in unit_summaries:
        if row.unit_status != "candidate":
            continue
        if not row.experimental_unit_type or not row.experimental_unit_id:
            raise ValidationError("Eligible projected unit is missing its declaration")
        owner = (
            classify_ecological_unit_level(row.experimental_unit_type)
            or row.experimental_unit_type.casefold(),
            row.experimental_unit_id,
        )
        for organism_key in row.complete_organism_keys:
            # Experimental-unit membership is an organism property, not a
            # measurement-metric property. Width and height cannot assign the
            # same organism to different tanks, even in different strata.
            previous = organism_unit_owners.setdefault(organism_key, owner)
            if previous != owner:
                raise ValidationError(
                    "One organism cannot be pooled across declared experimental units"
                )

    groups: dict[tuple[str, str, str, str], list[EcologyProjectedUnitSummary]] = {}
    seen_unit_metrics: set[tuple[str, str, str]] = set()
    for row in unit_summaries:
        if row.unit_status != "candidate":
            continue
        if (
            not row.experimental_unit_type
            or not row.experimental_unit_id
            or len(row.units) != 1
            or len(row.sampling_windows_utc) != 1
            or row.mean_absolute_change is None
            or row.mean_percent_change is None
        ):
            raise ValidationError("Incomplete projected unit cannot enter population summary")
        if (
            not row.organism_keys
            or len(row.organism_keys) != len(set(row.organism_keys))
            or len(row.complete_organism_keys) != len(set(row.complete_organism_keys))
            or len(row.incomplete_organism_keys) != len(set(row.incomplete_organism_keys))
            or set(row.complete_organism_keys) != set(row.organism_keys)
            or row.incomplete_organism_keys
        ):
            raise ValidationError("Projected unit organism coverage is inconsistent")
        if len(row.parent_colony_keys) != len(set(row.parent_colony_keys)):
            raise ValidationError("Projected unit parent-colony provenance is inconsistent")
        # A tank and an aquarium are the same biological sampling level.
        # Reusing one physical unit ID under aliases must never inflate the
        # number of independent experimental replicates.
        normalized_level = classify_ecological_unit_level(row.experimental_unit_type)
        unit_metric_key = (
            normalized_level or row.experimental_unit_type.casefold(),
            row.experimental_unit_id,
            row.metric,
        )
        if unit_metric_key in seen_unit_metrics:
            raise ValidationError("Duplicate projected experimental-unit metric")
        seen_unit_metrics.add(unit_metric_key)
        stratum_key = (
            normalized_level or row.experimental_unit_type.casefold(),
            row.metric,
            row.units[0],
            row.sampling_windows_utc[0],
        )
        groups.setdefault(stratum_key, []).append(row)

    results: list[EcologyProjectedPopulationSummary] = []
    for (unit_type, metric, unit, window), records in sorted(groups.items()):
        unit_ids = sorted(str(row.experimental_unit_id) for row in records)
        if len(set(unit_ids)) != len(records):
            raise ValidationError("Duplicate declared unit in projected population stratum")
        count = len(records)
        parent_counts: dict[str, int] = {}
        for record in records:
            for parent_key in record.parent_colony_keys:
                parent_counts[parent_key] = parent_counts.get(parent_key, 0) + 1
        # Recheck nullable unit means at the aggregation boundary. This also
        # narrows their types without trusting prior filtering or model copies.
        absolute_changes: list[float] = []
        percent_changes: list[float] = []
        for record in records:
            if record.mean_absolute_change is None or record.mean_percent_change is None:
                raise ValidationError("Incomplete projected unit cannot enter population summary")
            absolute_changes.append(record.mean_absolute_change)
            percent_changes.append(record.mean_percent_change)
        try:
            mean_absolute = math.fsum(value / count for value in absolute_changes)
            mean_percent = math.fsum(value / count for value in percent_changes)
        except OverflowError as exc:
            raise ValidationError("Projected population summary is nonfinite") from exc
        if not math.isfinite(mean_absolute) or not math.isfinite(mean_percent):
            raise ValidationError("Projected population summary is nonfinite")
        sample_sd_absolute: float | None = None
        sample_sd_percent: float | None = None
        if count >= 2:
            try:
                # hypot avoids squaring overflow for finite, large unit-level
                # changes when the sample standard deviation is itself finite.
                absolute_deviations = [value - mean_absolute for value in absolute_changes]
                percent_deviations = [value - mean_percent for value in percent_changes]
                sample_sd_absolute = math.hypot(*absolute_deviations) / math.sqrt(count - 1)
                sample_sd_percent = math.hypot(*percent_deviations) / math.sqrt(count - 1)
            except (OverflowError, ValueError) as exc:
                raise ValidationError("Projected unit dispersion is nonfinite") from exc
            if not math.isfinite(sample_sd_absolute) or not math.isfinite(sample_sd_percent):
                raise ValidationError("Projected unit dispersion is nonfinite")
        shared_parents = sorted(key for key, n in parent_counts.items() if n > 1)
        missing_parents = sorted(
            str(row.experimental_unit_id) for row in records if not row.parent_colony_keys
        )
        blockers = ["independence_not_authenticated"]
        if count < 2:
            blockers.append("single_declared_unit")
        if shared_parents:
            blockers.append("shared_parent_colonies")
        if missing_parents:
            blockers.append("missing_parent_colony")
        results.append(
            EcologyProjectedPopulationSummary(
                experimental_unit_type=unit_type,
                metric=metric,
                unit=unit,
                sampling_window_utc=window,
                experimental_unit_ids=unit_ids,
                declared_unit_count=count,
                contributing_organism_count=sum(len(row.complete_organism_keys) for row in records),
                parent_colony_keys=sorted(parent_counts),
                shared_parent_colony_keys=shared_parents,
                units_missing_parent_colony=missing_parents,
                mean_unit_absolute_change=mean_absolute,
                mean_unit_percent_change=mean_percent,
                sample_sd_unit_absolute_change=sample_sd_absolute,
                sample_sd_unit_percent_change=sample_sd_percent,
                design_review_blockers=blockers,
            )
        )
    return results


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
            # Historical image links retain their original identity revision.
            # A later correction to parentage or experimental-unit assignment
            # must not silently reattribute those measurements to the new
            # biological identity. Require explicit scientist re-review.
            if image_link.identity_revision != identity.revision:
                exclusions.append(
                    EcologyMeasurementExclusion(
                        calibration_evidence_id=calibration.id,
                        reason="identity_revision_requires_review",
                    )
                )
                continue
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
        visit_coverage = summarize_projected_visit_coverage(candidates)
        projected_changes = summarize_projected_endpoint_changes(candidates, sampling_date_qc)
        unit_summaries = summarize_projected_unit_summaries(candidates, projected_changes)
        population_summaries = summarize_projected_population_summaries(unit_summaries)
        rows = [row.model_dump(mode="json") for row in candidates]
        qc_rows = [row.model_dump(mode="json") for row in sampling_date_qc]
        coverage_rows = [row.model_dump(mode="json") for row in visit_coverage]
        change_rows = [row.model_dump(mode="json") for row in projected_changes]
        unit_rows = [row.model_dump(mode="json") for row in unit_summaries]
        population_rows = [row.model_dump(mode="json") for row in population_summaries]
        skipped = [row.model_dump(mode="json") for row in exclusions]
        fingerprint = canonical_json_sha256(
            {
                "algorithm_version": "ecology-measurement-candidates-0018",
                "project_id": project_id,
                "registry_history_sha256": snapshot.history_sha256,
                "registry_image_evidence_sha256": snapshot.image_evidence_sha256,
                "registry_annotation_evidence_sha256": snapshot.annotation_evidence_sha256,
                "registry_calibration_evidence_sha256": snapshot.calibration_evidence_sha256,
                "candidates": rows,
                "sampling_date_qc": qc_rows,
                "projected_visit_coverage": coverage_rows,
                "projected_endpoint_changes": change_rows,
                "projected_unit_summaries": unit_rows,
                "projected_population_summaries": population_rows,
                "exclusions": skipped,
            }
        )
        response = EcologyMeasurementCandidatesResponse(
            project_id=project_id,
            source_registry_history_sha256=snapshot.history_sha256,
            source_calibration_evidence_sha256=snapshot.calibration_evidence_sha256,
            source_image_evidence_sha256=snapshot.image_evidence_sha256,
            source_annotation_evidence_sha256=snapshot.annotation_evidence_sha256,
            source_fingerprint_contract="ecology-measurement-candidates-0018",
            candidates=candidates,
            candidate_count=len(candidates),
            sampling_date_qc=sampling_date_qc,
            projected_visit_coverage=visit_coverage,
            projected_endpoint_changes=projected_changes,
            projected_unit_summaries=unit_summaries,
            projected_population_summaries=population_summaries,
            exclusions=exclusions,
            input_sha256=fingerprint,
        )
        qc_counts: dict[str, int] = {}
        for audit in sampling_date_qc:
            qc_counts[audit.qc_status] = qc_counts.get(audit.qc_status, 0) + 1
        report_values = {
            "algorithm_version": "ecology-candidate-report-0001",
            "project_id": project_id,
            "source_input_sha256": fingerprint,
            "candidate_count": len(candidates),
            "source_image_count": len({row.image_id for row in candidates}),
            "source_organism_count": len({row.organism_key for row in candidates}),
            "declared_experimental_unit_count": len(
                {
                    (row.experimental_unit_type, row.experimental_unit_id)
                    for row in candidates
                    if row.experimental_unit_type and row.experimental_unit_id
                }
            ),
            "date_qc_pass_series_count": sum(
                row.qc_status == "date_series_candidate" for row in sampling_date_qc
            ),
            "excluded_series_count": sum(
                row.qc_status != "date_series_candidate" for row in sampling_date_qc
            ),
            "excluded_source_count": len(exclusions),
            "qc_status_counts": dict(sorted(qc_counts.items())),
        }
        response.candidate_report = EcologyCandidateReport.model_validate(
            {**report_values, "report_sha256": canonical_json_sha256(report_values)}
        )
        return response
