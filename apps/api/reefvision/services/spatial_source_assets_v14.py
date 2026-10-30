"""Bounded immutable local OBJ/PLY/GLB original-byte storage."""

from __future__ import annotations

import base64
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project, SpatialSourceAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.services.spatial_point_cloud_v14 import (
    MAX_PLY_BYTES,
    preview_point_cloud_from_request,
)
from reefvision.storage.projects import resolve_managed_project_path

MAX_BYTES = 8 * 1024 * 1024
KINDS = {"obj": "mesh", "glb": "mesh", "ply": "mesh_or_point_cloud"}


def _safe_original_filename(name: str | None) -> bool:
    """Use the same lexical filename constraints for import and later replay."""
    return (
        isinstance(name, str)
        and bool(name)
        and len(name) <= 500
        and name not in {".", ".."}
        and Path(name).name == name
        and "\\" not in name
        and "\x00" not in name
    )


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
        if not _safe_original_filename(name):
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
        # Source kind is derived from the imported format. Reject corrupted
        # metadata before replaying an original, even when its bytes still hash
        # correctly. PLY deliberately remains ambiguous until parsed.
        if KINDS.get(asset.source_format) != asset.source_kind:
            raise ValidationError("Spatial source format and kind metadata do not match")
        # The filename is original audit metadata. A later database edit must
        # not silently relabel the imported bytes as another file or format.
        # Reapply the import safety constraints without changing legacy case.
        if not _safe_original_filename(asset.original_filename):
            raise ValidationError("Spatial source original filename metadata is invalid")
        original_format = Path(asset.original_filename).suffix.casefold().lstrip(".")
        if original_format != asset.source_format:
            raise ValidationError("Spatial source original filename metadata is invalid")
        # Bind the immutable original to its database identity, not merely to
        # a file somewhere in the project originals directory. Otherwise a
        # changed managed_path could replay identical bytes under a different
        # asset identity while still passing the stored SHA-256 check.
        expected_path = f"{project.storage_root}/spatial/originals/{asset.id}.{asset.source_format}"
        if asset.managed_path != expected_path:
            raise ValidationError("Spatial source path does not match immutable asset identity")
        # The managed resolver follows symlinks. A link to another file under
        # the same data root could otherwise replay identical bytes under the
        # original asset ID and still satisfy the SHA-256 check. Inspect each
        # lexical path component before resolving it, including parent folders.
        lexical_path = self.settings.resolved_data_dir
        for component in Path(expected_path).parts:
            lexical_path = lexical_path / component
            if lexical_path.is_symlink():
                raise ValidationError("Spatial source original path contains a symlink")
        path = resolve_managed_project_path(self.settings, asset.managed_path)
        if path.is_symlink() or not path.is_file():
            raise ValidationError("Spatial source original bytes are missing or unsafe")
        if asset.size_bytes <= 0 or asset.size_bytes > MAX_BYTES:
            raise ValidationError("Spatial source stored byte length is invalid")
        # Read only the bounded import limit, then compare the bytes actually read.
        # A separate stat/read_bytes sequence can race a growing original file.
        try:
            with path.open("rb") as source:
                data = source.read(MAX_BYTES + 1)
        except OSError as exc:
            # The original can disappear or become unreadable between the
            # path check and the bounded read. Treat that as invalid source
            # evidence, not an unexpected server failure or measurement.
            raise ValidationError("Spatial source original bytes could not be read") from exc
        if len(data) != asset.size_bytes:
            raise ValidationError("Spatial source byte length no longer matches import")
        if sha256(data).hexdigest() != asset.sha256:
            raise ValidationError("Spatial source original bytes failed SHA-256 verification")
        return data


def preview_project_mesh(
    session: Session,
    settings: Settings,
    project_id: str,
    payload: MeshPreviewRequest,
) -> dict[str, Any]:
    """Run the same preview engine for inline or immutable project-owned source bytes."""
    if payload.asset_id is None:
        # Inline geometry has no project-owned imported source identity.
        if (
            payload.calibration_review is not None
            and payload.calibration_review.reviewed_spatial_source_asset_id is not None
        ):
            raise ValidationError(
                "Asset-bound calibration review requires an imported spatial source asset"
            )
        return preview_from_request(payload)
    service = SpatialSourceAssetService(session, settings)
    asset = service.get(project_id, payload.asset_id)
    original = service.read_verified(project_id, asset.id)
    # The byte digest alone does not identify a project-owned original:
    # two projects may import identical source bytes independently.
    review = payload.calibration_review
    if (
        review is not None
        and review.reviewed_spatial_source_asset_id is not None
        and review.reviewed_spatial_source_asset_id != asset.id
    ):
        raise ValidationError("Calibration review does not match imported spatial source asset")
    if (
        payload.expected_source_payload_sha256 is not None
        and payload.expected_source_payload_sha256 != asset.sha256
    ):
        raise ValidationError("Project mesh asset SHA-256 differs from expected source")
    fields = payload.model_dump(mode="python", exclude={"asset_id"})
    fields["expected_source_payload_sha256"] = asset.sha256
    if asset.source_format == "glb":
        encoded = base64.b64encode(original).decode("ascii")
        if len(encoded) > 350_000:
            raise ValidationError("Project GLB exceeds bounded mesh preview limit")
        fields["glb_base64"] = encoded
    elif asset.source_format in {"obj", "ply"}:
        try:
            text = original.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError("Project mesh preview requires UTF-8 OBJ or ASCII PLY") from exc
        if len(text) > 256_000:
            raise ValidationError("Project mesh exceeds bounded text preview limit")
        fields["obj_text" if asset.source_format == "obj" else "ply_text"] = text
    else:
        raise ValidationError("Unsupported project mesh source format")
    try:
        resolved = MeshPreviewRequest.model_validate(fields)
        result = preview_from_request(resolved)
    except (PydanticValidationError, ValueError) as exc:
        raise ValidationError(f"Invalid project mesh preview: {exc}") from exc
    result["provenance"]["spatial_source_asset_id"] = asset.id
    result["provenance"]["spatial_source_asset_sha256"] = asset.sha256
    result["qc_warnings"].append("project_source_original_unreviewed")
    if review is not None and review.reviewed_spatial_source_asset_id is None:
        result["qc_warnings"].append("independent_calibration_review_source_asset_unbound")
    return result


def preview_project_point_cloud(
    session: Session,
    settings: Settings,
    project_id: str,
    payload: PointCloudPreviewRequest,
) -> dict[str, Any]:
    """Resolve a project-owned ASCII PLY through the shared point-cloud engine."""
    if payload.asset_id is None:
        # Inline XYZ/PLY bytes have no project-owned imported source identity.
        if (
            payload.calibration_review is not None
            and payload.calibration_review.reviewed_spatial_source_asset_id is not None
        ):
            raise ValidationError(
                "Asset-bound calibration review requires an imported spatial source asset"
            )
        return preview_point_cloud_from_request(payload)
    service = SpatialSourceAssetService(session, settings)
    asset = service.get(project_id, payload.asset_id)
    if asset.source_format != "ply":
        raise ValidationError("Project point-cloud preview requires a PLY original")
    original = service.read_verified(project_id, asset.id)
    # The byte digest alone does not identify a project-owned original:
    # two projects may import identical source bytes independently.
    review = payload.calibration_review
    if (
        review is not None
        and review.reviewed_spatial_source_asset_id is not None
        and review.reviewed_spatial_source_asset_id != asset.id
    ):
        raise ValidationError("Calibration review does not match imported spatial source asset")
    if (
        payload.expected_source_payload_sha256 is not None
        and payload.expected_source_payload_sha256 != asset.sha256
    ):
        raise ValidationError("Project point-cloud asset SHA-256 differs from expected source")
    if len(original) > MAX_PLY_BYTES:
        raise ValidationError("Project PLY exceeds bounded point-cloud preview limit")
    try:
        text = original.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("Project point-cloud preview requires ASCII PLY") from exc
    fields = payload.model_dump(mode="python", exclude={"asset_id"})
    fields["ply_text"] = text
    fields["expected_source_payload_sha256"] = asset.sha256
    try:
        resolved = PointCloudPreviewRequest.model_validate(fields)
        result = preview_point_cloud_from_request(resolved)
    except (PydanticValidationError, ValueError) as exc:
        raise ValidationError(f"Invalid project point-cloud preview: {exc}") from exc
    result["provenance"]["spatial_source_asset_id"] = asset.id
    result["provenance"]["spatial_source_asset_sha256"] = asset.sha256
    result["qc_warnings"].append("project_source_original_unreviewed")
    if review is not None and review.reviewed_spatial_source_asset_id is None:
        result["qc_warnings"].append("independent_calibration_review_source_asset_unbound")
    return result
