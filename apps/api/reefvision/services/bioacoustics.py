"""Local WAV provenance, manual proposals, attributed reviews and frozen clock reports."""

from datetime import UTC, datetime, timedelta
from fractions import Fraction
from math import isfinite
from pathlib import Path
from typing import IO, TypeVar
from uuid import UUID, uuid4

from pydantic import ValidationError as InvalidStoredValue
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.bioacoustics import (
    BioacousticAsset,
    BioacousticClockAnchor,
    BioacousticProposal,
    BioacousticReport,
    BioacousticReview,
)
from reefvision.db.models.project import Project
from reefvision.db.models.video_asset import VideoAsset
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.bioacoustics import (
    AUDIO_ANCHOR,
    AUDIO_ANCHOR_READ,
    MAX_AUDIO_ANCHORS,
    MAX_AUDIO_PROPOSALS,
    AudioAlignment,
    AudioAnchorCreate,
    AudioAnchorRead,
    AudioAssetRead,
    AudioPage,
    AudioProposalCreate,
    AudioProposalRead,
    AudioReportCreate,
    AudioReportEntry,
    AudioReportRead,
    AudioReportSnapshot,
    AudioReviewCreate,
    AudioReviewRead,
    AudioWaveform,
    UTCAnchor,
    VideoAnchor,
)
from reefvision.storage.bioacoustics import (
    AudioStorage,
    audio_filename,
    audio_managed_path,
    inspect_wav,
    read_waveform,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.identity import get_local_user_identity

Record = TypeVar(
    "Record",
    BioacousticAsset,
    BioacousticClockAnchor,
    BioacousticProposal,
    BioacousticReport,
    BioacousticReview,
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def audio_asset_read(row: BioacousticAsset) -> AudioAssetRead:
    return AudioAssetRead.model_validate(row).model_copy(update={"created_at": utc(row.created_at)})


def audio_review_read(row: BioacousticReview) -> AudioReviewRead:
    return AudioReviewRead.model_validate(row).model_copy(
        update={"reviewed_at": utc(row.reviewed_at)}
    )


def audio_anchor_read(row: BioacousticClockAnchor) -> AudioAnchorRead:
    try:
        anchor = AUDIO_ANCHOR.validate_python(row.anchor_json)
        if canonical_json_sha256(anchor.model_dump(mode="json")) != row.anchor_sha256:
            raise ConflictError("The saved audio clock anchor checksum differs")
        return AUDIO_ANCHOR_READ.validate_python(
            {
                **anchor.model_dump(),
                "id": row.id,
                "asset_id": row.asset_id,
                "project_id": row.project_id,
                "anchor_sha256": row.anchor_sha256,
                "author": row.author,
                "created_at": utc(row.created_at),
            }
        )
    except InvalidStoredValue as exc:
        raise ConflictError("The saved audio clock anchor is invalid") from exc


def audio_proposal_read(
    row: BioacousticProposal, review: AudioReviewRead | None
) -> AudioProposalRead:
    try:
        if canonical_json_sha256(row.proposal_json) != row.proposal_sha256:
            raise ConflictError("The saved audio proposal checksum differs")
        return AudioProposalRead.model_validate(
            {
                **row.proposal_json,
                "id": row.id,
                "project_id": row.project_id,
                "asset_id": row.asset_id,
                "proposal_sha256": row.proposal_sha256,
                "author": row.author,
                "created_at": utc(row.created_at),
                "status": review.decision if review else "proposed",
                "review_revision": review.revision if review else 0,
                "latest_review": review,
            }
        )
    except InvalidStoredValue as exc:
        raise ConflictError("The saved audio proposal is invalid") from exc


def audio_report_read(row: BioacousticReport) -> AudioReportRead:
    try:
        snapshot = AudioReportSnapshot.model_validate(row.snapshot_json)
        if (str(snapshot.source.id), str(snapshot.source.project_id)) != (
            row.asset_id,
            row.project_id,
        ):
            raise ConflictError("The report source differs from its owning recording")
        if canonical_json_sha256(snapshot.model_dump(mode="json")) != row.report_sha256:
            raise ConflictError("The saved audio report checksum differs")
    except InvalidStoredValue as exc:
        raise ConflictError("The saved bioacoustic report is invalid") from exc
    return AudioReportRead(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        asset_id=UUID(row.asset_id),
        snapshot=snapshot,
        report_sha256=row.report_sha256,
        created_at=utc(row.created_at),
    )


def micros(sample: int, sample_rate: int) -> int:
    """Round to the nearest microsecond without losing the exact stored sample index."""
    return round(Fraction(sample * 1_000_000, sample_rate))


def _clock_conflicts(
    anchor: AudioAnchorRead | None, siblings: list[AudioAnchorRead], rate: int
) -> list[UUID]:
    if anchor is None:
        return []
    conflicts = []
    for candidate in siblings:
        if candidate.id == anchor.id:
            continue
        measured = micros(candidate.sample - anchor.sample, rate)
        if isinstance(anchor, UTCAnchor) and isinstance(candidate, UTCAnchor):
            difference = (candidate.utc - anchor.utc) - timedelta(microseconds=measured)
            exceeds = abs(difference) > timedelta(
                microseconds=anchor.uncertainty_us + candidate.uncertainty_us + 1
            )
        elif (
            isinstance(anchor, VideoAnchor)
            and isinstance(candidate, VideoAnchor)
            and anchor.video_id == candidate.video_id
        ):
            exceeds = (
                abs(candidate.video_time_us - anchor.video_time_us - measured)
                > anchor.uncertainty_us + candidate.uncertainty_us + 1
            )
        else:
            continue
        if exceeds:
            conflicts.append(candidate.id)
    return conflicts


def align_event(
    event: AudioProposalRead,
    anchor: AudioAnchorRead | None,
    rate: int,
    conflict: bool,
    video_duration: int | None,
) -> AudioAlignment:
    if event.status != "accepted":
        return AudioAlignment(
            status="withheld", reason="An explicit accepted review is required for aligned use"
        )
    if anchor is None:
        return AudioAlignment(status="withheld", reason="No explicit clock anchor selected")
    if conflict:
        return AudioAlignment(
            status="withheld", reason="Clock anchors conflict outside their declared uncertainty"
        )
    start = micros(event.start_sample - anchor.sample, rate)
    end = micros(event.end_sample - anchor.sample, rate)
    if isinstance(anchor, UTCAnchor):
        try:
            return AudioAlignment(
                status="utc",
                start_utc=anchor.utc + timedelta(microseconds=start),
                end_utc=anchor.utc + timedelta(microseconds=end),
                uncertainty_us=anchor.uncertainty_us,
            )
        except OverflowError:
            return AudioAlignment(
                status="withheld", reason="The aligned interval is outside the supported UTC range"
            )
    begin, finish = anchor.video_time_us + start, anchor.video_time_us + end
    if video_duration is None:
        return AudioAlignment(
            status="withheld", reason="The pinned video source is unavailable or has changed"
        )
    if begin - anchor.uncertainty_us < 0 or finish + anchor.uncertainty_us > video_duration:
        return AudioAlignment(
            status="withheld",
            reason="The aligned interval and uncertainty exceed the pinned video timeline",
        )
    return AudioAlignment(
        status="video",
        start_video_us=begin,
        end_video_us=finish,
        uncertainty_us=anchor.uncertainty_us,
    )


class BioacousticsService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _storage(self, project_id: str) -> AudioStorage:
        return AudioStorage(self.settings, self._project(project_id).storage_root)

    def asset(self, project_id: str, asset_id: str) -> BioacousticAsset:
        asset = self.session.get(BioacousticAsset, asset_id)
        if asset is None or asset.project_id != project_id:
            raise NotFoundError("Audio recording was not found in this project")
        return asset

    def content(self, project_id: str, asset_id: str) -> Path:
        row = self.asset(project_id, asset_id)
        project = self._project(project_id)
        if row.managed_path != audio_managed_path(project.storage_root, row.sha256):
            raise ConflictError("Managed WAV is not its expected content-addressed original")
        return self._storage(project_id).verify(row.managed_path, row.sha256, row.size_bytes)

    def _flush(self, row: Record, message: str) -> None:
        self.session.add(row)
        try:
            self.session.flush()
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise ConflictError(message) from exc

    def _page(self, query: Select[Record], limit: int, offset: int) -> tuple[list[Record], int]:
        total = (
            self.session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
            or 0
        )
        return list(self.session.scalars(query.limit(limit).offset(offset))), total

    def import_recording(
        self, project_id: str, name: str | None, source: IO[bytes]
    ) -> AudioAssetRead:
        storage = self._storage(project_id)
        name = audio_filename(name)
        with storage.stage(source) as (path, digest, size, pcm):
            managed = storage.publish(path, digest, size)
            existing = self.session.scalar(
                select(BioacousticAsset).where(
                    BioacousticAsset.project_id == project_id,
                    BioacousticAsset.sha256 == digest,
                )
            )
            if existing is not None:
                return audio_asset_read(existing)
            identifier = str(uuid4())
            row = BioacousticAsset(
                id=identifier,
                project_id=project_id,
                original_asset_id=identifier,
                original_project_id=project_id,
                original_filename=name,
                sha256=digest,
                size_bytes=size,
                managed_path=managed,
                sample_count=pcm.sample_count,
                sample_rate_hz=pcm.sample_rate_hz,
                channel_count=pcm.channel_count,
                bits_per_sample=pcm.bits_per_sample,
            )
            self._flush(
                row, "A concurrent audio import completed. Reload the recordings before retrying"
            )
            return audio_asset_read(row)

    def list_assets(self, project_id: str, limit: int, offset: int) -> AudioPage[AudioAssetRead]:
        self._project(project_id)
        query = (
            select(BioacousticAsset)
            .where(BioacousticAsset.project_id == project_id)
            .order_by(BioacousticAsset.created_at.desc(), BioacousticAsset.id)
        )
        rows, total = self._page(query, limit, offset)
        return AudioPage(
            items=[audio_asset_read(row) for row in rows], total=total, limit=limit, offset=offset
        )

    def waveform(self, project_id: str, asset_id: str, channel: int, bins: int) -> AudioWaveform:
        row = self.asset(project_id, asset_id)
        path = self.content(project_id, asset_id)
        pcm = inspect_wav(path, row.size_bytes)
        self._source_layout(
            row, pcm.sample_count, pcm.sample_rate_hz, pcm.channel_count, pcm.bits_per_sample
        )
        return AudioWaveform(
            asset_id=UUID(row.id),
            source_sha256=row.sha256,
            channel=channel,
            sample_rate_hz=row.sample_rate_hz,
            sample_count=row.sample_count,
            peaks=read_waveform(path, pcm, channel, bins),
        )

    @staticmethod
    def _source_layout(
        row: BioacousticAsset, samples: int, rate: int, channels: int, bits: int
    ) -> None:
        if (row.sample_count, row.sample_rate_hz, row.channel_count, row.bits_per_sample) != (
            samples,
            rate,
            channels,
            bits,
        ):
            raise ConflictError("The WAV sample layout differs from its stored source record")

    def _latest(self, project_id: str, proposal_id: str) -> AudioReviewRead | None:
        row = self.session.scalar(
            select(BioacousticReview)
            .where(
                BioacousticReview.project_id == project_id,
                BioacousticReview.proposal_id == proposal_id,
            )
            .order_by(BioacousticReview.revision.desc())
            .limit(1)
        )
        return audio_review_read(row) if row else None

    def _proposal(self, project_id: str, asset_id: str, proposal_id: str) -> BioacousticProposal:
        self.asset(project_id, asset_id)
        row = self.session.get(BioacousticProposal, proposal_id)
        if row is None or (row.project_id, row.asset_id) != (project_id, asset_id):
            raise NotFoundError("Audio proposal was not found in this recording")
        return row

    def _proposals(self, project_id: str, asset_id: str) -> Select[BioacousticProposal]:
        return (
            select(BioacousticProposal)
            .where(
                BioacousticProposal.project_id == project_id,
                BioacousticProposal.asset_id == asset_id,
            )
            .order_by(BioacousticProposal.created_at, BioacousticProposal.id)
        )

    def proposals(
        self, project_id: str, asset_id: str, limit: int, offset: int
    ) -> AudioPage[AudioProposalRead]:
        self.asset(project_id, asset_id)
        rows, total = self._page(self._proposals(project_id, asset_id), limit, offset)
        return AudioPage(
            items=[audio_proposal_read(row, self._latest(project_id, row.id)) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def propose(
        self, project_id: str, asset_id: str, form: AudioProposalCreate
    ) -> AudioProposalRead:
        asset = self.asset(project_id, asset_id)
        if form.source_sha256 != asset.sha256:
            raise ConflictError("The proposed interval does not name the current original SHA-256")
        if form.end_sample > asset.sample_count or form.channel >= asset.channel_count:
            raise ValidationError(
                "The interval and zero-based channel must fall inside the original recording"
            )
        self.content(project_id, asset_id)
        _, total = self._page(self._proposals(project_id, asset_id), 0, 0)
        if total >= MAX_AUDIO_PROPOSALS:
            raise ValidationError(f"This recording already has {MAX_AUDIO_PROPOSALS} proposals")
        body = form.model_dump(mode="json")
        row = BioacousticProposal(
            project_id=project_id,
            asset_id=asset_id,
            proposal_json=body,
            proposal_sha256=canonical_json_sha256(body),
            author=get_local_user_identity(self.settings),
        )
        self._flush(row, "Audio proposals changed concurrently. Reload before retrying")
        return audio_proposal_read(row, None)

    def reviews(
        self, project_id: str, asset_id: str, proposal_id: str, limit: int, offset: int
    ) -> AudioPage[AudioReviewRead]:
        self._proposal(project_id, asset_id, proposal_id)
        query = (
            select(BioacousticReview)
            .where(
                BioacousticReview.project_id == project_id,
                BioacousticReview.proposal_id == proposal_id,
            )
            .order_by(BioacousticReview.revision)
        )
        rows, total = self._page(query, limit, offset)
        return AudioPage(
            items=[audio_review_read(row) for row in rows], total=total, limit=limit, offset=offset
        )

    def review(
        self, project_id: str, asset_id: str, proposal_id: str, form: AudioReviewCreate
    ) -> AudioReviewRead:
        self.content(project_id, asset_id)
        proposal = self._proposal(project_id, asset_id, proposal_id)
        latest = self._latest(project_id, proposal.id)
        audio_proposal_read(proposal, latest)
        if form.expected_revision != (latest.revision if latest else 0):
            raise ConflictError(
                "Audio review changed. Reload the attributed decisions before saving"
            )
        row = BioacousticReview(
            project_id=project_id,
            proposal_id=proposal.id,
            reviewer=get_local_user_identity(self.settings),
            decision=form.decision,
            reason=form.reason,
            revision=form.expected_revision + 1,
        )
        self._flush(row, "Audio review changed. Reload the attributed decisions before saving")
        return audio_review_read(row)

    def _anchors(self, project_id: str, asset_id: str) -> Select[BioacousticClockAnchor]:
        return (
            select(BioacousticClockAnchor)
            .where(
                BioacousticClockAnchor.project_id == project_id,
                BioacousticClockAnchor.asset_id == asset_id,
            )
            .order_by(BioacousticClockAnchor.created_at, BioacousticClockAnchor.id)
        )

    def anchors(
        self, project_id: str, asset_id: str, limit: int, offset: int
    ) -> AudioPage[AudioAnchorRead]:
        self.asset(project_id, asset_id)
        rows, total = self._page(self._anchors(project_id, asset_id), limit, offset)
        return AudioPage(
            items=[audio_anchor_read(row) for row in rows], total=total, limit=limit, offset=offset
        )

    def _video_duration(self, project_id: str, anchor: VideoAnchor) -> int | None:
        video = self.session.get(VideoAsset, str(anchor.video_id))
        if (
            video is None
            or video.project_id != project_id
            or video.sha256 != anchor.video_sha256
            or not isfinite(video.duration_seconds)
            or video.duration_seconds <= 0
        ):
            return None
        try:
            self._storage(project_id).verify(video.managed_path, video.sha256)
        except (ConflictError, OSError, ValidationError):
            return None
        return round(video.duration_seconds * 1_000_000)

    def anchor(self, project_id: str, asset_id: str, form: AudioAnchorCreate) -> AudioAnchorRead:
        asset = self.asset(project_id, asset_id)
        if form.source_sha256 != asset.sha256:
            raise ConflictError("The anchor does not name its original recording SHA-256")
        if form.sample >= asset.sample_count:
            raise ValidationError("Choose an anchor sample inside the source recording")
        self.content(project_id, asset_id)
        if isinstance(form, VideoAnchor):
            duration = self._video_duration(project_id, form)
            if duration is None or form.video_time_us > duration:
                raise ValidationError(
                    "Choose a verified video in this project and a time inside its source timeline"
                )
        body = form.model_dump(mode="json")
        digest = canonical_json_sha256(body)
        query = self._anchors(project_id, asset_id)
        existing = self.session.scalar(query.where(BioacousticClockAnchor.anchor_sha256 == digest))
        if existing is not None:
            return audio_anchor_read(existing)
        _, total = self._page(query, 0, 0)
        if total >= MAX_AUDIO_ANCHORS:
            raise ValidationError(
                f"This recording already has {MAX_AUDIO_ANCHORS} declared clock anchors"
            )
        row = BioacousticClockAnchor(
            project_id=project_id,
            asset_id=asset_id,
            anchor_json=body,
            anchor_sha256=digest,
            author=get_local_user_identity(self.settings),
        )
        self._flush(row, "Audio clock anchors changed concurrently. Reload before retrying")
        return audio_anchor_read(row)

    def reports(
        self, project_id: str, asset_id: str, limit: int, offset: int
    ) -> AudioPage[AudioReportRead]:
        self.asset(project_id, asset_id)
        rows, total = self._page(
            select(BioacousticReport)
            .where(
                BioacousticReport.project_id == project_id,
                BioacousticReport.asset_id == asset_id,
            )
            .order_by(BioacousticReport.created_at.desc(), BioacousticReport.id),
            limit,
            offset,
        )
        return AudioPage(
            items=[audio_report_read(row) for row in rows], total=total, limit=limit, offset=offset
        )

    def report(
        self, project_id: str, report_id: str, asset_id: str | None = None
    ) -> AudioReportRead:
        row = self.session.get(BioacousticReport, report_id)
        if (
            row is None
            or row.project_id != project_id
            or (asset_id is not None and row.asset_id != asset_id)
        ):
            raise NotFoundError("Bioacoustic report was not found in this project recording")
        self.content(project_id, row.asset_id)
        return audio_report_read(row)

    def freeze(self, project_id: str, asset_id: str, form: AudioReportCreate) -> AudioReportRead:
        asset = self.asset(project_id, asset_id)
        self.content(project_id, asset_id)
        anchors = [
            audio_anchor_read(row)
            for row in self.session.scalars(self._anchors(project_id, asset_id))
        ]
        selected = next((anchor for anchor in anchors if anchor.id == form.anchor_id), None)
        if form.anchor_id is not None and selected is None:
            raise NotFoundError("The selected clock anchor does not belong to this recording")
        conflicts = _clock_conflicts(selected, anchors, asset.sample_rate_hz)
        duration = (
            self._video_duration(project_id, selected)
            if isinstance(selected, VideoAnchor)
            else None
        )
        proposals = self.session.scalars(
            self._proposals(project_id, asset_id).limit(MAX_AUDIO_PROPOSALS + 1)
        ).all()
        if len(proposals) > MAX_AUDIO_PROPOSALS:
            raise ConflictError("The recording has too many proposals for a bounded report")
        entries = []
        for row in proposals:
            proof = audio_proposal_read(row, self._latest(project_id, row.id))
            entries.append(
                AudioReportEntry(
                    proposal=proof,
                    alignment=align_event(
                        proof,
                        selected,
                        asset.sample_rate_hz,
                        bool(conflicts),
                        duration,
                    ),
                )
            )
        snapshot = AudioReportSnapshot(
            source=audio_asset_read(asset),
            anchor=selected,
            clock_conflicts=conflicts,
            entries=entries,
        )
        body = snapshot.model_dump(mode="json")
        digest = canonical_json_sha256(body)
        saved = self.session.scalar(
            select(BioacousticReport).where(
                BioacousticReport.project_id == project_id,
                BioacousticReport.asset_id == asset_id,
                BioacousticReport.report_sha256 == digest,
            )
        )
        if saved is None:
            saved = BioacousticReport(
                project_id=project_id, asset_id=asset_id, snapshot_json=body, report_sha256=digest
            )
            self._flush(
                saved, "A concurrent report saved this evidence. Reload reports before retrying"
            )
        return audio_report_read(saved)
