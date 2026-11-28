"""Confirm and monitor scoped links without rewriting ReefPose or organism history."""

from __future__ import annotations

from datetime import UTC
from typing import Literal, cast
from uuid import uuid4

from pydantic import ValidationError as SchemaError
from sqlalchemy import Select, Subquery, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.db.models.ecology_pose_link_revision import EcologyPoseLinkRevision
from reefvision.db.models.pose_biological_measurement import (
    PoseBiologicalEventRevision,
    PoseEventDetectionRun,
    PoseMeasurementRun,
    PoseMeasurementSample,
    PoseMeasurementSeries,
)
from reefvision.db.models.pose_identity_tracking import (
    PoseAnimalIdentity,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
)
from reefvision.db.models.project import Project
from reefvision.db.models.video_asset import VideoAsset
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.ecology_pose_links import (
    LinkedPoseEvent,
    LinkedPoseMeasurement,
    LinkedPoseObservation,
    LinkState,
    PoseLinkCorrection,
    PoseLinkCreate,
    PoseLinkList,
    PoseLinkResponse,
    PoseLinkSource,
    PoseLinkUnlink,
)
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.services.pose_biological_measurement import PoseBiologicalMeasurementService
from reefvision.storage.datasets import canonical_json_sha256

_REVIEWED = {"scientist_confirmed", "scientist_verified"}


class EcologyPoseLinkService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _lock_project(self, project_id: str) -> None:
        # Acquire the SQLite write lock before testing interval conflicts. Keep
        # the project's audit timestamp unchanged and serialize other writers.
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        self.session.execute(
            update(Project).where(Project.id == project_id).values(updated_at=Project.updated_at)
        )

    def _organism(self, project_id: str, organism_revision_id: str) -> EcologyIdentityRevision:
        row = self.session.get(EcologyIdentityRevision, organism_revision_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Organism revision does not belong to this project")
        latest = EcologyIdentityService(self.session)._latest(project_id).get(row.organism_key)
        if latest is None or latest.id != row.id:
            raise ConflictError("Organism registration revision changed")
        return row

    def _history(self, project_id: str, link_id: str) -> list[EcologyPoseLinkRevision]:
        rows = list(
            self.session.scalars(
                select(EcologyPoseLinkRevision)
                .where(
                    EcologyPoseLinkRevision.project_id == project_id,
                    EcologyPoseLinkRevision.link_id == link_id,
                )
                .order_by(EcologyPoseLinkRevision.revision)
            )
        )
        if not rows:
            raise NotFoundError("Reviewed pose link does not belong to this project")
        previous = None
        for revision, row in enumerate(rows, start=1):
            if (
                row.revision != revision
                or row.supersedes_id != previous
                or (row.action == "link") != (revision == 1)
                or (row.action == "unlink" and revision != len(rows))
            ):
                raise ValidationError("Reviewed pose link history is not contiguous")
            previous = row.id
        return rows

    def _validated_source(self, row: EcologyPoseLinkRevision) -> PoseLinkSource:
        if canonical_json_sha256(row.source_json) != row.source_sha256:
            raise ValidationError("Reviewed pose link evidence failed its checksum")
        try:
            source = PoseLinkSource.model_validate(row.source_json)
        except SchemaError as exc:
            raise ValidationError("Reviewed pose link evidence has an invalid schema") from exc
        if any(
            not row.frame_start <= item.frame_index <= row.frame_end for item in source.observations
        ):
            raise ValidationError("Reviewed pose link observations exceed its recorded scope")
        return source

    def _run_source(
        self, project_id: str, run_id: str, identity_id: str
    ) -> tuple[PoseIdentityAssociationRun, PoseAnimalIdentity, VideoAsset]:
        run = self.session.get(PoseIdentityAssociationRun, run_id)
        identity = self.session.get(PoseAnimalIdentity, identity_id)
        if (
            run is None
            or run.project_id != project_id
            or identity is None
            or identity.association_run_id != run_id
        ):
            raise NotFoundError("Pose identity does not belong to this project's identity run")
        video = self.session.get(VideoAsset, run.video_id)
        if video is None or video.project_id != project_id:
            raise NotFoundError("Source recording does not belong to this project")
        if run.status != "completed" or identity.lifecycle_state != "active":
            raise ValidationError("Links require an active identity in a completed association run")
        if run.source_coordinate_space != "source_pixels":
            raise ValidationError("Links require canonical source-pixel pose evidence")
        return run, identity, video

    def _observations(
        self,
        run: PoseIdentityAssociationRun,
        identity: PoseAnimalIdentity,
        frame_start: int,
        frame_end: int,
    ) -> list[LinkedPoseObservation]:
        rows = list(
            self.session.scalars(
                select(PoseIdentityObservation)
                .where(
                    PoseIdentityObservation.association_run_id == run.id,
                    PoseIdentityObservation.animal_identity_id == identity.id,
                    PoseIdentityObservation.frame_index.between(frame_start, frame_end),
                    PoseIdentityObservation.is_current.is_(True),
                )
                .order_by(PoseIdentityObservation.frame_index, PoseIdentityObservation.id)
            )
        )
        if not rows or any(row.verification_state not in _REVIEWED for row in rows):
            raise ValidationError("The selected span requires scientist-reviewed pose observations")
        if len({row.frame_index for row in rows}) != len(rows) or any(
            row.coordinate_space != "source_pixels" for row in rows
        ):
            raise ValidationError(
                "The selected span contains ambiguous or incompatible observations"
            )
        return [
            LinkedPoseObservation(
                id=row.id,
                observation_series_id=row.observation_series_id,
                revision=row.revision,
                frame_index=row.frame_index,
                source_video_track_id=row.source_video_track_id,
                verification_state=cast(
                    Literal["scientist_confirmed", "scientist_verified"], row.verification_state
                ),
            )
            for row in rows
        ]

    def _measurement(
        self,
        series_id: str,
        run: PoseIdentityAssociationRun,
        identity: PoseAnimalIdentity,
        frame_start: int,
        frame_end: int,
    ) -> LinkedPoseMeasurement:
        series = self.session.get(PoseMeasurementSeries, series_id)
        if series is None or series.animal_identity_id != identity.id:
            raise ValidationError("Measurement series does not belong to the linked identity")
        measurement = self.session.get(PoseMeasurementRun, series.measurement_run_id)
        if (
            measurement is None
            or measurement.project_id != run.project_id
            or measurement.video_id != run.video_id
            or measurement.source_identity_run_id != run.id
            or measurement.pose_schema_id != run.pose_schema_id
            or measurement.pose_schema_revision != run.pose_schema_revision
            or measurement.pose_schema_content_hash != run.pose_schema_content_hash
            or measurement.status != "completed"
            or measurement.verification_state != "scientific"
            or not measurement.result_sha256
        ):
            raise ValidationError(
                "A completed scientific measurement with compatible anatomy is required"
            )
        PoseBiologicalMeasurementService(self.session)._validate_manifest(measurement)
        sample_id = self.session.scalar(
            select(PoseMeasurementSample.id)
            .where(
                PoseMeasurementSample.series_id == series_id,
                PoseMeasurementSample.frame_index.between(frame_start, frame_end),
                PoseMeasurementSample.valid.is_(True),
            )
            .limit(1)
        )
        if sample_id is None:
            raise ValidationError("Measurement series has no valid sample in the linked span")
        return LinkedPoseMeasurement(
            id=series.id,
            run_id=measurement.id,
            definition_id=series.definition_id,
            name=series.display_name,
            series_sha256=series.series_sha256,
            result_sha256=measurement.result_sha256,
        )

    def _event(
        self,
        event_id: str,
        run: PoseIdentityAssociationRun,
        identity: PoseAnimalIdentity,
        frame_start: int,
        frame_end: int,
    ) -> tuple[LinkedPoseEvent, LinkedPoseMeasurement]:
        event = self.session.get(PoseBiologicalEventRevision, event_id)
        if (
            event is None
            or event.animal_identity_id != identity.id
            or not event.is_current
            or event.review_state != "confirmed"
        ):
            raise ValidationError("Only current, scientist-confirmed event revisions may be linked")
        if (
            event.end_frame is None
            or not frame_start <= event.start_frame <= event.end_frame <= frame_end
        ):
            raise ValidationError("The full confirmed event must be within the linked span")
        event_run = self.session.get(PoseEventDetectionRun, event.event_detection_run_id)
        measurement = self._measurement(
            event.measurement_series_id, run, identity, frame_start, frame_end
        )
        if event_run is None or event_run.measurement_run_id != measurement.run_id:
            raise ValidationError("Event provenance does not match its measurement series")
        PoseBiologicalMeasurementService(self.session)._validate_event_source(event_run)
        return (
            LinkedPoseEvent(
                id=event.id,
                event_series_id=event.event_series_id,
                run_id=event_run.id,
                measurement_series_id=event.measurement_series_id,
                revision=event.revision,
                start_frame=event.start_frame,
                end_frame=event.end_frame,
                after_sha256=event.after_sha256,
            ),
            measurement,
        )

    def _capture(
        self,
        run: PoseIdentityAssociationRun,
        identity: PoseAnimalIdentity,
        video: VideoAsset,
        frame_start: int,
        frame_end: int,
        measurement_ids: list[str],
        event_ids: list[str],
    ) -> PoseLinkSource:
        if frame_end >= video.frame_count:
            raise ValidationError("The linked span exceeds the source video frame count")
        observations = self._observations(run, identity, frame_start, frame_end)
        measurements = {
            series_id: self._measurement(series_id, run, identity, frame_start, frame_end)
            for series_id in measurement_ids
        }
        events = []
        for event_id in sorted(event_ids):
            event, measurement = self._event(event_id, run, identity, frame_start, frame_end)
            events.append(event)
            measurements[measurement.id] = measurement
        return PoseLinkSource(
            video_id=video.id,
            video_sha256=video.sha256,
            video_revision=video.revision,
            pose_schema_id=run.pose_schema_id,
            pose_schema_revision=run.pose_schema_revision,
            pose_schema_sha256=run.pose_schema_content_hash,
            identity_run_revision=run.revision,
            input_manifest_sha256=run.input_manifest_sha256,
            observations=observations,
            measurements=sorted(measurements.values(), key=lambda item: item.id),
            events=events,
        )

    def _latest_revisions(self, project_id: str) -> Subquery:
        model = EcologyPoseLinkRevision
        return (
            select(model.link_id, func.max(model.revision).label("revision"))
            .where(model.project_id == project_id)
            .group_by(model.link_id)
            .subquery()
        )

    def _current_statement(self, project_id: str) -> Select[EcologyPoseLinkRevision]:
        model = EcologyPoseLinkRevision
        latest = self._latest_revisions(project_id)
        return select(model).join(
            latest, (model.link_id == latest.c.link_id) & (model.revision == latest.c.revision)
        )

    def _assert_scope_available(
        self,
        organism: EcologyIdentityRevision,
        run: PoseIdentityAssociationRun,
        animal_id: str,
        payload: PoseLinkCreate,
        source: PoseLinkSource,
        excluded_link_id: str,
    ) -> None:
        model = EcologyPoseLinkRevision
        overlaps = self.session.scalars(
            self._current_statement(organism.project_id)
            .join(
                PoseIdentityAssociationRun,
                PoseIdentityAssociationRun.id == model.association_run_id,
            )
            .where(
                PoseIdentityAssociationRun.video_id == run.video_id,
                model.link_id != excluded_link_id,
                model.action != "unlink",
                model.frame_start <= payload.frame_end,
                model.frame_end >= payload.frame_start,
            )
        )
        assignments = {(row.source_video_track_id, row.frame_index) for row in source.observations}
        for other in overlaps:
            other_organism = self.session.get(EcologyIdentityRevision, other.organism_revision_id)
            other_source = self._validated_source(other)
            if (
                other.animal_identity_id == animal_id
                or (
                    other_organism is not None
                    and other_organism.organism_key == organism.organism_key
                )
                or any(
                    (row.source_video_track_id, row.frame_index) in assignments
                    for row in other_source.observations
                )
            ):
                raise ConflictError(
                    "An overlapping reviewed link already assigns this pose or organism"
                )

    def _stale_reason(self, row: EcologyPoseLinkRevision, recorded: PoseLinkSource) -> str | None:
        try:
            run, identity, video = self._run_source(
                row.project_id, row.association_run_id, row.animal_identity_id
            )
            expected = self._capture(
                run,
                identity,
                video,
                row.frame_start,
                row.frame_end,
                [item.id for item in recorded.measurements],
                [item.id for item in recorded.events],
            )
        except (ValidationError, NotFoundError, SchemaError) as exc:
            return str(exc)
        # A correction on another animal or outside the scope does not make
        # the frozen observations stale. Explicitly linked measurements keep
        # their existing run-level verification policy.
        if (
            expected.model_copy(update={"identity_run_revision": recorded.identity_run_revision})
            != recorded
        ):
            return "The video, anatomy, or scoped ReefPose evidence changed"
        return None

    def _response(
        self, row: EcologyPoseLinkRevision, *, superseded: bool = False
    ) -> PoseLinkResponse:
        source = self._validated_source(row)
        organism = self.session.get(EcologyIdentityRevision, row.organism_revision_id)
        if organism is None or organism.project_id != row.project_id:
            raise ValidationError("Reviewed pose link references an invalid organism revision")
        stale_reason = None
        state: LinkState
        if superseded:
            state = "superseded"
        elif row.action == "unlink":
            state = "unlinked"
        else:
            stale_reason = self._stale_reason(row, source)
            state = "stale" if stale_reason else "current"
        return PoseLinkResponse.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "link_id": row.link_id,
                "revision": row.revision,
                "action": row.action,
                "status": state,
                "stale_reason": stale_reason,
                "supersedes_id": row.supersedes_id,
                "organism_revision_id": row.organism_revision_id,
                "organism_key": organism.organism_key,
                "association_run_id": row.association_run_id,
                "animal_identity_id": row.animal_identity_id,
                "frame_start": row.frame_start,
                "frame_end": row.frame_end,
                "source": source,
                "source_sha256": row.source_sha256,
                "reviewer": row.reviewer,
                "reason": row.reason,
                "created_at": row.created_at.astimezone(UTC)
                if row.created_at.tzinfo
                else row.created_at.replace(tzinfo=UTC),
            }
        )

    def _persist(self, row: EcologyPoseLinkRevision) -> PoseLinkResponse:
        self.session.add(row)
        try:
            self.session.flush()
            response = self._response(row)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Pose link changed during review") from exc
        return response

    def _append(
        self,
        project_id: str,
        payload: PoseLinkCreate,
        previous: EcologyPoseLinkRevision | None,
    ) -> PoseLinkResponse:
        organism = self._organism(project_id, str(payload.organism_revision_id))
        run, identity, video = self._run_source(
            project_id, str(payload.association_run_id), str(payload.animal_identity_id)
        )
        if run.revision != payload.expected_identity_run_revision:
            raise ConflictError("Identity run revision changed during review")
        if (
            payload.expected_pose_schema_sha256 is not None
            and run.pose_schema_content_hash != payload.expected_pose_schema_sha256
        ):
            raise ConflictError("Pose anatomy schema changed during review")
        source = self._capture(
            run,
            identity,
            video,
            payload.frame_start,
            payload.frame_end,
            [str(item) for item in payload.measurement_series_ids],
            [str(item) for item in payload.event_revision_ids],
        )
        link_id = previous.link_id if previous is not None else str(uuid4())
        self._assert_scope_available(organism, run, identity.id, payload, source, link_id)
        snapshot = source.model_dump(mode="json")
        return self._persist(
            EcologyPoseLinkRevision(
                project_id=project_id,
                link_id=link_id,
                revision=previous.revision + 1 if previous is not None else 1,
                action="correct" if previous is not None else "link",
                supersedes_id=previous.id if previous is not None else None,
                organism_revision_id=organism.id,
                association_run_id=run.id,
                animal_identity_id=identity.id,
                frame_start=payload.frame_start,
                frame_end=payload.frame_end,
                source_json=snapshot,
                source_sha256=canonical_json_sha256(snapshot),
                reviewer=payload.reviewer,
                reason=payload.reason,
            )
        )

    def link(self, project_id: str, payload: PoseLinkCreate) -> PoseLinkResponse:
        self._lock_project(project_id)
        return self._append(project_id, payload, None)

    def _head(self, project_id: str, link_id: str, revision: int) -> EcologyPoseLinkRevision:
        row = self._history(project_id, link_id)[-1]
        if row.revision != revision or row.action == "unlink":
            raise ConflictError("Pose link is superseded or unlinked")
        return row

    def correct(
        self, project_id: str, link_id: str, payload: PoseLinkCorrection
    ) -> PoseLinkResponse:
        self._lock_project(project_id)
        return self._append(
            project_id, payload, self._head(project_id, link_id, payload.expected_revision)
        )

    def unlink(self, project_id: str, link_id: str, payload: PoseLinkUnlink) -> PoseLinkResponse:
        self._lock_project(project_id)
        previous = self._head(project_id, link_id, payload.expected_revision)
        return self._persist(
            EcologyPoseLinkRevision(
                project_id=project_id,
                link_id=link_id,
                revision=previous.revision + 1,
                action="unlink",
                supersedes_id=previous.id,
                organism_revision_id=previous.organism_revision_id,
                association_run_id=previous.association_run_id,
                animal_identity_id=previous.animal_identity_id,
                frame_start=previous.frame_start,
                frame_end=previous.frame_end,
                source_json=previous.source_json,
                source_sha256=previous.source_sha256,
                reviewer=payload.reviewer,
                reason=payload.reason,
            )
        )

    def history(self, project_id: str, link_id: str) -> list[PoseLinkResponse]:
        rows = self._history(project_id, link_id)
        return [self._response(row, superseded=row.id != rows[-1].id) for row in rows]

    def list(
        self, project_id: str, *, organism_key: str | None, limit: int, offset: int
    ) -> PoseLinkList:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        model = EcologyPoseLinkRevision
        latest = self._latest_revisions(project_id)
        if organism_key is None:
            statement = self._current_statement(project_id)
        else:
            # A corrected link can belong to a different organism. The old
            # organism still shows its latest historical revision and audit path.
            matching = (
                select(model.link_id, func.max(model.revision).label("revision"))
                .join(
                    EcologyIdentityRevision,
                    EcologyIdentityRevision.id == model.organism_revision_id,
                )
                .where(
                    model.project_id == project_id,
                    EcologyIdentityRevision.organism_key == organism_key,
                )
                .group_by(model.link_id)
                .subquery()
            )
            statement = select(model).join(
                matching,
                (model.link_id == matching.c.link_id) & (model.revision == matching.c.revision),
            )
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        records = cast(
            list[tuple[EcologyPoseLinkRevision, int]],
            self.session.execute(
                statement.add_columns(latest.c.revision)
                .join(latest, model.link_id == latest.c.link_id)
                .order_by(model.created_at.desc(), model.link_id)
                .limit(limit)
                .offset(offset)
            ).all(),
        )
        return PoseLinkList(
            items=[
                self._response(row, superseded=row.revision != newest) for row, newest in records
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
