"""Recompute paired organism-box reflectance on a reviewed hydrophone clock and footprint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    BioacousticReport,
    EcologyIdentityAnnotationEvidence,
    EcologyIdentityImageEvidence,
    EcologyIdentityRevision,
    ImageAsset,
    Project,
    SpectralIndex,
)
from reefvision.db.models.multimodal import MultimodalStudy
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.multimodal import classify_window, paired_difference
from reefvision.schemas.bioacoustics import AudioReportRead, UTCAnchorRead
from reefvision.schemas.multimodal import (
    Exposure,
    MultimodalOption,
    MultimodalRead,
    MultimodalRequest,
    MultimodalSummary,
)
from reefvision.schemas.reviewer_lab_v15 import ReviewerLabRole
from reefvision.services.bioacoustics import BioacousticsService
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.services.multispectral import MultispectralService
from reefvision.storage.datasets import canonical_json_sha256


def micros(offset: timedelta) -> int:
    return (offset.days * 86400 + offset.seconds) * 1000000 + offset.microseconds


def audio_evidence(report: AudioReportRead) -> dict[str, Any]:
    snap = report.snapshot
    source = snap.source
    anchor = snap.anchor
    # Archive import rebinds local row UUIDs. These source-coordinate facts are immutable.
    return {
        "source_sha256": source.sha256,
        "file": source.original_filename,
        "sample_rate_hz": source.sample_rate_hz,
        "sample_count": source.sample_count,
        "channel_count": source.channel_count,
        "anchor": None
        if anchor is None
        else {
            "kind": anchor.kind,
            "sample": anchor.sample,
            "utc": anchor.utc.astimezone(UTC).isoformat()
            if isinstance(anchor, UTCAnchorRead)
            else None,
            "uncertainty_us": anchor.uncertainty_us,
            "evidence": anchor.evidence,
        },
        "clock_conflict": bool(snap.clock_conflicts),
        "entries": [
            {
                "start_sample": e.proposal.start_sample,
                "end_sample": e.proposal.end_sample,
                "label": e.proposal.label,
                "channel": e.proposal.channel,
                "status": e.proposal.status,
                "review_revision": e.proposal.review_revision,
                "reviewer": e.proposal.latest_review.reviewer if e.proposal.latest_review else None,
                "review_reason": e.proposal.latest_review.reason
                if e.proposal.latest_review
                else None,
                "alignment": e.alignment.model_dump(mode="json"),
            }
            for e in snap.entries
        ],
    }


def freeze_box(session: Session, project: str, exposure: Exposure) -> dict[str, Any]:
    link = session.get(EcologyIdentityAnnotationEvidence, str(exposure.annotation_evidence_id))
    if link is None or link.project_id != project or link.annotation_kind != "box":
        raise ValidationError("Select a reviewed organism box from the current project")
    image = session.get(EcologyIdentityImageEvidence, link.image_evidence_id)
    box = session.get(Annotation, link.annotation_id)
    if image is None or image.project_id != project or box is None:
        raise ValidationError("The reviewed organism evidence is incomplete")
    actual = EcologyIdentityService(session)._annotation_source("box", box.id, image.image_id)
    if actual != (link.annotation_revision, link.annotation_sha256):
        raise ConflictError("The selected organism box changed after its ecological review")
    identity = session.scalar(
        select(EcologyIdentityRevision).where(
            EcologyIdentityRevision.project_id == project,
            EcologyIdentityRevision.organism_key == image.organism_key,
            EcologyIdentityRevision.revision == image.identity_revision,
        )
    )
    if identity is None:
        raise ValidationError("The pinned organism revision is missing")
    asset = session.get(ImageAsset, image.image_id)
    if asset is None or asset.project_id != project or asset.sha256 != image.image_sha256:
        raise ConflictError("The original ecological image differs from the reviewed link")
    capture = asset.capture_timestamp
    explicit = EcologyIdentityService._explicit_capture_fingerprint(asset)
    fingerprints = {EcologyIdentityService._source_metadata_fingerprint(asset)}
    if explicit is not None:
        capture, recovered_fingerprint = explicit
        fingerprints.add(recovered_fingerprint)
    if image.source_metadata_sha256 and image.source_metadata_sha256 not in fingerprints:
        raise ConflictError(
            "The registered image geometry or acquisition time changed after review"
        )
    capture_utc = (
        capture.astimezone(UTC).isoformat() if capture and capture.utcoffset() is not None else None
    )
    return {
        "capture_utc": capture_utc,
        "link_id": link.id,
        "image_link_id": image.id,
        "image_id": image.image_id,
        "image_sha256": image.image_sha256,
        "organism_key": identity.organism_key,
        "organism_revision": identity.revision,
        "organism_revision_id": identity.id,
        "annotation_id": box.id,
        "annotation_revision": link.annotation_revision,
        "annotation_sha256": link.annotation_sha256,
        "bounds_xyxy": [box.x_min, box.y_min, box.x_max, box.y_max],
    }


def options(
    session: Session, project: str, kind: str, limit: int, offset: int
) -> list[MultimodalOption]:
    if kind == "audio":
        audio = session.scalars(
            select(BioacousticReport)
            .where(BioacousticReport.project_id == project)
            .order_by(BioacousticReport.created_at.desc(), BioacousticReport.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            MultimodalOption(
                id=UUID(a.id),
                label=a.snapshot_json["source"]["original_filename"] + " · " + a.report_sha256[:10],
                digest=a.report_sha256,
            )
            for a in audio
        ]
    if kind == "index":
        index = session.scalars(
            select(SpectralIndex)
            .where(SpectralIndex.project_id == project)
            .order_by(SpectralIndex.created_at.desc(), SpectralIndex.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            MultimodalOption(
                id=UUID(i.id),
                label=(
                    i.snapshot_json["acquisition"]["label"]
                    + " · image "
                    + i.snapshot_json["acquisition"]["bands"][0]["original_sha256"][:10]
                    + " · index "
                    + i.content_sha256[:10]
                ),
                digest=i.content_sha256,
            )
            for i in index
        ]
    links = session.execute(
        select(EcologyIdentityAnnotationEvidence, EcologyIdentityImageEvidence)
        .join(
            EcologyIdentityImageEvidence,
            EcologyIdentityAnnotationEvidence.image_evidence_id == EcologyIdentityImageEvidence.id,
        )
        .where(
            EcologyIdentityAnnotationEvidence.project_id == project,
            EcologyIdentityAnnotationEvidence.annotation_kind == "box",
        )
        .order_by(
            EcologyIdentityAnnotationEvidence.created_at.desc(),
            EcologyIdentityAnnotationEvidence.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return [
        MultimodalOption(
            id=UUID(link.id),
            label=(
                f"{image.organism_key} · image {image.image_sha256[:10]}"
                f" · box {link.annotation_sha256[:10]}"
            ),
            digest=link.annotation_sha256,
        )
        for link, image in links
    ]


def calculate(
    session: Session,
    settings: Settings,
    project: str,
    req: MultimodalRequest,
    boxes: list[dict[str, Any]],
    audio: dict[str, Any],
    bindings: dict[str, str],
) -> dict[str, Any]:
    reasons = []
    if not req.full_recording_reviewed:
        reasons.append(
            "The complete recording has no confirmed review coverage for this label and channel."
        )
    if audio["clock_conflict"] or not audio["anchor"] or audio["anchor"]["kind"] != "utc":
        reasons.append("A consistent UTC anchor is required for the hydrophone.")
    if req.channel >= audio["channel_count"]:
        reasons.append("The selected acoustic channel is absent.")
    if (
        req.identity_review != "same organism"
        or len({(b["organism_key"], b["organism_revision"]) for b in boxes}) != 1
    ):
        reasons.append("The two observations do not have a common reviewed organism revision.")
    a, b = req.exposures
    pair_uncertainty = a.uncertainty_us + b.uncertainty_us
    if (
        micros(a.start_utc - b.end_utc) < pair_uncertainty
        and micros(b.start_utc - a.end_utc) < pair_uncertainty
    ):
        reasons.append("The uncertainty intervals of the two exposures overlap.")
    rows = []
    channels = []
    optical_sources = []
    rate = audio["sample_rate_hz"]
    entries = [
        e for e in audio["entries"] if e["label"] == req.event_label and e["channel"] == req.channel
    ]
    for exposure, box in zip(req.exposures, boxes, strict=True):
        local_id = bindings.get(str(exposure.index_id), str(exposure.index_id))
        spectral, samples = MultispectralService(session, settings).replay(
            project, local_id, exposure.index_sha256
        )
        snapshot = spectral.snapshot
        acq = snapshot.acquisition
        source = acq.bands[0]
        optical_sources.append(
            {
                "acquisition_sha256": snapshot.selection.acquisition_sha256,
                "sensor": acq.sensor,
                "alignment": None
                if acq.alignment is None
                else acq.alignment.model_dump(mode="json"),
                "method": snapshot.method,
                "valid_mask_sha256": snapshot.result.mask_sha256,
                "float32_le_sha256": snapshot.result.float32_le_sha256,
                "bands": [
                    {
                        "role": role,
                        **acq.bands[position].model_dump(mode="json", exclude={"image_id"}),
                    }
                    for role, position in (
                        ("positive", snapshot.selection.positive),
                        ("negative", snapshot.selection.negative),
                    )
                ],
            }
        )
        channels.append(
            [
                (acq.bands[k].wavelength_nm, acq.bands[k].bandwidth_nm)
                for k in (snapshot.selection.positive, snapshot.selection.negative)
            ]
        )
        x0, y0, x1, y1 = box["bounds_xyxy"]
        dx, dy = exposure.station_grid_offset_xy
        f0, f1, f2, f3 = req.footprint.bounds_xyxy
        if box.get("capture_utc"):
            captured = datetime.fromisoformat(box["capture_utc"])
            if not (
                -exposure.uncertainty_us <= micros(captured - exposure.start_utc)
                and micros(captured - exposure.end_utc) <= exposure.uncertainty_us
            ):
                reasons.append(
                    "The recorded acquisition time conflicts with the reviewed exposure."
                )
        alignment = acq.alignment
        grid_error = (
            None
            if alignment is None
            else alignment.maximum_residual_px + req.footprint.registration_error_px
        )
        if source.original_sha256 != box["image_sha256"]:
            reasons.append("The organism box belongs to a different reference-band original.")
        if alignment is None or alignment.grid != req.footprint.grid:
            reasons.append("The signed hydrophone footprint and optical reference grid differ.")
        if grid_error is None or grid_error > req.footprint.maximum_total_error_px:
            reasons.append("Spatial registration uncertainty exceeds the declared tolerance.")
        elif not (
            f0 + grid_error <= x0 + dx < x1 + dx <= f2 - grid_error
            and f1 + grid_error <= y0 + dy < y1 + dy <= f3 - grid_error
        ):
            reasons.append(
                "The organism box falls outside the certain interior of the signed footprint."
            )
        count = 0
        mean = None
        if samples is None:
            reasons.extend(snapshot.result.reasons)
        elif source.original_sha256 == box["image_sha256"]:
            ix0, iy0, ix1, iy1 = [ceil(v - 0.5) for v in (x0, y0, x1, y1)]
            cut = samples[
                max(iy0, 0) : min(iy1, source.height), max(ix0, 0) : min(ix1, source.width)
            ]
            finite = cut[np.isfinite(cut)]
            count = int(finite.size)
            if count:
                mean = float(np.mean(finite, dtype=np.float64))
            else:
                reasons.append("The reviewed box has no valid calibrated pixel centers.")
        state = "unresolved clock"
        anchor = audio["anchor"]
        if anchor and anchor["kind"] == "utc" and not audio["clock_conflict"]:
            zero = datetime.fromisoformat(anchor["utc"])
            uncertainty = anchor["uncertainty_us"] + exposure.uncertainty_us
            if uncertainty > req.maximum_time_uncertainty_us:
                reasons.append("Combined clock uncertainty exceeds the declared tolerance.")
            # Scaling the clock by Hz preserves fractional-microsecond sample boundaries.
            start = micros(exposure.start_utc - zero) * rate + anchor["sample"] * 1000000
            end = micros(exposure.end_utc - zero) * rate + anchor["sample"] * 1000000
            events = [
                (e["start_sample"] * 1000000, e["end_sample"] * 1000000, e["status"])
                for e in entries
            ]
            state = classify_window(
                (start, end), events, uncertainty * rate, audio["sample_count"] * 1000000
            )
        rows.append(
            {
                "exposure": state,
                "valid_pixels": count,
                "roi_mean": mean,
                "grid_error_px": grid_error,
                "index_sha256": spectral.content_sha256,
                "source_band_sha256": source.original_sha256,
                "unit": "dimensionless normalized reflectance difference",
            }
        )
    if rows[0]["source_band_sha256"] == rows[1]["source_band_sha256"]:
        reasons.append("The visits require two distinct reference-band originals.")
    if channels[0] != channels[1]:
        reasons.append(
            "The optical observations use different wavelength or bandwidth definitions."
        )
    contrast = paired_difference(rows)
    if contrast is None:
        reasons.append(
            "One exposed observation and one reviewed outside-event observation are required."
        )
    reasons = list(dict.fromkeys(reasons))
    return {
        "method": "paired-acoustic-spectral-roi-v1",
        "status": "withheld" if reasons else "available",
        "reasons": reasons,
        "observations": rows,
        "optical_sources": optical_sources,
        "exposed_minus_control": None if reasons else contrast,
        "unit": "dimensionless normalized reflectance difference",
        "interpretation": (
            "A within-organism descriptive difference at the surveyed station "
            "during these exposures."
        ),
    }


def summary(row: MultimodalStudy) -> MultimodalSummary:
    return MultimodalSummary(
        id=UUID(row.id),
        name=row.name,
        content_sha256=row.content_sha256,
        status=row.snapshot_json["result"]["status"],
        created_at=row.created_at,
    )


def find_study(session: Session, project: str, identifier: str) -> MultimodalStudy:
    row = session.get(MultimodalStudy, identifier)
    if row is None or row.project_id != project:
        raise NotFoundError("Multimodal study was not found in the current project")
    if canonical_json_sha256(row.snapshot_json) != row.content_sha256:
        raise ConflictError("The saved multimodal study digest differs")
    return row


def read(row: MultimodalStudy) -> MultimodalRead:
    return MultimodalRead(**summary(row).model_dump(), snapshot=row.snapshot_json)


def freeze(
    session: Session,
    settings: Settings,
    project: str,
    req: MultimodalRequest,
    actor: ReviewerLabRole,
) -> MultimodalRead:
    if actor.role not in {"reviewer", "adjudicator"}:
        raise ValidationError("The survey alignment requires an active reviewer or adjudicator")
    payload = req.model_dump(mode="json")
    digest = canonical_json_sha256(payload)
    prior = session.scalar(
        select(MultimodalStudy).where(
            MultimodalStudy.project_id == project,
            MultimodalStudy.operation_id == str(req.operation_id),
        )
    )
    if prior:
        if prior.request_sha256 != digest or prior.role_revision_id != actor.id:
            raise ConflictError("The multimodal operation already has different inputs or reviewer")
        return read(find_study(session, project, prior.id))
    report = BioacousticsService(session, settings).report(project, str(req.audio_report_id))
    if report.report_sha256 != req.audio_report_sha256:
        raise ConflictError("The selected audio report differs from the pinned digest")
    audio = audio_evidence(report)
    boxes = [freeze_box(session, project, exp) for exp in req.exposures]
    result = calculate(session, settings, project, req, boxes, audio, {})
    snapshot = {
        "version": "reefvision-multimodal-study-1",
        "request": payload,
        "reviewer": actor.model_dump(mode="json"),
        "boxes": boxes,
        "audio": audio,
        "result": result,
    }
    session.execute(update(Project).where(Project.id == project).values(id=Project.id))
    prior = session.scalar(
        select(MultimodalStudy).where(
            MultimodalStudy.project_id == project,
            MultimodalStudy.operation_id == str(req.operation_id),
        )
    )
    if prior:
        if prior.request_sha256 != digest or prior.role_revision_id != actor.id:
            raise ConflictError("Concurrent multimodal submission has different inputs or reviewer")
        return read(find_study(session, project, prior.id))
    row = MultimodalStudy(
        project_id=project,
        operation_id=str(req.operation_id),
        name=req.name,
        audio_report_id=str(report.id),
        role_revision_id=actor.id,
        request_sha256=digest,
        content_sha256=canonical_json_sha256(snapshot),
        snapshot_json=snapshot,
    )
    session.add(row)
    session.commit()
    return read(row)


def replay(
    session: Session, settings: Settings, project: str, row: MultimodalStudy, expected: str
) -> dict[str, Any]:
    if row.content_sha256 != expected:
        raise ConflictError("The selected multimodal study differs from its pinned digest")
    snap = row.snapshot_json
    req = MultimodalRequest.model_validate(snap["request"])
    report = BioacousticsService(session, settings).report(project, row.audio_report_id)
    audio = audio_evidence(report)
    if audio != snap["audio"]:
        raise ConflictError("The original acoustic clock, event or reviewed coverage differs")
    outcome = calculate(
        session, settings, project, req, snap["boxes"], audio, row.source_id_map_json
    )
    if "optical_sources" not in snap["result"]:
        outcome.pop("optical_sources")
    if outcome != snap["result"]:
        raise ConflictError("Recomputed multimodal evidence differs from the frozen study")
    return {
        "study_id": row.id,
        "study_sha256": row.content_sha256,
        "result": outcome,
        "replayed": True,
        "download_url": f"/projects/{project}/multimodal/studies/{row.id}/export",
    }
