"""Transactional orchestration for anatomical measurement and event analysis."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    PoseAnimalIdentity,
    PoseBiologicalEventRevision,
    PoseEventDetectionRun,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    PoseMeasurementRun,
    PoseMeasurementSample,
    PoseMeasurementSeries,
    VideoAsset,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.pose_anatomical_measurement import (
    AnatomicalLandmark,
    AnatomicalObservation,
    MeasurementCalibration,
    calculate_measurement_series,
)
from reefvision.domain.pose_anatomical_measurement import (
    MeasurementDefinition as DomainMeasurementDefinition,
)
from reefvision.domain.pose_biological_events import (
    CycleDefinition as DomainCycleDefinition,
)
from reefvision.domain.pose_biological_events import (
    EventSignalSample,
    detect_biological_events,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_biological_measurement import (
    EventCorrectionRequest,
    EventDetectionCreateRequest,
    ManualEventCreateRequest,
    PoseMeasurementRunCreateRequest,
)
from reefvision.storage.datasets import canonical_json_sha256


class PoseBiologicalMeasurementCancelled(Exception):
    pass


def canonical_package_hash(value: Any) -> str:
    return canonical_json_sha256(value)


class PoseBiologicalMeasurementService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _measurement_run(self, run_id: str) -> PoseMeasurementRun:
        run = self.session.get(PoseMeasurementRun, run_id)
        if run is None:
            raise NotFoundError("Pose measurement run not found")
        return run

    def _event_run(self, run_id: str) -> PoseEventDetectionRun:
        run = self.session.get(PoseEventDetectionRun, run_id)
        if run is None:
            raise NotFoundError("Biological event detection run not found")
        return run

    @staticmethod
    def _calibration(
        video: VideoAsset,
    ) -> tuple[dict[str, Any] | None, str | None, MeasurementCalibration | None]:
        raw = dict(video.metadata_json or {}).get("spatial_calibration")
        if not isinstance(raw, dict):
            return None, None, None
        try:
            pixels_per_unit = float(
                raw.get("pixels_per_unit")
                or float(raw["reference_pixels"]) / float(raw["reference_distance"])
            )
            calibration = MeasurementCalibration(pixels_per_unit, str(raw["unit"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Stored video spatial calibration is invalid") from exc
        snapshot = dict(raw)
        return snapshot, canonical_package_hash(snapshot), calibration

    def submit_measurements(
        self, project_id: str, payload: PoseMeasurementRunCreateRequest
    ) -> JobResponse:
        source = self.session.get(PoseIdentityAssociationRun, payload.source_identity_run_id)
        video = self.session.get(VideoAsset, payload.video_id)
        if source is None or source.project_id != project_id:
            raise ValidationError("Identity run does not belong to the project")
        if source.status != "completed":
            raise ValidationError("Identity run must be completed")
        if source.revision != payload.source_identity_run_revision:
            raise ValidationError("Identity run revision does not match")
        if video is None or video.project_id != project_id or video.id != source.video_id:
            raise ValidationError("Video does not match the identity run")
        identities = list(
            self.session.scalars(
                select(PoseAnimalIdentity).where(PoseAnimalIdentity.association_run_id == source.id)
            )
        )
        selected = set(payload.identity_ids or [identity.id for identity in identities])
        if not selected or not selected <= {identity.id for identity in identities}:
            raise ValidationError("Selected identities do not belong to the identity run")
        if payload.verification_mode == "scientific" and any(
            identity.verification_state not in {"scientist_verified", "scientist_confirmed"}
            for identity in identities
            if identity.id in selected
        ):
            raise ValidationError("Scientific measurement requires scientist-reviewed identities")
        calibration_json, calibration_hash, _ = self._calibration(video)
        definitions = [definition.model_dump(mode="json") for definition in payload.definitions]
        manifest = {
            "identity_run_id": source.id,
            "identity_run_revision": source.revision,
            "identity_ids": sorted(selected),
            "video_id": video.id,
            "video_sha256": video.sha256,
            "video_revision": video.revision,
            "calibration_sha256": calibration_hash,
            "definitions": definitions,
            "maximum_gap_s": payload.maximum_gap_s,
            "verification_mode": payload.verification_mode,
            "schema": {
                "id": source.pose_schema_id,
                "revision": source.pose_schema_revision,
                "hash": source.pose_schema_content_hash,
            },
        }
        manifest_hash = canonical_package_hash(manifest)
        existing = self.session.scalar(
            select(PoseMeasurementRun).where(
                PoseMeasurementRun.project_id == project_id,
                PoseMeasurementRun.input_manifest_sha256 == manifest_hash,
                PoseMeasurementRun.status.in_(("queued", "running")),
            )
        )
        if existing is not None and existing.source_job_id is not None:
            active_job = self.session.get(Job, existing.source_job_id)
            if active_job is not None:
                return JobResponse.model_validate(active_job)
        run = PoseMeasurementRun(
            project_id=project_id,
            video_id=video.id,
            source_identity_run_id=source.id,
            source_identity_run_revision=source.revision,
            pose_schema_id=source.pose_schema_id,
            pose_schema_revision=source.pose_schema_revision,
            pose_schema_content_hash=source.pose_schema_content_hash,
            video_sha256=video.sha256,
            video_revision=video.revision,
            calibration_json=calibration_json,
            calibration_sha256=calibration_hash,
            timebase_json={"fps": video.fps, "source": "observation_time_or_video_fps"},
            definitions_json=definitions,
            configuration_json={
                "identity_ids": sorted(selected),
                "maximum_gap_s": payload.maximum_gap_s,
            },
            input_manifest_json=manifest,
            input_manifest_sha256=manifest_hash,
            status="queued",
            progress_json={
                "stage": "queued",
                "current": 0,
                "total": len(selected) * len(definitions),
            },
            provenance_json={"engine": "reefpose.measurement.v1"},
            verification_state=payload.verification_mode,
        )
        self.session.add(run)
        self.session.flush()
        job = Job(
            project_id=project_id,
            job_type="pose_biological_measurement",
            status="queued",
            progress_total=max(1, len(selected) * len(definitions)),
            request_json={"run_id": run.id, "input_manifest_sha256": run.input_manifest_sha256},
            result_json={"run_id": run.id, "stage": "queued"},
        )
        self.session.add(job)
        self.session.flush()
        run.source_job_id = job.id
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def _validate_manifest(
        self, run: PoseMeasurementRun
    ) -> tuple[PoseIdentityAssociationRun, VideoAsset]:
        source = self.session.get(PoseIdentityAssociationRun, run.source_identity_run_id)
        video = self.session.get(VideoAsset, run.video_id)
        if source is None or video is None:
            raise ValidationError("Measurement source no longer exists")
        _, calibration_hash, _ = self._calibration(video)
        if (
            source.revision != run.source_identity_run_revision
            or video.revision != run.video_revision
            or video.sha256 != run.video_sha256
            or calibration_hash != run.calibration_sha256
        ):
            raise ValidationError("Measurement source provenance is stale")
        return source, video

    def execute_measurements(
        self,
        run_id: str,
        *,
        cancellation_check: Callable[[], None] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> PoseMeasurementRun:
        run = self._measurement_run(run_id)
        _source, video = self._validate_manifest(run)
        identity_ids = list(run.configuration_json.get("identity_ids") or [])
        observations = list(
            self.session.scalars(
                select(PoseIdentityObservation)
                .where(
                    PoseIdentityObservation.association_run_id == run.source_identity_run_id,
                    PoseIdentityObservation.animal_identity_id.in_(identity_ids),
                    PoseIdentityObservation.is_current.is_(True),
                )
                .order_by(PoseIdentityObservation.frame_index)
            )
        )
        calibration = (
            MeasurementCalibration(
                float(
                    run.calibration_json.get("pixels_per_unit")
                    or float(run.calibration_json["reference_pixels"])
                    / float(run.calibration_json["reference_distance"])
                ),
                str(run.calibration_json["unit"]),
            )
            if run.calibration_json
            else None
        )
        domain = [
            AnatomicalObservation(
                o.id,
                o.revision,
                str(o.animal_identity_id),
                o.frame_index,
                float(o.time_s if o.time_s is not None else o.frame_index / video.fps),
                o.coordinate_space,
                o.association_confidence,
                tuple(
                    AnatomicalLandmark(
                        str(p.get("landmark_id") or p.get("id")),
                        p.get("x"),
                        p.get("y"),
                        p.get("confidence"),
                        str(p.get("visibility") or p.get("status") or "visible"),
                    )
                    for p in o.landmarks_json
                ),
            )
            for o in observations
        ]
        outputs: list[tuple[str, dict[str, Any], Any]] = []
        total = len(identity_ids) * len(run.definitions_json)
        current = 0
        for identity_id in identity_ids:
            for raw in run.definitions_json:
                if cancellation_check:
                    cancellation_check()
                definition = DomainMeasurementDefinition(
                    str(raw["id"]),
                    str(raw["kind"]),
                    tuple(raw["landmark_ids"]),
                    dict(raw.get("options") or {}),
                )
                result = calculate_measurement_series(
                    domain,
                    definition,
                    calibration,
                    identity_id=identity_id,
                    maximum_gap_s=float(run.configuration_json.get("maximum_gap_s", 0.25)),
                )
                outputs.append((identity_id, raw, result))
                current += 1
                if progress:
                    progress(current, total)
        for identity_id, raw, result in outputs:
            series = PoseMeasurementSeries(
                measurement_run_id=run.id,
                animal_identity_id=identity_id,
                definition_id=result.definition_id,
                measurement_kind=result.measurement_kind,
                display_name=str(raw.get("name") or result.definition_id),
                landmark_ids_json=list(raw["landmark_ids"]),
                formula_version=result.formula_version,
                unit_dimension="angle" if result.pixel_unit == "degrees" else "length",
                pixel_unit=result.pixel_unit,
                physical_unit=result.physical_unit,
                summary_json=result.summary,
                series_sha256=result.result_sha256,
            )
            self.session.add(series)
            self.session.flush()
            self.session.add_all(
                [
                    PoseMeasurementSample(
                        series_id=series.id,
                        frame_index=s.frame_index,
                        time_s=s.time_s,
                        pixel_value=s.pixel_value,
                        physical_value=s.physical_value,
                        value_json={},
                        confidence=s.confidence,
                        valid=s.valid,
                        quality_flags_json=list(s.quality_flags),
                        source_observation_ids_json=list(s.source_observation_ids),
                        source_observation_revisions_json=list(s.source_observation_revisions),
                    )
                    for s in result.samples
                ]
            )
        run.status = "completed"
        run.progress_json = {"stage": "completed", "current": total, "total": total}
        run.completed_at = datetime.now(UTC)
        run.result_sha256 = canonical_package_hash([output[2].result_sha256 for output in outputs])
        self.session.commit()
        self.session.refresh(run)
        return run

    def submit_events(self, project_id: str, payload: EventDetectionCreateRequest) -> JobResponse:
        measurement = self._measurement_run(payload.measurement_run_id)
        if measurement.project_id != project_id or measurement.status != "completed":
            raise ValidationError("Measurement run is not completed for this project")
        configuration = {"cycles": [cycle.model_dump(mode="json") for cycle in payload.cycles]}
        configuration_hash = canonical_package_hash(configuration)
        existing = self.session.scalar(
            select(PoseEventDetectionRun).where(
                PoseEventDetectionRun.measurement_run_id == measurement.id,
                PoseEventDetectionRun.configuration_sha256 == configuration_hash,
                PoseEventDetectionRun.status.in_(("queued", "running")),
            )
        )
        if existing is not None and existing.source_job_id is not None:
            active_job = self.session.get(Job, existing.source_job_id)
            if active_job is not None:
                return JobResponse.model_validate(active_job)
        run = PoseEventDetectionRun(
            measurement_run_id=measurement.id,
            configuration_json=configuration,
            configuration_sha256=configuration_hash,
            status="queued",
            progress_json={"stage": "queued", "current": 0, "total": len(payload.cycles)},
            provenance_json={
                "measurement_result_sha256": measurement.result_sha256,
                "engine": "reefpose.events.v1",
            },
        )
        self.session.add(run)
        self.session.flush()
        job = Job(
            project_id=project_id,
            job_type="pose_biological_event_detection",
            status="queued",
            progress_total=len(payload.cycles),
            request_json={"run_id": run.id},
            result_json={"run_id": run.id, "stage": "queued"},
        )
        self.session.add(job)
        self.session.flush()
        run.source_job_id = job.id
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def execute_events(
        self,
        run_id: str,
        *,
        cancellation_check: Callable[[], None] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> PoseEventDetectionRun:
        run = self._event_run(run_id)
        measurement = self._measurement_run(run.measurement_run_id)
        self._validate_manifest(measurement)
        hashes = []
        for index, raw in enumerate(run.configuration_json["cycles"], 1):
            if cancellation_check:
                cancellation_check()
            series = self.session.get(PoseMeasurementSeries, str(raw["measurement_series_id"]))
            if series is None or series.measurement_run_id != measurement.id:
                raise ValidationError(
                    "Cycle definition references an incompatible measurement series"
                )
            rows = list(
                self.session.scalars(
                    select(PoseMeasurementSample)
                    .where(PoseMeasurementSample.series_id == series.id)
                    .order_by(PoseMeasurementSample.time_s)
                )
            )
            domain = [
                EventSignalSample(
                    s.frame_index,
                    s.time_s,
                    s.physical_value if s.physical_value is not None else s.pixel_value,
                    s.confidence,
                    s.valid,
                    series.animal_identity_id,
                )
                for s in rows
            ]
            config = {k: v for k, v in raw.items() if k != "measurement_series_id"}
            result = detect_biological_events(domain, DomainCycleDefinition(**config))
            hashes.append(result.result_sha256)
            for candidate in result.events:
                event_id = str(uuid4())
                payload = asdict(candidate)
                self.session.add(
                    PoseBiologicalEventRevision(
                        id=event_id,
                        event_series_id=event_id,
                        revision=1,
                        event_detection_run_id=run.id,
                        measurement_series_id=series.id,
                        animal_identity_id=series.animal_identity_id,
                        start_frame=candidate.start_frame,
                        peak_frame=candidate.peak_frame,
                        end_frame=candidate.end_frame,
                        start_time_s=candidate.start_time_s,
                        peak_time_s=candidate.peak_time_s,
                        end_time_s=candidate.end_time_s,
                        baseline_value=candidate.baseline_value,
                        peak_value=candidate.peak_value,
                        amplitude=candidate.amplitude,
                        duration_s=candidate.duration_s,
                        confidence=candidate.confidence,
                        cycle_state=candidate.cycle_state,
                        detection_source="automated",
                        review_state="unreviewed",
                        rejection_reasons_json=list(candidate.rejection_reasons),
                        actor="system",
                        after_sha256=canonical_package_hash(payload),
                        is_current=True,
                    )
                )
            if progress:
                progress(index, len(run.configuration_json["cycles"]))
        run.status = "completed"
        run.progress_json = {"stage": "completed", "current": len(hashes), "total": len(hashes)}
        run.result_sha256 = canonical_package_hash(hashes)
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(run)
        return run

    def correct_event(
        self, event_id: str, payload: EventCorrectionRequest
    ) -> PoseBiologicalEventRevision:
        current = self.session.scalar(
            select(PoseBiologicalEventRevision).where(
                PoseBiologicalEventRevision.id == event_id,
                PoseBiologicalEventRevision.is_current.is_(True),
            )
        )
        if current is None:
            raise NotFoundError("Current biological event not found")
        start = (
            payload.start_frame
            if payload.action == "adjust_boundaries" and payload.start_frame is not None
            else current.start_frame
        )
        end = (
            payload.end_frame
            if payload.action == "adjust_boundaries" and payload.end_frame is not None
            else current.end_frame
        )
        if end is not None and end < start:
            raise ValidationError("Event end must not precede start")
        samples = list(
            self.session.scalars(
                select(PoseMeasurementSample)
                .where(
                    PoseMeasurementSample.series_id == current.measurement_series_id,
                    PoseMeasurementSample.frame_index >= start,
                    PoseMeasurementSample.frame_index <= end
                    if end is not None
                    else PoseMeasurementSample.frame_index >= start,
                )
                .order_by(PoseMeasurementSample.frame_index)
            )
        )
        valid = [
            s
            for s in samples
            if s.valid and (s.physical_value is not None or s.pixel_value is not None)
        ]
        if not valid:
            raise ValidationError("Corrected event contains no valid measurement samples")

        def value(sample: PoseMeasurementSample) -> float:
            raw = sample.physical_value if sample.physical_value is not None else sample.pixel_value
            assert raw is not None
            return float(raw)

        peak = max(valid, key=lambda s: (value(s), -s.frame_index))
        baseline = value(valid[0])
        before = {
            c.name: getattr(current, c.name)
            for c in current.__table__.columns
            if c.name not in {"created_at"}
        }
        current.is_current = False
        state = {"confirm": "confirmed", "reject": "rejected", "remove": "removed"}.get(
            payload.action, current.review_state
        )
        revised = PoseBiologicalEventRevision(
            event_series_id=current.event_series_id,
            revision=current.revision + 1,
            supersedes_event_id=current.id,
            event_detection_run_id=current.event_detection_run_id,
            measurement_series_id=current.measurement_series_id,
            animal_identity_id=current.animal_identity_id,
            start_frame=start,
            peak_frame=peak.frame_index,
            end_frame=end,
            start_time_s=valid[0].time_s,
            peak_time_s=peak.time_s,
            end_time_s=valid[-1].time_s if end is not None else None,
            baseline_value=baseline,
            peak_value=value(peak),
            amplitude=value(peak) - baseline,
            duration_s=valid[-1].time_s - valid[0].time_s if end is not None else None,
            confidence=min((s.confidence for s in valid if s.confidence is not None), default=None),
            cycle_state=current.cycle_state,
            detection_source="scientist",
            review_state=state,
            rejection_reasons_json=current.rejection_reasons_json,
            reason=payload.reason,
            actor=payload.actor,
            before_sha256=canonical_package_hash(before),
            after_sha256="pending",
            is_current=True,
        )
        self.session.add(revised)
        self.session.flush()
        revised.after_sha256 = canonical_package_hash(
            {
                c.name: getattr(revised, c.name)
                for c in revised.__table__.columns
                if c.name not in {"created_at", "after_sha256"}
            }
        )
        self.session.commit()
        self.session.refresh(revised)
        return revised

    def add_manual_event(
        self, event_run_id: str, payload: ManualEventCreateRequest
    ) -> PoseBiologicalEventRevision:
        run = self._event_run(event_run_id)
        series = self.session.get(PoseMeasurementSeries, payload.measurement_series_id)
        if series is None or series.measurement_run_id != run.measurement_run_id:
            raise ValidationError("Manual event references an incompatible measurement series")
        samples = list(
            self.session.scalars(
                select(PoseMeasurementSample)
                .where(
                    PoseMeasurementSample.series_id == series.id,
                    PoseMeasurementSample.frame_index >= payload.start_frame,
                    PoseMeasurementSample.frame_index <= payload.end_frame,
                    PoseMeasurementSample.valid.is_(True),
                )
                .order_by(PoseMeasurementSample.frame_index)
            )
        )
        valid = [
            sample
            for sample in samples
            if sample.physical_value is not None or sample.pixel_value is not None
        ]
        if not valid:
            raise ValidationError("Manual event contains no valid measurement samples")

        def value(sample: PoseMeasurementSample) -> float:
            raw = sample.physical_value if sample.physical_value is not None else sample.pixel_value
            assert raw is not None
            return float(raw)

        peak = max(valid, key=lambda sample: (value(sample), -sample.frame_index))
        baseline = value(valid[0])
        event_series_id = str(uuid4())
        event = PoseBiologicalEventRevision(
            event_series_id=event_series_id,
            revision=1,
            event_detection_run_id=run.id,
            measurement_series_id=series.id,
            animal_identity_id=series.animal_identity_id,
            start_frame=payload.start_frame,
            peak_frame=peak.frame_index,
            end_frame=payload.end_frame,
            start_time_s=valid[0].time_s,
            peak_time_s=peak.time_s,
            end_time_s=valid[-1].time_s,
            baseline_value=baseline,
            peak_value=value(peak),
            amplitude=value(peak) - baseline,
            duration_s=valid[-1].time_s - valid[0].time_s,
            confidence=min(
                (sample.confidence for sample in valid if sample.confidence is not None),
                default=None,
            ),
            cycle_state=payload.cycle_state,
            detection_source="scientist",
            review_state="confirmed" if payload.cycle_state == "complete" else "unreviewed",
            rejection_reasons_json=[],
            reason=payload.reason,
            actor=payload.actor,
            after_sha256="pending",
            is_current=True,
        )
        self.session.add(event)
        self.session.flush()
        event.after_sha256 = canonical_package_hash(
            {
                column.name: getattr(event, column.name)
                for column in event.__table__.columns
                if column.name not in {"created_at", "after_sha256"}
            }
        )
        self.session.commit()
        self.session.refresh(event)
        return event

    def measurement_runs(self, project_id: str) -> list[PoseMeasurementRun]:
        return list(
            self.session.scalars(
                select(PoseMeasurementRun)
                .where(PoseMeasurementRun.project_id == project_id)
                .order_by(PoseMeasurementRun.created_at.desc())
            )
        )

    def series(self, run_id: str) -> list[PoseMeasurementSeries]:
        self._measurement_run(run_id)
        return list(
            self.session.scalars(
                select(PoseMeasurementSeries).where(
                    PoseMeasurementSeries.measurement_run_id == run_id
                )
            )
        )

    def samples(self, series_id: str) -> list[PoseMeasurementSample]:
        return list(
            self.session.scalars(
                select(PoseMeasurementSample)
                .where(PoseMeasurementSample.series_id == series_id)
                .order_by(PoseMeasurementSample.frame_index)
            )
        )

    def events(
        self, run_id: str, include_history: bool = False
    ) -> list[PoseBiologicalEventRevision]:
        self._event_run(run_id)
        query = select(PoseBiologicalEventRevision).where(
            PoseBiologicalEventRevision.event_detection_run_id == run_id
        )
        query = (
            query
            if include_history
            else query.where(PoseBiologicalEventRevision.is_current.is_(True))
        )
        return list(
            self.session.scalars(
                query.order_by(
                    PoseBiologicalEventRevision.start_frame, PoseBiologicalEventRevision.revision
                )
            )
        )

    def export_json(self, event_run_id: str, *, reviewed_only: bool = True) -> dict[str, Any]:
        run = self._event_run(event_run_id)
        measurement = self._measurement_run(run.measurement_run_id)
        self._validate_manifest(measurement)
        events = self.events(run.id)
        history = self.events(run.id, include_history=True)
        if reviewed_only and any(e.review_state == "unreviewed" for e in events):
            raise ValidationError(
                "Reviewed export requires disposition of every retained event candidate"
            )
        exported = [
            e
            for e in events
            if not reviewed_only or (e.review_state == "confirmed" and e.cycle_state == "complete")
        ]
        payload = {
            "schema_version": "reefpose-biological-movement-export-1",
            "scientific_status": "scientist_reviewed"
            if reviewed_only
            else "exploratory_unreviewed",
            "measurement_run": {
                "id": measurement.id,
                "source_identity_run_id": measurement.source_identity_run_id,
                "source_identity_run_revision": measurement.source_identity_run_revision,
                "result_sha256": measurement.result_sha256,
                "input_manifest_sha256": measurement.input_manifest_sha256,
            },
            "event_run": {
                "id": run.id,
                "configuration_sha256": run.configuration_sha256,
                "result_sha256": run.result_sha256,
            },
            "events": [
                {
                    "event_series_id": e.event_series_id,
                    "revision": e.revision,
                    "identity_id": e.animal_identity_id,
                    "start_frame": e.start_frame,
                    "peak_frame": e.peak_frame,
                    "end_frame": e.end_frame,
                    "amplitude": e.amplitude,
                    "duration_s": e.duration_s,
                    "confidence": e.confidence,
                    "cycle_state": e.cycle_state,
                    "review_state": e.review_state,
                }
                for e in exported
            ],
            "event_history": [
                {
                    "id": event.id,
                    "event_series_id": event.event_series_id,
                    "revision": event.revision,
                    "supersedes_event_id": event.supersedes_event_id,
                    "identity_id": event.animal_identity_id,
                    "measurement_series_id": event.measurement_series_id,
                    "start_frame": event.start_frame,
                    "peak_frame": event.peak_frame,
                    "end_frame": event.end_frame,
                    "amplitude": event.amplitude,
                    "duration_s": event.duration_s,
                    "confidence": event.confidence,
                    "cycle_state": event.cycle_state,
                    "review_state": event.review_state,
                    "detection_source": event.detection_source,
                    "actor": event.actor,
                    "reason": event.reason,
                    "is_current": event.is_current,
                    "before_sha256": event.before_sha256,
                    "after_sha256": event.after_sha256,
                }
                for event in history
            ],
            "measurement_series": [
                {
                    "id": series.id,
                    "identity_id": series.animal_identity_id,
                    "definition_id": series.definition_id,
                    "measurement_kind": series.measurement_kind,
                    "landmark_ids": series.landmark_ids_json,
                    "pixel_unit": series.pixel_unit,
                    "physical_unit": series.physical_unit,
                    "summary": series.summary_json,
                    "series_sha256": series.series_sha256,
                    "samples": [
                        {
                            "frame_index": sample.frame_index,
                            "time_s": sample.time_s,
                            "pixel_value": sample.pixel_value,
                            "physical_value": sample.physical_value,
                            "confidence": sample.confidence,
                            "valid": sample.valid,
                            "quality_flags": sample.quality_flags_json,
                        }
                        for sample in self.samples(series.id)
                    ],
                }
                for series in self.series(measurement.id)
            ],
        }
        payload["package_sha256"] = canonical_package_hash(payload)
        return payload

    def export_csv(self, event_run_id: str, *, reviewed_only: bool = True) -> str:
        package = self.export_json(event_run_id, reviewed_only=reviewed_only)
        output = io.StringIO(newline="")
        columns = [
            "record_type",
            "series_id",
            "event_series_id",
            "revision",
            "identity_id",
            "frame_index",
            "time_s",
            "pixel_value",
            "physical_value",
            "start_frame",
            "peak_frame",
            "end_frame",
            "amplitude",
            "duration_s",
            "confidence",
            "cycle_state",
            "review_state",
            "quality_flags",
        ]
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for series in package["measurement_series"]:
            for sample in series["samples"]:
                writer.writerow(
                    {
                        "record_type": "measurement",
                        "series_id": series["id"],
                        "identity_id": series["identity_id"],
                        "frame_index": sample["frame_index"],
                        "time_s": sample["time_s"],
                        "pixel_value": sample["pixel_value"],
                        "physical_value": sample["physical_value"],
                        "confidence": sample["confidence"],
                        "quality_flags": "|".join(sample["quality_flags"]),
                    }
                )
        for event in package["event_history"]:
            writer.writerow(
                {
                    "record_type": "event_revision",
                    "series_id": event["measurement_series_id"],
                    "event_series_id": event["event_series_id"],
                    "revision": event["revision"],
                    "identity_id": event["identity_id"],
                    "start_frame": event["start_frame"],
                    "peak_frame": event["peak_frame"],
                    "end_frame": event["end_frame"],
                    "amplitude": event["amplitude"],
                    "duration_s": event["duration_s"],
                    "confidence": event["confidence"],
                    "cycle_state": event["cycle_state"],
                    "review_state": event["review_state"],
                }
            )
        return output.getvalue()
