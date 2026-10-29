"""Bounded immutable local OBJ/PLY/GLB original-byte storage."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project, SpatialSourceAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.storage.projects import resolve_managed_project_path

MAX_BYTES = 8 * 1024 * 1024
KINDS = {"obj": "mesh", "glb": "mesh", "ply": "mesh_or_point_cloud"}


class SpatialSourceAssetService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def get(self, project_id: str, asset_id: str) -> SpatialSourceAsset:
        self._project(project_id)
        asset = self.session.get(SpatialSourceAsset, asset_id)
        if asset is None or asset.project_id != project_id:
            raise NotFoundError("Spatial source asset not found in project")
        return asset

    def list(self, project_id: str) -> list[SpatialSourceAsset]:
        self._project(project_id)
        query = (
            select(SpatialSourceAsset)
            .where(SpatialSourceAsset.project_id == project_id)
            .order_by(SpatialSourceAsset.created_at, SpatialSourceAsset.id)
        )
        return list(self.session.scalars(query))

    def import_source(
        self, project_id: str, filename: str | None, stream: BinaryIO
    ) -> SpatialSourceAsset:
        project = self._project(project_id)
        name = filename or ""
        if (
            not name
            or len(name) > 500
            or name in {".", ".."}
            or Path(name).name != name
            or "\\" in name
            or "\x00" in name
        ):
            raise ValidationError("A safe original 3D filename is required")
        source_format = Path(name).suffix.casefold().lstrip(".")
        if source_format not in KINDS:
            raise ValidationError("Only OBJ, PLY, and GLB originals are supported")
        data = stream.read(MAX_BYTES + 1)
        if not isinstance(data, bytes) or not data:
            raise ValidationError("Spatial source must contain nonempty bytes")
        if len(data) > MAX_BYTES:
            raise ValidationError("Spatial source exceeds the 8 MiB import limit")
        digest = sha256(data).hexdigest()
        existing = self.session.scalar(
            select(SpatialSourceAsset).where(
                SpatialSourceAsset.project_id == project_id,
                SpatialSourceAsset.sha256 == digest,
                SpatialSourceAsset.source_format == source_format,
            )
        )
        if existing is not None:
            self.read_verified(project_id, existing.id)
            return existing
        asset_id = str(uuid4())
        relative = f"{project.storage_root}/spatial/originals/{asset_id}.{source_format}"
        destination = resolve_managed_project_path(self.settings, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(data)
        asset = SpatialSourceAsset(
            id=asset_id,
            project_id=project_id,
            original_filename=name,
            source_format=source_format,
            source_kind=KINDS[source_format],
            managed_path=relative,
            sha256=digest,
            size_bytes=len(data),
        )
        self.session.add(asset)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            destination.unlink(missing_ok=True)
            raise
        self.session.refresh(asset)
        return asset

    def read_verified(self, project_id: str, asset_id: str) -> bytes:
        asset = self.get(project_id, asset_id)
        project = self._project(project_id)
        if not asset.managed_path.startswith(f"{project.storage_root}/spatial/originals/"):
            raise ValidationError("Spatial source path is outside its project")
        path = resolve_managed_project_path(self.settings, asset.managed_path)
        if not path.is_file():
            raise ValidationError("Spatial source original bytes are missing")
        if path.stat().st_size != asset.size_bytes or asset.size_bytes > MAX_BYTES:
            raise ValidationError("Spatial source byte length no longer matches import")
        data = path.read_bytes()
        if sha256(data).hexdigest() != asset.sha256:
            raise ValidationError("Spatial source original bytes failed SHA-256 verification")
        return data
