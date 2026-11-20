"""Capture and transfer immutable local field batches."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.field_capture import FieldCaptureBatch, FieldCaptureObservation
from reefvision.db.models.project import Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.field_capture import (
    MAX_FIELD_OBSERVATIONS,
    FieldCaptureArchiveManifest,
    FieldCaptureBatchPage,
    FieldCaptureBatchResponse,
    FieldCaptureBatchSummary,
    FieldCaptureEntry,
    FieldCaptureImportResponse,
    FieldCaptureManifest,
    FieldCaptureMetadata,
    FieldCaptureObservationResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.field_capture import (
    MAX_FIELD_MEDIA_BYTES,
    FieldCaptureStorage,
    field_filename,
    field_media_kind,
)


def capture_entry(row: FieldCaptureObservation) -> FieldCaptureEntry:
    kind = field_media_kind(row.filename)
    if kind != row.kind:
        raise ConflictError("Stored field media kind disagrees with its source filename")
    return FieldCaptureEntry(
        source_observation_id=UUID(row.source_observation_id),
        filename=row.filename,
        kind=kind,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        metadata=FieldCaptureMetadata.model_validate(row.metadata_json),
    )


class FieldCaptureService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def storage(self, project_id: str) -> FieldCaptureStorage:
        return FieldCaptureStorage(self.settings, self.project(project_id).storage_root)

    def batch(self, project_id: str, batch_id: str) -> FieldCaptureBatch:
        batch = self.session.scalar(
            select(FieldCaptureBatch)
            .where(FieldCaptureBatch.id == batch_id, FieldCaptureBatch.project_id == project_id)
            .execution_options(populate_existing=True)
        )
        if batch is None:
            raise NotFoundError("Field batch not found")
        return batch

    def lock_batch(self, project_id: str, batch_id: str) -> FieldCaptureBatch:
        # Acquire the SQLite writer slot before reading current batch state.
        self.session.execute(
            update(FieldCaptureBatch)
            .where(FieldCaptureBatch.id == batch_id, FieldCaptureBatch.project_id == project_id)
            .values(label=FieldCaptureBatch.label)
        )
        return self.batch(project_id, batch_id)

    def observations(self, batch: FieldCaptureBatch) -> list[FieldCaptureObservation]:
        return list(
            self.session.scalars(
                select(FieldCaptureObservation)
                .where(
                    FieldCaptureObservation.batch_id == batch.id,
                    FieldCaptureObservation.project_id == batch.project_id,
                )
                .order_by(FieldCaptureObservation.ordinal)
            )
        )

    @staticmethod
    def observation_response(row: FieldCaptureObservation) -> FieldCaptureObservationResponse:
        entry = capture_entry(row)
        return FieldCaptureObservationResponse(
            **entry.model_dump(),
            id=UUID(row.id),
            captured_at_utc=entry.metadata.clock.utc_timestamp(),
        )

    @staticmethod
    def summary(batch: FieldCaptureBatch) -> FieldCaptureBatchSummary:
        return FieldCaptureBatchSummary(
            id=UUID(batch.id),
            project_id=UUID(batch.project_id),
            origin_project_id=UUID(batch.origin_project_id),
            origin_batch_id=UUID(batch.origin_batch_id),
            label=batch.label,
            manifest_sha256=batch.manifest_sha256,
            created_at=batch.created_at.replace(tzinfo=UTC),
        )

    def response(self, batch: FieldCaptureBatch) -> FieldCaptureBatchResponse:
        return FieldCaptureBatchResponse(
            **self.summary(batch).model_dump(),
            observations=[self.observation_response(row) for row in self.observations(batch)],
        )

    def create_batch(self, project_id: str, label: str) -> FieldCaptureBatchResponse:
        self.project(project_id)
        batch_id = str(uuid4())
        batch = FieldCaptureBatch(
            id=batch_id,
            project_id=project_id,
            origin_project_id=project_id,
            origin_batch_id=batch_id,
            label=label,
        )
        self.session.add(batch)
        self.session.commit()
        return self.response(batch)

    def list_batches(self, project_id: str, page: int, page_size: int) -> FieldCaptureBatchPage:
        self.project(project_id)
        selection = select(FieldCaptureBatch).where(FieldCaptureBatch.project_id == project_id)
        total = self.session.scalar(select(func.count()).select_from(selection.subquery())) or 0
        rows = self.session.scalars(
            selection.order_by(FieldCaptureBatch.created_at.desc(), FieldCaptureBatch.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return FieldCaptureBatchPage(
            items=[self.summary(batch) for batch in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def add_observation(
        self,
        project_id: str,
        batch_id: str,
        filename: str | None,
        stream: BinaryIO,
        metadata: FieldCaptureMetadata,
    ) -> FieldCaptureObservationResponse:
        self.batch(project_id, batch_id)
        storage = self.storage(project_id)
        name = field_filename(filename)
        kind = field_media_kind(name)
        with storage.staging() as directory:
            path, digest, size = storage.stage_source(stream, name, kind, directory)
            batch = self.lock_batch(project_id, batch_id)
            if batch.manifest_sha256 is not None:
                raise ConflictError("A sealed field batch cannot accept new observations")
            rows = self.observations(batch)
            if len(rows) >= MAX_FIELD_OBSERVATIONS:
                raise ValidationError("Field batch reached its observation limit")
            media = {row.sha256: row.size_bytes for row in rows}
            media[digest] = size
            if sum(media.values()) > MAX_FIELD_MEDIA_BYTES:
                raise ValidationError("Field batch reached its source byte limit")
            source_id = uuid4()
            entry = FieldCaptureEntry(
                source_observation_id=source_id,
                filename=name,
                kind=kind,
                sha256=digest,
                size_bytes=size,
                metadata=metadata,
            )
            row = self._add_entry(batch, len(rows), entry, storage.preserve(path, entry), source_id)
            self.session.commit()
        return self.observation_response(row)

    def _add_entry(
        self,
        batch: FieldCaptureBatch,
        ordinal: int,
        entry: FieldCaptureEntry,
        relative: str,
        local_id: UUID,
    ) -> FieldCaptureObservation:
        key = entry.metadata.observation_key
        row = FieldCaptureObservation(
            id=str(local_id),
            batch_id=batch.id,
            project_id=batch.project_id,
            source_observation_id=str(entry.source_observation_id),
            ordinal=ordinal,
            filename=entry.filename,
            kind=entry.kind,
            sha256=entry.sha256,
            size_bytes=entry.size_bytes,
            managed_path=relative,
            claim_key=key.casefold() if key is not None else None,
            metadata_json=entry.metadata.model_dump(mode="json"),
        )
        self.session.add(row)
        return row

    def manifest(
        self, batch: FieldCaptureBatch, rows: list[FieldCaptureObservation]
    ) -> FieldCaptureArchiveManifest:
        if not rows:
            raise ValidationError("Add an observation before sealing the field batch")
        manifest = FieldCaptureManifest(
            origin_project_id=UUID(batch.origin_project_id),
            origin_batch_id=UUID(batch.origin_batch_id),
            label=batch.label,
            observations=[capture_entry(row) for row in rows],
        )
        digest = canonical_json_sha256(manifest.model_dump(mode="json"))
        if batch.manifest_sha256 is not None and digest != batch.manifest_sha256:
            raise ConflictError("Stored field batch manifest no longer matches its sealed checksum")
        return FieldCaptureArchiveManifest(manifest_sha256=digest, manifest=manifest)

    def seal(self, project_id: str, batch_id: str) -> FieldCaptureBatchResponse:
        batch = self.lock_batch(project_id, batch_id)
        rows = self.observations(batch)
        manifest = self.manifest(batch, rows)
        storage = self.storage(project_id)
        for row in rows:
            storage.verify(row.managed_path, row.sha256, row.size_bytes)
        batch.manifest_sha256 = manifest.manifest_sha256
        self.session.commit()
        return self.response(batch)

    def export_archive(self, project_id: str, batch_id: str) -> Path:
        batch = self.batch(project_id, batch_id)
        if batch.manifest_sha256 is None:
            raise ConflictError("Seal the field batch before exporting it")
        rows = self.observations(batch)
        package = self.manifest(batch, rows)
        return self.storage(project_id).write_archive(
            package, [(capture_entry(row), row.managed_path) for row in rows]
        )

    def import_archive(self, project_id: str, stream: BinaryIO) -> FieldCaptureImportResponse:
        storage = self.storage(project_id)
        with storage.read_archive(stream) as (package, originals):
            # Serialize replay lookup and insertion even when the batch has no local ID yet.
            self.session.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(updated_at=Project.updated_at)
            )
            batch = self.session.scalar(
                select(FieldCaptureBatch).where(
                    FieldCaptureBatch.project_id == project_id,
                    FieldCaptureBatch.manifest_sha256 == package.manifest_sha256,
                )
            )
            if batch is not None:
                for row in self.observations(batch):
                    storage.verify(row.managed_path, row.sha256, row.size_bytes)
                self.session.commit()
                return FieldCaptureImportResponse(batch=self.response(batch), duplicate=True)
            manifest = package.manifest
            batch = FieldCaptureBatch(
                id=str(uuid4()),
                project_id=project_id,
                origin_project_id=str(manifest.origin_project_id),
                origin_batch_id=str(manifest.origin_batch_id),
                label=manifest.label,
                manifest_sha256=package.manifest_sha256,
            )
            self.session.add(batch)
            self.session.flush()
            for ordinal, entry in enumerate(manifest.observations):
                relative = storage.preserve(originals[entry.sha256], entry)
                self._add_entry(batch, ordinal, entry, relative, uuid4())
            self.session.commit()
        return FieldCaptureImportResponse(batch=self.response(batch), duplicate=False)

    def source(self, project_id: str, batch_id: str, observation_id: str) -> tuple[Path, str]:
        row = self.session.scalar(
            select(FieldCaptureObservation).where(
                FieldCaptureObservation.project_id == project_id,
                FieldCaptureObservation.batch_id == batch_id,
                FieldCaptureObservation.id == observation_id,
            )
        )
        if row is None:
            raise NotFoundError("Field observation not found")
        return self.storage(project_id).verify(
            row.managed_path, row.sha256, row.size_bytes
        ), row.filename
