"""Bind acquisition to local immutable evidence and advance its cursor atomically."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

from PIL import Image
from pydantic import TypeAdapter
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.acquisition_source import AcquisitionCapture, AcquisitionSource
from reefvision.db.models.field_capture import FieldCaptureBatch, FieldCaptureObservation
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.acquisition_camera import CameraUnavailable, capture_local_camera
from reefvision.schemas.acquisition_source import (
    AcquisitionCapturePage,
    AcquisitionCaptureReceipt,
    AcquisitionDispatch,
    AcquisitionMedia,
    AcquisitionReceiptData,
    AcquisitionSourceCreate,
    AcquisitionSourcePage,
    AcquisitionSourceResponse,
    AcquisitionStateChange,
    AcquisitionTime,
    CameraSource,
    RecordedSource,
    SimulatedSource,
    SourceConfiguration,
    SyntheticReading,
)
from reefvision.schemas.field_capture import (
    FieldCaptureClock,
    FieldCaptureEntry,
    FieldCaptureMetadata,
)
from reefvision.services.field_capture import FieldCaptureService, capture_entry
from reefvision.storage.acquisition_source import MAX_RECORDED_ORIGINAL_BYTES
from reefvision.storage.datasets import canonical_json_sha256


class SourceUnavailable(RuntimeError):
    """The current source entry could not be collected without changing the cursor."""


class SourceExhausted(RuntimeError):
    """The sealed source has no next entry."""


_CONFIG = TypeAdapter[SourceConfiguration](cast(Any, SourceConfiguration))
_CAMERA_CONSENT = timedelta(minutes=15)
_RETRY_DELAY = timedelta(seconds=5)


def _utc(time: datetime | None) -> datetime | None:
    if time is None:
        return None
    return time.replace(tzinfo=UTC) if time.tzinfo is None else time.astimezone(UTC)


def _source_digest(
    project_id: str, source_id: str, label: str, configuration: dict[str, Any]
) -> str:
    return canonical_json_sha256(
        {
            "identity_format": "reefvision-acquisition-source-1",
            "project_id": project_id,
            "source_id": source_id,
            "label": label,
            "configuration": configuration,
        }
    )


def verify_scheduled_source(
    session: Session, project_id: str, source_id: str, source_sha256: str
) -> AcquisitionSource:
    source = session.get(AcquisitionSource, source_id)
    if source is None or source.project_id != project_id:
        raise NotFoundError("Acquisition source was not found in this project")
    computed = _source_digest(project_id, source.id, source.label, source.configuration_json)
    if (
        computed != source.source_sha256
        or source.source_sha256 != source_sha256
        or source.kind != source.configuration_json.get("kind")
    ):
        raise ConflictError("The acquisition source differs from the pinned configuration")
    return source


class AcquisitionSourceService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.field = FieldCaptureService(session, settings)

    def _source(self, project_id: str, source_id: str) -> AcquisitionSource:
        source = self.session.get(AcquisitionSource, source_id)
        if source is None or source.project_id != project_id:
            raise NotFoundError("Acquisition source was not found in this project")
        return source

    def _locked_source(self, project_id: str, source_id: str) -> AcquisitionSource:
        # Reserve the database writer before checking the cursor or retry identity.
        self.session.execute(
            update(AcquisitionSource)
            .where(AcquisitionSource.project_id == project_id, AcquisitionSource.id == source_id)
            .values(revision=AcquisitionSource.revision, updated_at=AcquisitionSource.updated_at)
        )
        row = self._source(project_id, source_id)
        self.session.refresh(row)
        return row

    @staticmethod
    def _response(row: AcquisitionSource) -> AcquisitionSourceResponse:
        return AcquisitionSourceResponse.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "label": row.label,
                "configuration": row.configuration_json,
                "source_sha256": row.source_sha256,
                "cursor": row.cursor,
                "state": row.state,
                "revision": row.revision,
                "last_error": row.last_error,
                "next_retry_at": _utc(row.next_retry_at),
                "local_consent_until": _utc(row.local_consent_until),
                "created_at": _utc(row.created_at),
                "updated_at": _utc(row.updated_at),
            }
        )

    def read_source(self, project_id: str, source_id: str) -> AcquisitionSourceResponse:
        return self._response(self._source(project_id, source_id))

    def list_sources(self, project_id: str, page: int, page_size: int) -> AcquisitionSourcePage:
        self.field.project(project_id)
        select_rows = select(AcquisitionSource).where(AcquisitionSource.project_id == project_id)
        total = self.session.scalar(select(func.count()).select_from(select_rows.subquery())) or 0
        rows = self.session.scalars(
            select_rows.order_by(AcquisitionSource.created_at.desc(), AcquisitionSource.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return AcquisitionSourcePage(
            items=[self._response(row) for row in rows], total=total, page=page, page_size=page_size
        )

    def create(
        self, project_id: str, payload: AcquisitionSourceCreate
    ) -> AcquisitionSourceResponse:
        self.field.project(project_id)
        configuration = payload.configuration
        if isinstance(configuration, RecordedSource):
            self._recorded(project_id, configuration)
        elif isinstance(configuration, SimulatedSource):
            configuration = configuration.model_copy(
                update={"start_at_utc": configuration.start_at_utc.astimezone(UTC)}
            )
        config_json = configuration.model_dump(mode="json")
        source_id = str(uuid4())
        row = AcquisitionSource(
            project_id=project_id,
            id=source_id,
            label=payload.label,
            kind=configuration.kind,
            configuration_json=config_json,
            source_sha256=_source_digest(project_id, source_id, payload.label, config_json),
            state="ready",
        )
        self.session.add(row)
        self.session.commit()
        return self._response(row)

    def change_state(
        self, project_id: str, source_id: str, change: AcquisitionStateChange
    ) -> AcquisitionSourceResponse:
        row = self._locked_source(project_id, source_id)
        if row.revision != change.revision:
            raise ConflictError("The acquisition source changed. Refresh it and retry the action")
        now = utc_now()
        match change.action:
            case "pause":
                if row.state == "exhausted":
                    raise ConflictError("This recorded source is already exhausted")
                row.state = "paused"
                row.local_consent_until = None
            case "resume":
                if row.state == "exhausted":
                    raise ConflictError("This source has no remaining observations")
                retry_at = _utc(row.next_retry_at)
                if retry_at is not None and retry_at > now:
                    raise ConflictError("Wait until the displayed retry time before reconnecting")
                row.state = "ready"
                row.next_retry_at = None
                row.last_error = None
            case "approve_camera":
                if row.kind != "camera" or row.state != "ready":
                    raise ConflictError("Only an available local camera can be approved")
                row.local_consent_until = now + _CAMERA_CONSENT
            case "revoke_camera":
                if row.kind != "camera":
                    raise ValidationError("Only a local camera uses capture consent")
                row.local_consent_until = None
        row.revision += 1
        self.session.commit()
        return self._response(row)

    def _recorded(
        self, project_id: str, configuration: RecordedSource
    ) -> tuple[FieldCaptureBatch, list[FieldCaptureObservation]]:
        batch = self.field.batch(project_id, str(configuration.batch_id))
        if configuration.manifest_sha256 != batch.manifest_sha256:
            raise ConflictError("Use a sealed field batch with its original manifest checksum")
        rows = self.field.observations(batch)
        self.field.manifest(batch, rows)
        if any(row.size_bytes > MAX_RECORDED_ORIGINAL_BYTES for row in rows):
            raise ValidationError("A recorded original exceeds the 512 MiB acquisition limit")
        return batch, rows

    def _preserve_frame(
        self,
        source: AcquisitionSource,
        data: bytes,
        clock: FieldCaptureClock,
        observer: str,
    ) -> tuple[FieldCaptureBatch, FieldCaptureObservation]:
        storage = self.field.storage(source.project_id)
        batch_id, observation_id = uuid4(), uuid4()
        batch = FieldCaptureBatch(
            id=str(batch_id),
            project_id=source.project_id,
            origin_project_id=source.project_id,
            origin_batch_id=str(batch_id),
            label=f"{source.label} · {source.cursor + 1}"[:200],
        )
        self.session.add(batch)
        self.session.flush()
        name = f"acquisition-{source.cursor + 1:06}.png"
        with storage.staging() as directory:
            path, content_sha, size = storage.stage_source(BytesIO(data), name, "image", directory)
            entry = FieldCaptureEntry(
                source_observation_id=observation_id,
                filename=name,
                kind="image",
                sha256=content_sha,
                size_bytes=size,
                metadata=FieldCaptureMetadata(
                    observer=observer,
                    clock=clock,
                    source_label=source.label,
                    observation_key=f"{source.id}:{source.cursor}",
                ),
            )
            relative = storage.preserve(path, entry)
            row = self.field._add_entry(batch, 0, entry, relative, observation_id)
            batch.manifest_sha256 = self.field.manifest(batch, [row]).manifest_sha256
        self.session.flush()
        return batch, row

    @staticmethod
    def _media(batch: FieldCaptureBatch, row: FieldCaptureObservation) -> AcquisitionMedia:
        if batch.manifest_sha256 is None:
            raise ConflictError("The field evidence has no sealed manifest")
        entry = capture_entry(row)
        return AcquisitionMedia(
            field_batch_id=UUID(batch.id),
            field_batch_sha256=batch.manifest_sha256,
            field_observation_id=UUID(row.id),
            original_observation_id=entry.source_observation_id,
            filename=entry.filename,
            kind=entry.kind,
            sha256=entry.sha256,
            size_bytes=entry.size_bytes,
        )

    def _observe(
        self, source: AcquisitionSource, config: SourceConfiguration
    ) -> tuple[
        FieldCaptureBatch, FieldCaptureObservation, AcquisitionTime, SyntheticReading | None, bool
    ]:
        if isinstance(config, RecordedSource):
            try:
                batch, rows = self._recorded(source.project_id, config)
                if source.cursor >= len(rows):
                    raise SourceExhausted("The sealed recording has no remaining observations")
                row = rows[source.cursor]
                self.field.storage(source.project_id).verify(
                    row.managed_path, row.sha256, row.size_bytes
                )
            except (ValidationError, ConflictError, NotFoundError) as exc:
                raise SourceUnavailable(
                    "The sealed recording or its next original is unavailable. "
                    "Restore its original bytes before reconnecting"
                ) from exc
            clock = capture_entry(row).metadata.clock
            return (
                batch,
                row,
                AcquisitionTime(
                    origin="field_source", clock=clock, captured_at_utc=clock.utc_timestamp()
                ),
                None,
                source.cursor + 1 == len(rows),
            )

        if isinstance(config, CameraSource):
            storage = self.field.storage(source.project_id)
            try:
                with storage.staging() as directory:
                    frame = capture_local_camera(config.camera_index, directory)
            except CameraUnavailable as exc:
                raise SourceUnavailable(str(exc)) from exc
            clock = FieldCaptureClock(
                state="unknown",
                evidence=(
                    "The camera did not supply an exposure timestamp. "
                    "Host receipt time and elapsed driver read are recorded separately."
                ),
            )
            time = AcquisitionTime(
                origin="local_host_read",
                clock=clock,
                captured_at_utc=None,
                host_received_at_utc=frame.received_at_utc,
                host_read_elapsed_seconds=frame.read_elapsed_seconds,
            )
            batch, row = self._preserve_frame(
                source, frame.png, clock, "Explicitly approved local camera"
            )
            return batch, row, time, None, False

        try:
            captured_at = config.start_at_utc + timedelta(
                seconds=config.period_seconds * source.cursor
            )
        except OverflowError as exc:
            raise SourceExhausted("The synthetic clock reached its supported date range") from exc
        clock = FieldCaptureClock(
            state="known_offset",
            wall_time=captured_at.replace(tzinfo=None).isoformat(),
            utc_offset_minutes=0,
            evidence="Deterministic time from the configured UTC start, period and cursor.",
        )
        colors = sha256(f"reefvision-synthetic-v1:{config.seed}:{source.cursor}".encode()).digest()
        png = BytesIO()
        image = Image.new("RGB", (48, 32), tuple(colors[:3]))
        image.paste(tuple(colors[3:6]), (12, 8, 36, 24))
        image.save(png, format="PNG")
        time = AcquisitionTime(
            origin="synthetic_clock",
            clock=clock,
            captured_at_utc=captured_at,
            uncertainty_seconds=0,
        )
        batch, row = self._preserve_frame(
            source, png.getvalue(), clock, "Deterministic ReefVision simulator"
        )
        return batch, row, time, SyntheticReading(value=colors[6] % 101), False

    def capture(
        self,
        project_id: str,
        source_id: str,
        source_sha256: str,
        key: str,
        dispatch: AcquisitionDispatch,
        *,
        confirm_camera: bool = False,
    ) -> AcquisitionCaptureReceipt:
        source = self._locked_source(project_id, source_id)
        verify_scheduled_source(self.session, project_id, source_id, source_sha256)
        prior = self.session.scalar(
            select(AcquisitionCapture).where(
                AcquisitionCapture.source_id == source_id,
                AcquisitionCapture.capture_key == key,
            )
        )
        if prior is not None:
            receipt = self._check_receipt(prior, verify_original=True)
            self.session.commit()
            return receipt
        if source.state != "ready":
            raise ConflictError(
                "Acquisition is " + source.state + ". Review the source status before capturing"
            )
        config = _CONFIG.validate_python(source.configuration_json)
        if isinstance(config, CameraSource):
            approved_until = _utc(source.local_consent_until)
            if approved_until is None or approved_until <= utc_now():
                raise ConflictError("Approve this local camera before capture")
            if dispatch.kind == "manual" and not confirm_camera:
                raise ConflictError(
                    "Confirm that this action may capture one frame from the selected local camera"
                )
        try:
            batch, row, time, synthetic, exhausted = self._observe(source, config)
        except (SourceUnavailable, SourceExhausted) as exc:
            disconnected = isinstance(exc, SourceUnavailable)
            source.state = "disconnected" if disconnected else "exhausted"
            source.last_error = str(exc)
            source.next_retry_at = utc_now() + _RETRY_DELAY if disconnected else None
            source.local_consent_until = None
            source.revision += 1
            self.session.commit()
            raise ConflictError(str(exc)) from exc

        capture_id = uuid4()
        payload = AcquisitionReceiptData(
            id=capture_id,
            project_id=UUID(project_id),
            source_id=UUID(source_id),
            source_kind=config.kind,
            source_sha256=source.source_sha256,
            ordinal=source.cursor,
            dispatch=dispatch,
            time=time,
            media=self._media(batch, row),
            synthetic_reading=synthetic,
            recorded_at_utc=utc_now(),
        )
        body = payload.model_dump(mode="json")
        digest = canonical_json_sha256(body)
        self.session.add(
            AcquisitionCapture(
                id=str(capture_id),
                project_id=project_id,
                source_id=source_id,
                capture_key=key,
                ordinal=source.cursor,
                field_batch_id=batch.id,
                field_observation_id=row.id,
                content_sha256=digest,
                receipt_json=body,
            )
        )
        source.cursor += 1
        source.revision += 1
        if exhausted:
            source.state = "exhausted"
        self.session.commit()
        return AcquisitionCaptureReceipt(content_sha256=digest, receipt=payload)

    def list_captures(
        self, project_id: str, source_id: str, page: int, page_size: int
    ) -> AcquisitionCapturePage:
        self._source(project_id, source_id)
        selection = select(AcquisitionCapture).where(
            AcquisitionCapture.project_id == project_id, AcquisitionCapture.source_id == source_id
        )
        total = self.session.scalar(select(func.count()).select_from(selection.subquery())) or 0
        rows = self.session.scalars(
            selection.order_by(AcquisitionCapture.ordinal.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return AcquisitionCapturePage(
            items=[self._check_receipt(row, verify_original=False) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_capture(
        self,
        project_id: str,
        capture_id: str,
        *,
        source_id: str | None = None,
        expected_sha256: str | None = None,
    ) -> AcquisitionCaptureReceipt:
        row = self.session.get(AcquisitionCapture, capture_id)
        if (
            row is None
            or row.project_id != project_id
            or (source_id is not None and row.source_id != source_id)
        ):
            raise NotFoundError("Acquisition receipt was not found in this project")
        if expected_sha256 is not None and row.content_sha256 != expected_sha256:
            raise ConflictError("The acquisition receipt differs from the pinned checksum")
        return self._check_receipt(row, verify_original=True)

    def _check_receipt(
        self, row: AcquisitionCapture, *, verify_original: bool
    ) -> AcquisitionCaptureReceipt:
        if canonical_json_sha256(row.receipt_json) != row.content_sha256:
            raise ConflictError("Stored acquisition receipt checksum does not match its evidence")
        receipt = AcquisitionReceiptData.model_validate(row.receipt_json)
        if (
            str(receipt.id) != row.id
            or str(receipt.project_id) != row.project_id
            or str(receipt.source_id) != row.source_id
            or receipt.ordinal != row.ordinal
            or str(receipt.media.field_batch_id) != row.field_batch_id
            or str(receipt.media.field_observation_id) != row.field_observation_id
        ):
            raise ConflictError(
                "Stored acquisition receipt does not match its recorded source identities"
            )
        if verify_original:
            verify_scheduled_source(
                self.session, row.project_id, row.source_id, receipt.source_sha256
            )
            batch = self.field.batch(row.project_id, row.field_batch_id)
            entries = self.field.observations(batch)
            self.field.manifest(batch, entries)
            entry = next((entry for entry in entries if entry.id == row.field_observation_id), None)
            if entry is None or self._media(batch, entry) != receipt.media:
                raise ConflictError("The acquisition receipt no longer matches the field original")
            self.field.storage(row.project_id).verify(
                entry.managed_path, entry.sha256, entry.size_bytes
            )
        return AcquisitionCaptureReceipt(content_sha256=row.content_sha256, receipt=receipt)
