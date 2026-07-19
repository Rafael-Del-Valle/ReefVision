"""Safe previews for managed and payload-backed artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ArtifactRecord
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.artifacts import ArtifactPreviewResponse
from reefvision.storage.projects import resolve_managed_project_path

_TEXT_SUFFIXES = {
    ".txt",
    ".log",
    ".md",
    ".yaml",
    ".yml",
    ".xml",
    ".jsonl",
    ".py",
    ".r",
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ArtifactPreviewService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def artifact(self, artifact_id: str) -> ArtifactRecord:
        artifact = self.session.get(ArtifactRecord, artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact not found")
        return artifact

    def content_path(self, artifact_id: str) -> tuple[ArtifactRecord, Path]:
        artifact = self.artifact(artifact_id)
        if artifact.managed_path is None:
            raise ValidationError("This artifact is payload-backed and has no managed content file")
        path = resolve_managed_project_path(self.settings, artifact.managed_path)
        if not path.is_file():
            raise NotFoundError("Artifact content is missing")
        return artifact, path

    def preview(self, artifact_id: str) -> ArtifactPreviewResponse:
        artifact = self.artifact(artifact_id)
        payload = artifact.metadata_json.get("payload")
        if artifact.managed_path is None:
            return ArtifactPreviewResponse(
                artifact_id=artifact.id,
                preview_kind="payload",
                media_type="application/json",
                content_url=None,
                filename=None,
                text=None,
                payload=payload if isinstance(payload, (dict, list)) else artifact.metadata_json,
                columns=[],
                rows=[],
                archive_entries=[],
                truncated=False,
                checksum_verified=None,
            )
        _artifact, path = self.content_path(artifact_id)
        suffix = path.suffix.casefold()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        checksum_verified = _sha256(path) == artifact.checksum
        content_url = f"/api/v1/artifacts/{artifact.id}/content"
        base = {
            "artifact_id": artifact.id,
            "media_type": media_type,
            "content_url": content_url,
            "filename": path.name,
            "columns": [],
            "rows": [],
            "archive_entries": [],
            "checksum_verified": checksum_verified,
        }
        if suffix in _IMAGE_SUFFIXES:
            return ArtifactPreviewResponse(
                **base,
                preview_kind="image",
                text=None,
                payload=None,
                truncated=False,
            )
        if suffix in _VIDEO_SUFFIXES:
            return ArtifactPreviewResponse(
                **base,
                preview_kind="video",
                text=None,
                payload=None,
                truncated=False,
            )
        if suffix in _AUDIO_SUFFIXES:
            return ArtifactPreviewResponse(
                **base,
                preview_kind="audio",
                text=None,
                payload=None,
                truncated=False,
            )
        if suffix in {".html", ".htm"}:
            return ArtifactPreviewResponse(
                **base,
                preview_kind="html",
                text=None,
                payload=None,
                truncated=False,
            )
        if suffix == ".json":
            raw = path.read_bytes()
            truncated = len(raw) > 2_000_000
            parsed: Any = None
            text: str | None = None
            try:
                if truncated:
                    text = raw[:200_000].decode("utf-8", errors="replace")
                else:
                    parsed = json.loads(raw)
            except json.JSONDecodeError:
                text = raw[:200_000].decode("utf-8", errors="replace")
            return ArtifactPreviewResponse(
                **base,
                preview_kind="json" if parsed is not None else "text",
                text=text,
                payload=parsed if isinstance(parsed, (dict, list)) else None,
                truncated=truncated,
            )
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            rows: list[list[Any]] = []
            columns: list[str] = []
            truncated = False
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.reader(handle, delimiter=delimiter)
                for index, row in enumerate(reader):
                    if index == 0:
                        columns = row
                    elif index <= 200:
                        rows.append(row)
                    else:
                        truncated = True
                        break
            return ArtifactPreviewResponse(
                **{**base, "columns": columns, "rows": rows},
                preview_kind="table",
                text=None,
                payload=None,
                truncated=truncated,
            )
        if suffix in {".zip", ".rvzip"}:
            try:
                with zipfile.ZipFile(path) as archive:
                    entries = archive.namelist()
            except zipfile.BadZipFile as exc:
                raise ValidationError("Artifact archive is invalid") from exc
            return ArtifactPreviewResponse(
                **{**base, "archive_entries": entries[:500]},
                preview_kind="archive",
                text=None,
                payload=None,
                truncated=len(entries) > 500,
            )
        if suffix in _TEXT_SUFFIXES or media_type.startswith("text/"):
            raw = path.read_bytes()
            return ArtifactPreviewResponse(
                **base,
                preview_kind="text",
                text=raw[:200_000].decode("utf-8", errors="replace"),
                payload=None,
                truncated=len(raw) > 200_000,
            )
        return ArtifactPreviewResponse(
            **base,
            preview_kind="binary",
            text=None,
            payload=None,
            truncated=False,
        )
