"""Atomically reconcile a sealed field batch into the project's normal media."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, VideoAsset
from reefvision.db.models.field_capture import (
    FieldCaptureBatch,
    FieldCaptureObservation,
    FieldCaptureReconciliationRecord,
    FieldCaptureReview,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.geospatial.models import TelemetryMetadata
from reefvision.repositories.images import ImageRepository
from reefvision.schemas.field_capture import (
    FieldCaptureConflict,
    FieldCaptureEntry,
    FieldCaptureReconciliation,
    FieldCaptureReconciliationItem,
    FieldCaptureReviewCreate,
    FieldCaptureReviewResponse,
)
from reefvision.services.field_capture import FieldCaptureService, capture_entry
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.field_capture import FieldCaptureStorage, video_content_type
from reefvision.storage.images import InvalidImageError, UnsupportedImageError, inspect_staged_image
from reefvision.storage.video_media import inspect_video


class FieldCaptureReconciliationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.capture = FieldCaptureService(session, settings)

    def _existing(self, batch_id: str) -> FieldCaptureReconciliation | None:
        record = self.session.get(FieldCaptureReconciliationRecord, batch_id)
        if record is None:
            return None
        report = FieldCaptureReconciliation.model_validate(record.report_json)
        digest = canonical_json_sha256(report.model_dump(mode="json", exclude={"report_sha256"}))
        if digest != report.report_sha256 or digest != record.report_sha256:
            raise ConflictError("The saved field reconciliation receipt has changed")
        return report

    def get_report(self, project_id: str, batch_id: str) -> FieldCaptureReconciliation:
        self.capture.batch(project_id, batch_id)
        report = self._existing(batch_id)
        if report is None:
            raise NotFoundError("Field batch has not been reconciled")
        return report

    def reconcile(
        self, project_id: str, batch_id: str, manifest_sha256: str
    ) -> FieldCaptureReconciliation:
        try:
            return self._reconcile(project_id, batch_id, manifest_sha256)
        except Exception:
            self.session.rollback()
            raise

    def _reconcile(
        self, project_id: str, batch_id: str, manifest_sha256: str
    ) -> FieldCaptureReconciliation:
        batch = self.capture.lock_batch(project_id, batch_id)
        if batch.manifest_sha256 is None or batch.manifest_sha256 != manifest_sha256:
            raise ConflictError("Reconciliation requires the current sealed field batch checksum")
        rows = self.capture.observations(batch)
        self.capture.manifest(batch, rows)
        storage = self.capture.storage(project_id)
        saved = self._existing(batch_id)
        if saved is not None:
            if (str(saved.project_id), str(saved.batch_id), saved.manifest_sha256) != (
                project_id,
                batch.id,
                manifest_sha256,
            ):
                raise ConflictError("The saved reconciliation belongs to different field evidence")
            self._verify_saved(storage, saved, rows)
            self.session.commit()
            return saved

        results: list[FieldCaptureReconciliationItem] = []
        with storage.staging() as directory:
            for row in rows:
                entry = capture_entry(row)
                source = storage.verify(row.managed_path, row.sha256, row.size_bytes)
                conflicts = self._conflicts(batch, row, entry)
                asset_id, created = self._reconcile_media(
                    project_id, storage, source, entry, directory
                )
                results.append(
                    FieldCaptureReconciliationItem(
                        observation_id=UUID(row.id),
                        source_observation_id=entry.source_observation_id,
                        kind=entry.kind,
                        sha256=entry.sha256,
                        asset_id=UUID(asset_id),
                        outcome="conflict"
                        if conflicts
                        else "imported"
                        if created
                        else "duplicate_media",
                        conflicts=conflicts,
                    )
                )
                self.session.flush()
        body: dict[str, Any] = {
            "project_id": project_id,
            "batch_id": batch_id,
            "manifest_sha256": manifest_sha256,
            "rows": [item.model_dump(mode="json") for item in results],
        }
        report = FieldCaptureReconciliation.model_validate(
            {
                **body,
                "report_sha256": canonical_json_sha256(body),
            }
        )
        self.session.add(
            FieldCaptureReconciliationRecord(
                batch_id=batch.id,
                report_sha256=report.report_sha256,
                report_json=report.model_dump(mode="json"),
            )
        )
        self.session.commit()
        return report

    def _verify_saved(
        self,
        storage: FieldCaptureStorage,
        report: FieldCaptureReconciliation,
        originals: list[FieldCaptureObservation],
    ) -> None:
        if [str(row.observation_id) for row in report.rows] != [row.id for row in originals]:
            raise ConflictError(
                "Saved field reconciliation differs from the sealed observation roster"
            )
        for result, original in zip(report.rows, originals, strict=True):
            storage.verify(original.managed_path, original.sha256, original.size_bytes)
            if result.kind == "image":
                asset: ImageAsset | VideoAsset | None = self.session.get(
                    ImageAsset, str(result.asset_id)
                )
            else:
                asset = self.session.get(VideoAsset, str(result.asset_id))
            if asset is None or (asset.project_id, asset.sha256) != (
                original.project_id,
                original.sha256,
            ):
                raise ConflictError(
                    "A reconciled project original is missing or refers to different bytes"
                )
            storage.verify(asset.managed_path, original.sha256, original.size_bytes)

    def _conflicts(
        self,
        batch: FieldCaptureBatch,
        row: FieldCaptureObservation,
        entry: FieldCaptureEntry,
    ) -> list[FieldCaptureConflict]:
        model = FieldCaptureObservation
        identities = [
            model.source_observation_id == row.source_observation_id,
            and_(model.kind == row.kind, model.sha256 == row.sha256),
        ]
        if row.claim_key is not None:
            identities.append(model.claim_key == row.claim_key)
        sealed_prior = select(FieldCaptureReconciliationRecord.batch_id)
        candidates = self.session.scalars(
            select(model)
            .where(
                model.project_id == batch.project_id,
                or_(*identities),
                or_(
                    model.batch_id.in_(sealed_prior),
                    and_(model.batch_id == batch.id, model.ordinal < row.ordinal),
                ),
            )
            .order_by(model.batch_id, model.ordinal)
        )
        result: list[FieldCaptureConflict] = []
        for candidate in candidates:
            against = capture_entry(candidate)
            changed_claim = entry.metadata.model_dump(
                exclude={"observer"}
            ) != against.metadata.model_dump(exclude={"observer"})
            changed_media = (entry.sha256, entry.kind, entry.size_bytes) != (
                against.sha256,
                against.kind,
                against.size_bytes,
            )
            if against.source_observation_id == entry.source_observation_id and entry != against:
                reason = "source_identity_changed"
            elif (
                row.claim_key is not None
                and row.claim_key == candidate.claim_key
                and (changed_claim or changed_media)
            ):
                reason = "declared_observation_changed"
            elif not changed_media and changed_claim:
                reason = "media_metadata_changed"
            else:
                continue
            result.append(
                FieldCaptureConflict(
                    against_observation_id=UUID(candidate.id),
                    against_batch_id=UUID(candidate.batch_id),
                    against=against,
                    reason=reason,
                )
            )
        return result

    def _reconcile_media(
        self,
        project_id: str,
        storage: FieldCaptureStorage,
        source: Path,
        entry: FieldCaptureEntry,
        directory: Path,
    ) -> tuple[str, bool]:
        if entry.kind == "image":
            duplicate: ImageAsset | VideoAsset | None = ImageRepository(
                self.session
            ).find_duplicate(project_id, entry.sha256)
        else:
            duplicate = self.session.scalar(
                select(VideoAsset)
                .where(
                    VideoAsset.project_id == project_id,
                    VideoAsset.sha256 == entry.sha256,
                )
                .order_by(VideoAsset.created_at, VideoAsset.id)
                .limit(1)
            )
        if duplicate is not None:
            storage.verify(duplicate.managed_path, entry.sha256, entry.size_bytes)
            return duplicate.id, False

        # Recover the same canonical path when interrupted after file publication.
        asset_id = str(
            uuid5(NAMESPACE_URL, f"reefvision-field:{project_id}:{entry.kind}:{entry.sha256}")
        )
        if entry.kind == "image":
            try:
                inspected = inspect_staged_image(source, entry.sha256, entry.size_bytes)
            except (InvalidImageError, UnsupportedImageError) as exc:
                raise ValidationError(str(exc)) from exc
            path = f"{storage.project_root}/images/originals/{asset_id}{inspected.extension}"
            thumbnail_path = f"{storage.project_root}/images/thumbnails/{asset_id}.jpg"
            storage.publish_project_original(
                source, path, entry.sha256, entry.size_bytes, directory
            )
            self.session.add(
                ImageAsset(
                    id=asset_id,
                    project_id=project_id,
                    original_filename=entry.filename,
                    managed_path=path,
                    sha256=entry.sha256,
                    width_px=inspected.width_px,
                    height_px=inspected.height_px,
                    file_size_bytes=entry.size_bytes,
                    media_type=inspected.media_type,
                    import_source=entry.filename,
                    capture_timestamp=entry.metadata.clock.utc_timestamp(),
                    metadata_json=inspected.metadata,
                )
            )
            self.session.add(
                Job(
                    project_id=project_id,
                    job_type="thumbnail",
                    status="queued",
                    progress_total=1,
                    request_json={
                        "image_id": asset_id,
                        "source_path": path,
                        "thumbnail_path": thumbnail_path,
                    },
                )
            )
        else:
            metadata = inspect_video(source)
            suffix = Path(entry.filename).suffix.casefold()
            path = f"{storage.project_root}/videos/originals/{asset_id}{suffix}"
            storage.publish_project_original(
                source, path, entry.sha256, entry.size_bytes, directory
            )
            telemetry = TelemetryMetadata().model_dump(mode="json")
            self.session.add(
                VideoAsset(
                    id=asset_id,
                    project_id=project_id,
                    original_filename=entry.filename,
                    managed_path=path,
                    sha256=entry.sha256,
                    media_type=video_content_type(entry.filename),
                    width_px=int(metadata["width_px"]),
                    height_px=int(metadata["height_px"]),
                    frame_count=int(metadata["frame_count"]),
                    fps=float(metadata["fps"]),
                    duration_seconds=float(metadata["duration_seconds"]),
                    metadata_json={
                        "file_size_bytes": entry.size_bytes,
                        "telemetry": telemetry,
                        "airdata_telemetry": telemetry,
                        "airdata_alignment": {"time_offset_s": 0.0, "evidence": None},
                    },
                )
            )
        return asset_id, True

    @staticmethod
    def _review_response(review: FieldCaptureReview) -> FieldCaptureReviewResponse:
        return FieldCaptureReviewResponse(
            id=UUID(review.id),
            observation_id=UUID(review.observation_id),
            against_observation_id=UUID(review.against_observation_id),
            reviewer=review.reviewer,
            decision=review.decision,
            notes=review.notes,
            created_at=review.created_at.replace(tzinfo=UTC),
        )

    def list_reviews(self, project_id: str, batch_id: str) -> list[FieldCaptureReviewResponse]:
        self.capture.batch(project_id, batch_id)
        return [
            self._review_response(row)
            for row in self.session.scalars(
                select(FieldCaptureReview)
                .where(FieldCaptureReview.batch_id == batch_id)
                .order_by(FieldCaptureReview.created_at, FieldCaptureReview.id)
            )
        ]

    def review(
        self,
        project_id: str,
        batch_id: str,
        payload: FieldCaptureReviewCreate,
    ) -> FieldCaptureReviewResponse:
        self.capture.lock_batch(project_id, batch_id)
        report = self.get_report(project_id, batch_id)
        valid = any(
            row.observation_id == payload.observation_id
            and any(
                conflict.against_observation_id == payload.against_observation_id
                for conflict in row.conflicts
            )
            for row in report.rows
        )
        if not valid:
            raise ValidationError("Choose a conflict listed in the saved reconciliation receipt")
        review = self.session.scalar(
            select(FieldCaptureReview).where(
                FieldCaptureReview.observation_id == str(payload.observation_id),
                FieldCaptureReview.against_observation_id == str(payload.against_observation_id),
            )
        )
        if review is not None:
            response = self._review_response(review)
            if response.model_dump(exclude={"id", "created_at"}) != payload.model_dump():
                raise ConflictError("This field conflict already has a recorded review decision")
            self.session.commit()
            return response
        review = FieldCaptureReview(
            id=str(uuid4()),
            batch_id=batch_id,
            observation_id=str(payload.observation_id),
            against_observation_id=str(payload.against_observation_id),
            reviewer=payload.reviewer,
            decision=payload.decision,
            notes=payload.notes,
        )
        self.session.add(review)
        self.session.commit()
        return self._review_response(review)
