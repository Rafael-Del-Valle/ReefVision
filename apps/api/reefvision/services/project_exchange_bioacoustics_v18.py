"""Authenticate and rebind portable bioacoustic originals and frozen reports."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from math import isfinite
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import UUID
from zipfile import BadZipFile, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models.bioacoustics import (
    BioacousticAsset,
    BioacousticClockAnchor,
    BioacousticProposal,
    BioacousticReport,
    BioacousticReview,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.bioacoustics import (
    AUDIO_ANCHOR,
    AUDIO_ANCHOR_READ,
    MAX_AUDIO_ANCHORS,
    MAX_AUDIO_PROPOSALS,
    AudioAnchorRead,
    AudioAssetRead,
    AudioProposalCreate,
    AudioProposalRead,
    AudioReportRead,
    AudioReportSnapshot,
    AudioReviewRead,
    VideoAnchor,
)
from reefvision.services.bioacoustics import _clock_conflicts, align_event, utc
from reefvision.services.workflow_bioacoustics import NODE
from reefvision.storage.bioacoustics import (
    PCM,
    AudioStorage,
    audio_filename,
    audio_managed_path,
    inspect_wav,
    inspect_wav_stream,
)
from reefvision.storage.datasets import canonical_json_sha256

AUDIO_MEDIA_KIND = "bioacoustic_source"
AUDIO_ORIGIN = "bioacoustic_report_origins"
AUDIO_SECTION_MODELS: dict[str, type[Base]] = {
    "bioacoustic_assets": BioacousticAsset,
    "bioacoustic_clock_anchors": BioacousticClockAnchor,
    "bioacoustic_proposals": BioacousticProposal,
    "bioacoustic_reviews": BioacousticReview,
    "bioacoustic_reports": BioacousticReport,
}
ASSETS, ANCHORS, PROPOSALS, REVIEWS, REPORTS = AUDIO_SECTION_MODELS
Sections = Mapping[str, Sequence[dict[str, Any]]]


def has_audio_assets(session: Session, project_id: str) -> bool:
    return (
        session.scalar(
            select(BioacousticAsset.id).where(BioacousticAsset.project_id == project_id).limit(1)
        )
        is not None
    )


def audio_exchange_records(session: Session, project_id: str) -> dict[str, Sequence[Base]]:
    if not has_audio_assets(session, project_id):
        return {}
    return {
        ASSETS: list(
            session.scalars(
                select(BioacousticAsset).where(BioacousticAsset.project_id == project_id)
            )
        ),
        ANCHORS: list(
            session.scalars(
                select(BioacousticClockAnchor).where(
                    BioacousticClockAnchor.project_id == project_id
                )
            )
        ),
        PROPOSALS: list(
            session.scalars(
                select(BioacousticProposal).where(BioacousticProposal.project_id == project_id)
            )
        ),
        REVIEWS: list(
            session.scalars(
                select(BioacousticReview).where(BioacousticReview.project_id == project_id)
            )
        ),
        REPORTS: list(
            session.scalars(
                select(BioacousticReport).where(BioacousticReport.project_id == project_id)
            )
        ),
    }


def audio_owned_project_path(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path.replace("\\", "/")).parts
    return bool(parts) and parts[0].rstrip(" .").casefold() == "bioacoustics"


def _member(asset_id: str) -> str:
    return f"media/audio/{asset_id}.wav"


def _descriptor(asset_id: str, digest: str, size: int) -> dict[str, Any]:
    return {
        "kind": AUDIO_MEDIA_KIND,
        "record_id": asset_id,
        "path": _member(asset_id),
        "sha256": digest,
        "size_bytes": size,
    }


def _layout(asset: AudioAssetRead | BioacousticAsset, pcm: PCM) -> None:
    if (asset.sample_count, asset.sample_rate_hz, asset.channel_count, asset.bits_per_sample) != (
        pcm.sample_count,
        pcm.sample_rate_hz,
        pcm.channel_count,
        pcm.bits_per_sample,
    ):
        raise ValueError("Audio source metadata differs from its original PCM frames")


def gather_audio_media(
    settings: Settings,
    storage_root: str,
    assets: Sequence[BioacousticAsset],
) -> list[tuple[dict[str, object], Path]]:
    storage = AudioStorage(settings, storage_root)
    media = []
    for asset in assets:
        if asset.managed_path != audio_managed_path(storage_root, asset.sha256):
            raise ValidationError("Audio original is outside its designated content-addressed path")
        path = storage.verify(asset.managed_path, asset.sha256, asset.size_bytes)
        try:
            _layout(asset, inspect_wav(path, asset.size_bytes))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        media.append((_descriptor(asset.id, asset.sha256, asset.size_bytes), path))
    return media


def restore_audio_media(
    settings: Settings,
    target_storage_root: str,
    archive: ZipFile,
    descriptor: Mapping[str, Any],
) -> str:
    storage = AudioStorage(settings, target_storage_root)
    with (
        archive.open(descriptor["path"]) as source,
        storage.stage(source) as (stage, digest, size, _),
    ):
        if digest != descriptor["sha256"] or size != descriptor["size_bytes"]:
            raise ValidationError("Audio original changed while restoring the verified archive")
        return storage.publish(stage, digest, size)


def contains_audio_exchange_records(sections: Sections) -> bool:
    return (
        any(sections.get(name) for name in AUDIO_SECTION_MODELS)
        or any(row.get("data_type") == NODE for row in sections.get("workflow_artifacts", ()))
        or any(row.get("node_type") == NODE for row in sections.get("workflow_node_runs", ()))
        or any(
            node.get("node_type") == NODE
            for row in sections.get("workflow_graphs", ())
            for node in row.get("graph_json", {}).get("nodes", ())
        )
    )


def _key(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Audio record identity must be a canonical UUID")
    return value


def _source_time(value: Any) -> datetime:
    return utc(value if isinstance(value, datetime) else datetime.fromisoformat(value))


def _owned(sections: Sections, name: str, project_id: str) -> dict[str, dict[str, Any]]:
    result = {}
    for row in sections.get(name, ()):
        identity = _key(row["id"])
        if row["project_id"] != project_id or identity in result:
            raise ValueError("Audio evidence has repeated identity or foreign project ownership")
        result[identity] = row
    return result


def _asset_response(row: Mapping[str, Any]) -> AudioAssetRead:
    return AudioAssetRead.model_validate(
        {
            **{key: row[key] for key in AudioAssetRead.model_fields},
            "created_at": _source_time(row["created_at"]),
        }
    )


def _verify_media(
    assets: Mapping[str, AudioAssetRead],
    media: Sequence[Mapping[str, Any]],
    archive: ZipFile,
) -> None:
    descriptors = [item for item in media if item.get("kind") == AUDIO_MEDIA_KIND]
    by_asset = {item["record_id"]: item for item in descriptors}
    if set(by_asset) != set(assets) or len(by_asset) != len(descriptors):
        raise ValueError("Each bioacoustic recording requires its one original media member")
    for key, asset in assets.items():
        expected = _descriptor(key, asset.sha256, asset.size_bytes)
        if dict(by_asset[key]) != expected:
            raise ValueError("Audio media descriptor does not match its owning original")
        member = archive.getinfo(expected["path"])
        if member.file_size != asset.size_bytes:
            raise ValueError("Audio media member differs from its declared size")
        digest = hashlib.sha256()
        with archive.open(member) as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != asset.sha256:
            raise ValueError("Audio media bytes do not match their recorded SHA-256")
        with archive.open(member) as source:
            _layout(asset, inspect_wav_stream(source, asset.size_bytes))


def _check_interval(proposal: AudioProposalCreate, asset: AudioAssetRead) -> None:
    if (
        proposal.source_sha256 != asset.sha256
        or proposal.end_sample > asset.sample_count
        or proposal.channel >= asset.channel_count
    ):
        raise ValueError(
            "Audio proposal interval does not belong to its original channel and sample range"
        )


def _archive_anchors(
    rows: Mapping[str, dict[str, Any]],
    assets: Mapping[str, AudioAssetRead],
    videos: Mapping[str, dict[str, Any]],
    video_members: set[str],
) -> tuple[dict[str, AudioAnchorRead], dict[str, int]]:
    anchors: dict[str, AudioAnchorRead] = {}
    durations: dict[str, int] = {}
    counts: dict[str, int] = {}
    for key, row in rows.items():
        asset_id = row["asset_id"]
        asset = assets[asset_id]
        source = AUDIO_ANCHOR.validate_python(row["anchor_json"])
        if (
            source.source_sha256 != asset.sha256
            or source.sample >= asset.sample_count
            or canonical_json_sha256(source.model_dump(mode="json")) != row["anchor_sha256"]
        ):
            raise ValueError("Audio clock evidence does not match its original recording")
        if isinstance(source, VideoAnchor):
            video = videos[str(source.video_id)]
            length = video["duration_seconds"]
            if (
                video["project_id"] != row["project_id"]
                or video["id"] not in video_members
                or video["sha256"] != source.video_sha256
                or not isfinite(length)
                or length <= 0
            ):
                raise ValueError(
                    "Audio reference video is missing, modified, or outside its project"
                )
            duration = round(length * 1_000_000)
            if source.video_time_us > duration:
                raise ValueError("Audio clock anchor exceeds the pinned video duration")
            durations[key] = duration
        anchors[key] = AUDIO_ANCHOR_READ.validate_python(
            {
                **source.model_dump(),
                "id": key,
                "asset_id": asset_id,
                "project_id": row["project_id"],
                "anchor_sha256": row["anchor_sha256"],
                "author": row["author"],
                "created_at": _source_time(row["created_at"]),
            }
        )
        counts[asset_id] = counts.get(asset_id, 0) + 1
        if counts[asset_id] > MAX_AUDIO_ANCHORS:
            raise ValueError("Audio recording exceeded the clock-anchor bound")
    return anchors, durations


def _archive_reviews(
    rows: Mapping[str, dict[str, Any]], proposals: Mapping[str, dict[str, Any]]
) -> dict[str, AudioReviewRead]:
    reviews: dict[str, AudioReviewRead] = {}
    revisions: dict[str, list[int]] = {}
    for key, row in rows.items():
        review = AudioReviewRead.model_validate(
            {**row, "reviewed_at": _source_time(row["reviewed_at"])}
        )
        if str(review.proposal_id) not in proposals:
            raise ValueError("Audio review has no original source proposal")
        revisions.setdefault(str(review.proposal_id), []).append(review.revision)
        reviews[key] = review
    if any(sorted(items) != list(range(1, len(items) + 1)) for items in revisions.values()):
        raise ValueError("Audio review history must retain every original revision")
    return reviews


def _proposal_response(row: Mapping[str, Any], review: AudioReviewRead | None) -> AudioProposalRead:
    return AudioProposalRead.model_validate(
        {
            **row["proposal_json"],
            "id": row["id"],
            "asset_id": row["asset_id"],
            "project_id": row["project_id"],
            "proposal_sha256": row["proposal_sha256"],
            "created_at": _source_time(row["created_at"]),
            "author": row["author"],
            "status": review.decision if review else "proposed",
            "review_revision": review.revision if review else 0,
            "latest_review": review,
        }
    )


def _verify_reports(
    rows: Mapping[str, dict[str, Any]],
    assets: Mapping[str, AudioAssetRead],
    anchors: Mapping[str, AudioAnchorRead],
    durations: Mapping[str, int],
    proposals: Mapping[str, dict[str, Any]],
    reviews: Mapping[str, AudioReviewRead],
) -> dict[str, dict[str, Any]]:
    reports = {}
    for key, row in rows.items():
        asset = assets[row["asset_id"]]
        snapshot = AudioReportSnapshot.model_validate(row["snapshot_json"])
        selected = snapshot.anchor
        if (
            snapshot.source != asset
            or canonical_json_sha256(snapshot.model_dump(mode="json")) != row["report_sha256"]
        ):
            raise ValueError("Frozen audio report differs from its verified original or checksum")
        sources = [anchors[str(candidate)] for candidate in snapshot.clock_conflicts]
        if (
            (selected and (selected.asset_id != asset.id or anchors[str(selected.id)] != selected))
            or any(source.asset_id != asset.id for source in sources)
            or _clock_conflicts(selected, sources, asset.sample_rate_hz) != snapshot.clock_conflicts
        ):
            raise ValueError("Frozen audio report has incompatible or unverified clock sources")
        seen: set[UUID] = set()
        for entry in snapshot.entries:
            proposal = entry.proposal
            source_proposal = proposals[str(proposal.id)]
            review = (
                reviews[str(proposal.latest_review.id)]
                if proposal.latest_review is not None
                else None
            )
            expected = _proposal_response(source_proposal, review)
            if (
                proposal.id in seen
                or proposal.asset_id != asset.id
                or proposal != expected
                or (review is not None and review.proposal_id != proposal.id)
            ):
                raise ValueError("Frozen audio report uses an altered or unrelated proposal review")
            seen.add(proposal.id)
            alignment = align_event(
                proposal,
                selected,
                asset.sample_rate_hz,
                bool(sources),
                durations.get(str(selected.id)) if selected else None,
            )
            if entry.alignment != alignment:
                raise ValueError(
                    "Frozen audio report alignment differs from its typed source evidence"
                )
        reports[key] = AudioReportRead.model_validate(
            {
                "id": key,
                "asset_id": row["asset_id"],
                "project_id": row["project_id"],
                "snapshot": snapshot,
                "report_sha256": row["report_sha256"],
                "created_at": _source_time(row["created_at"]),
            }
        ).model_dump(mode="json")
    return reports


def _verify_pin(parameters: Mapping[str, Any], reports: Mapping[str, dict[str, Any]]) -> str:
    identifier = _key(parameters["report_id"])
    if parameters["report_sha256"] != reports[identifier]["report_sha256"]:
        raise ValueError("A bioacoustic workflow pin does not identify a valid frozen report")
    return identifier


def _verify_workflows(sections: Sections, reports: Mapping[str, dict[str, Any]]) -> None:
    runs: dict[str, tuple[str, str]] = {}
    for row in sections.get("workflow_graphs", ()):
        for node in row["graph_json"]["nodes"]:
            if node.get("node_type") == NODE:
                _verify_pin(node["parameters"], reports)
    for row in sections.get("workflow_node_runs", ()):
        if row.get("node_type") == NODE:
            runs[row["id"]] = (_verify_pin(row["parameters_json"], reports), row["workflow_run_id"])
    for row in sections.get("workflow_artifacts", ()):
        if row.get("data_type") != NODE:
            continue
        identifier, workflow_run = runs[row["producer_node_run_id"]]
        payload = row["payload_json"]
        if (
            row["workflow_run_id"] != workflow_run
            or row["producer_port_id"] != "report"
            or payload != reports[identifier]
            or canonical_json_sha256(payload) != row["payload_sha256"]
        ):
            raise ValueError(
                "Bioacoustic workflow output does not match its verified frozen report and producer"
            )


def validate_audio_exchange(
    project_id: str,
    source_storage_root: str,
    sections: Sections,
    media: Sequence[Mapping[str, Any]],
    archive: ZipFile,
) -> None:
    if not contains_audio_exchange_records(sections) and not any(
        item.get("kind") == AUDIO_MEDIA_KIND for item in media
    ):
        return
    try:
        root = PurePosixPath(source_storage_root)
        if (
            not root.parts
            or root.is_absolute()
            or PureWindowsPath(source_storage_root).drive
            or ".." in root.parts
            or root.as_posix() != source_storage_root
        ):
            raise ValueError("Audio project storage root is invalid")
        raw_assets = _owned(sections, ASSETS, project_id)
        assets = {key: _asset_response(row) for key, row in raw_assets.items()}
        if len({asset.sha256 for asset in assets.values()}) != len(assets):
            raise ValueError("Audio originals cannot repeat the same project source bytes")
        for key, asset in assets.items():
            if audio_filename(asset.original_filename) != asset.original_filename or raw_assets[
                key
            ]["managed_path"] != audio_managed_path(source_storage_root, asset.sha256):
                raise ValueError("Audio file name or original path is invalid")
        _verify_media(assets, media, archive)
        videos = {row["id"]: row for row in sections.get("videos", ())}
        video_members = {item["record_id"] for item in media if item.get("kind") == "video"}
        anchors, durations = _archive_anchors(
            _owned(sections, ANCHORS, project_id), assets, videos, video_members
        )
        proposals = _owned(sections, PROPOSALS, project_id)
        counts: dict[str, int] = {}
        for row in proposals.values():
            record = AudioProposalCreate.model_validate(row["proposal_json"])
            _check_interval(record, assets[row["asset_id"]])
            if canonical_json_sha256(record.model_dump(mode="json")) != row["proposal_sha256"]:
                raise ValueError("Audio proposal checksum does not match its source annotation")
            counts[row["asset_id"]] = counts.get(row["asset_id"], 0) + 1
            if counts[row["asset_id"]] > MAX_AUDIO_PROPOSALS:
                raise ValueError("Audio recording exceeded the source proposal bound")
        reviews = _archive_reviews(_owned(sections, REVIEWS, project_id), proposals)
        reports = _verify_reports(
            _owned(sections, REPORTS, project_id), assets, anchors, durations, proposals, reviews
        )
        _verify_workflows(sections, reports)
    except (AttributeError, KeyError, OSError, TypeError, ValueError, BadZipFile) as exc:
        raise ValidationError(f"Bioacoustic archive evidence is invalid: {exc}") from exc


def _anchor_params(body: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("kind", "sample", "source_sha256", "uncertainty_us", "evidence")
    reference = ("utc",) if body["kind"] == "utc" else ("video_id", "video_sha256", "video_time_us")
    return {key: body[key] for key in (*keys, *reference)}


def _replace(row: dict[str, Any], mapping: Mapping[str, str], *keys: str) -> None:
    for key in keys:
        row[key] = mapping[row[key]]


def _remap_snapshot(source: dict[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    snapshot = deepcopy(source)
    _replace(snapshot["source"], mapping, "id", "project_id")
    anchor = snapshot["anchor"]
    if anchor is not None:
        _replace(anchor, mapping, "id", "asset_id", "project_id")
        if anchor["kind"] == "video":
            _replace(anchor, mapping, "video_id")
        anchor["anchor_sha256"] = canonical_json_sha256(_anchor_params(anchor))
    snapshot["clock_conflicts"] = [
        mapping[identifier] for identifier in snapshot["clock_conflicts"]
    ]
    for entry in snapshot["entries"]:
        proposal = entry["proposal"]
        _replace(proposal, mapping, "id", "asset_id", "project_id")
        review = proposal["latest_review"]
        if review is not None:
            _replace(review, mapping, "id", "proposal_id", "project_id")
    return snapshot


def _snapshot_references(snapshot: dict[str, Any]) -> set[str]:
    source = snapshot["source"]
    output = {source["id"], source["project_id"], *snapshot["clock_conflicts"]}
    if (anchor := snapshot["anchor"]) is not None:
        output.update(anchor[key] for key in ("id", "project_id", "asset_id"))
        if anchor["kind"] == "video":
            output.add(anchor["video_id"])
    for entry in snapshot["entries"]:
        proposal = entry["proposal"]
        output.update(proposal[key] for key in ("id", "project_id", "asset_id"))
        if (review := proposal["latest_review"]) is not None:
            output.update(review[key] for key in ("id", "project_id", "proposal_id"))
    return output


def restore_audio_row(
    section_name: str,
    source_row: dict[str, Any],
    values: dict[str, Any],
    id_map: Mapping[str, str],
    digests: dict[str, str],
) -> None:
    literals = {
        ASSETS: ("original_asset_id", "original_project_id", "original_filename"),
        PROPOSALS: ("proposal_json", "author"),
        ANCHORS: ("author",),
        REVIEWS: ("reviewer", "reason", "decision"),
    }
    for key in literals.get(section_name, ()):
        values[key] = deepcopy(source_row[key])
    if section_name == ANCHORS:
        anchor = deepcopy(source_row["anchor_json"])
        if anchor["kind"] == "video":
            _replace(anchor, id_map, "video_id")
        values["anchor_json"] = anchor
        values["anchor_sha256"] = canonical_json_sha256(anchor)
        digests[source_row["anchor_sha256"]] = values["anchor_sha256"]
    elif section_name == REPORTS:
        snapshot = _remap_snapshot(source_row["snapshot_json"], id_map)
        values["snapshot_json"] = snapshot
        values["report_sha256"] = canonical_json_sha256(snapshot)
        digests[source_row["report_sha256"]] = values["report_sha256"]
    elif section_name == "workflow_artifacts" and source_row.get("data_type") == NODE:
        payload = deepcopy(source_row["payload_json"])
        _replace(payload, id_map, "id", "asset_id", "project_id")
        payload["snapshot"] = _remap_snapshot(payload["snapshot"], id_map)
        payload["report_sha256"] = canonical_json_sha256(payload["snapshot"])
        values["payload_json"] = payload


def validate_audio_origin(sections: Sections, metadata: Any, archive_origin: Any) -> None:
    if metadata is None:
        return
    try:
        archive_aliases = archive_origin["id_map"] if isinstance(archive_origin, dict) else {}
        reports = {row["id"]: row for row in sections.get(REPORTS, ())}
        for local_id, receipt in metadata.items():
            row = reports[_key(local_id)]
            mapping = receipt["source_to_local"]
            inverse = {_key(local): _key(origin) for origin, local in mapping.items()}
            snapshot = row["snapshot_json"]
            if (
                len(inverse) != len(mapping)
                or set(inverse) != (_snapshot_references(snapshot) | {local_id})
                or any(archive_aliases.get(old) != new for old, new in mapping.items())
                or receipt["original_report_id"] != inverse[local_id]
                or receipt["local_report_sha256"] != row["report_sha256"]
                or receipt["original_report_sha256"]
                != canonical_json_sha256(_remap_snapshot(snapshot, inverse))
            ):
                raise ValueError(
                    "Frozen report does not reproduce its claimed original digest and identity"
                )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"Bioacoustic report origin is invalid: {exc}") from exc


def restore_audio_origin(
    sections: Sections, previous: Mapping[str, Any], id_map: Mapping[str, str]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in sections.get(REPORTS, ()):
        identifier = row["id"]
        snapshot = row["snapshot_json"]
        prior = previous.get(identifier)
        refs = _snapshot_references(snapshot) | {identifier}
        mapping = (
            prior["source_to_local"] if prior is not None else {key: key for key in sorted(refs)}
        )
        result[id_map[identifier]] = {
            "original_report_id": prior["original_report_id"] if prior is not None else identifier,
            "original_report_sha256": prior["original_report_sha256"]
            if prior is not None
            else row["report_sha256"],
            "local_report_sha256": canonical_json_sha256(_remap_snapshot(snapshot, id_map)),
            "source_to_local": {source: id_map[local] for source, local in mapping.items()},
        }
    return result
