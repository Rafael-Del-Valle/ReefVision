"""Bounded immutable local OBJ/PLY/GLB original-byte storage."""

from __future__ import annotations

import base64
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO
from unicodedata import category
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, Project, SpatialSourceAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.schemas.spatial_source_asset_v14 import (
    SpatialSourceAssetResponse,
    SpatialSourceParseResult,
    SpatialSourceParseSummary,
)
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.services.spatial_point_cloud_v14 import (
    MAX_PLY_BYTES,
    preview_point_cloud_from_request,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

MAX_BYTES = 8 * 1024 * 1024
KINDS = {"obj": "mesh", "glb": "mesh", "ply": "mesh_or_point_cloud"}
SPATIAL_PARSE_JOB = "spatial_source_parse"
SPATIAL_PARSE_SCHEMA = "spatial-source-parse-0001"


def spatial_source_parse_result_content(result: SpatialSourceParseResult) -> dict[str, Any]:
    return result.model_dump(mode="json", exclude={"content_sha256"})


def _safe_original_filename(name: str | None) -> bool:
    """Use the same lexical filename constraints for import and later replay."""
    return (
        isinstance(name, str)
        and bool(name)
        and len(name) <= 500
        and name not in {".", ".."}
        and Path(name).name == name
        and "\\" not in name
        and not any(
            ord(character) < 32 or ord(character) == 127 or category(character) in {"Cf", "Cs"}
            for character in name
        )
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

    def _parse_deduplication_key(self, asset: SpatialSourceAsset) -> str:
        return sha256(
            (
                f"{SPATIAL_PARSE_SCHEMA}\0{asset.project_id}\0{asset.id}\0"
                f"{asset.sha256}\0{asset.source_format}"
            ).encode()
        ).hexdigest()

    def _new_parse_job(self, asset: SpatialSourceAsset) -> Job:
        return Job(
            project_id=asset.project_id,
            job_type=SPATIAL_PARSE_JOB,
            deduplication_key=self._parse_deduplication_key(asset),
            status="queued",
            progress_current=0,
            progress_total=1,
            request_json={
                "schema_version": SPATIAL_PARSE_SCHEMA,
                "project_id": asset.project_id,
                "spatial_source_asset_id": asset.id,
                "expected_source_sha256": asset.sha256,
                "source_format": asset.source_format,
                "managed_path": asset.managed_path,
                "size_bytes": asset.size_bytes,
            },
        )

    def latest_parse_job(self, asset: SpatialSourceAsset) -> Job | None:
        return self.session.scalar(
            select(Job)
            .where(
                Job.project_id == asset.project_id,
                Job.job_type == SPATIAL_PARSE_JOB,
                Job.request_json["spatial_source_asset_id"].as_string() == asset.id,
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )

    def ensure_parse_job(self, asset: SpatialSourceAsset) -> Job:
        existing = self.latest_parse_job(asset)
        if existing is not None:
            return existing
        job = self._new_parse_job(asset)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def response(self, asset: SpatialSourceAsset) -> SpatialSourceAssetResponse:
        job = self.latest_parse_job(asset)
        summary: SpatialSourceParseSummary | None = None
        if job is not None and job.status == "succeeded":
            # A result digest alone cannot establish that this was the request
            # executed for the immutable source. A successful job must also
            # have a result and retain the original request binding.
            request = job.request_json
            if (
                job.result_json is None
                or request.get("schema_version") != SPATIAL_PARSE_SCHEMA
                or request.get("project_id") != asset.project_id
                or request.get("spatial_source_asset_id") != asset.id
                or request.get("expected_source_sha256") != asset.sha256
                or request.get("source_format") != asset.source_format
                or request.get("managed_path") != asset.managed_path
                or type(request.get("size_bytes")) is not int
                or request.get("size_bytes") != asset.size_bytes
            ):
                raise ValidationError("Spatial source parse result failed integrity validation")
            try:
                result = SpatialSourceParseResult.model_validate(job.result_json)
            except (PydanticValidationError, ValueError) as exc:
                raise ValidationError(
                    "Spatial source parse result failed integrity validation"
                ) from exc
            if (
                result.project_id != asset.project_id
                or result.spatial_source_asset_id != asset.id
                or result.source_sha256 != asset.sha256
                or result.source_format != asset.source_format
                or canonical_json_sha256(spatial_source_parse_result_content(result))
                != result.content_sha256
            ):
                raise ValidationError("Spatial source parse result failed integrity validation")
            summary = SpatialSourceParseSummary.model_validate(
                {key: getattr(result, key) for key in SpatialSourceParseSummary.model_fields}
            )
        return SpatialSourceAssetResponse.model_validate(
            {
                **{
                    field: getattr(asset, field)
                    for field in SpatialSourceAssetResponse.model_fields
                    if hasattr(asset, field)
                },
                "parse_job_id": None if job is None else job.id,
                "parse_status": "not_queued" if job is None else job.status,
                "parse_summary": summary,
            }
        )

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
            # Deduplication must not silently replace the caller-supplied
            # original filename with a different prior import identity.
            if existing.original_filename != name:
                raise ValidationError(
                    "Identical spatial bytes already exist under a different original filename"
                )
            self.ensure_parse_job(existing)
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
        self.session.add(self._new_parse_job(asset))
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
        try:
            lexical_path = self.settings.resolved_data_dir
            for component in Path(expected_path).parts:
                lexical_path = lexical_path / component
                if lexical_path.is_symlink():
                    raise ValidationError("Spatial source original path contains a symlink")
            path = resolve_managed_project_path(self.settings, asset.managed_path)
            if path.is_symlink() or not path.is_file():
                raise ValidationError("Spatial source original bytes are missing or unsafe")
        except OSError as exc:
            # Permission changes or I/O failures during path inspection are
            # invalid source evidence, not an unexpected server error.
            raise ValidationError("Spatial source original path could not be inspected") from exc
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


def _load_saved_calibration_review(
    session: Session,
    settings: Settings,
    project_id: str,
    asset_id: str,
    review_id: str,
) -> tuple[Any, str]:
    # Local import avoids a module cycle with the review receipt service.
    from reefvision.services.spatial_calibration_review_v14 import SpatialCalibrationReviewService

    receipt = SpatialCalibrationReviewService(session, settings).get(
        project_id, asset_id, review_id
    )
    # get() rechecks the original bytes, project/asset binding and evidence digest.
    # The receipt is attributed audit evidence, never an authenticated approval.
    return receipt.evidence, receipt.evidence_sha256


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
    review_digest: str | None = None
    if payload.calibration_review_id is not None:
        review, review_digest = _load_saved_calibration_review(
            session, settings, project_id, asset.id, payload.calibration_review_id
        )
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
    fields = payload.model_dump(mode="python", exclude={"asset_id", "calibration_review_id"})
    fields["calibration_review"] = review
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
    if review_digest is not None:
        result["provenance"]["calibration_review_record_id"] = payload.calibration_review_id
        result["provenance"]["calibration_review_evidence_sha256"] = review_digest
        result["qc_warnings"].append("persisted_calibration_review_unverified")
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
    review_digest: str | None = None
    if payload.calibration_review_id is not None:
        review, review_digest = _load_saved_calibration_review(
            session, settings, project_id, asset.id, payload.calibration_review_id
        )
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
    fields = payload.model_dump(mode="python", exclude={"asset_id", "calibration_review_id"})
    fields["calibration_review"] = review
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
    if review_digest is not None:
        result["provenance"]["calibration_review_record_id"] = payload.calibration_review_id
        result["provenance"]["calibration_review_evidence_sha256"] = review_digest
        result["qc_warnings"].append("persisted_calibration_review_unverified")
    if review is not None and review.reviewed_spatial_source_asset_id is None:
        result["qc_warnings"].append("independent_calibration_review_source_asset_unbound")
    return result
