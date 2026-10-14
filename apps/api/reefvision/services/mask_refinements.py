"""Persist previews separately and replace selected masks only on explicit approval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, MaskAnnotation, MaskAnnotationEvent, Project
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.mask_refinement import component_points, infer_refinement
from reefvision.schemas.annotations import MaskAnnotationResponse
from reefvision.schemas.images import ImageResponse
from reefvision.schemas.mask_refinements import (
    MaskRefinementAcceptRequest,
    MaskRefinementGeometryRequest,
    MaskRefinementPreviewRequest,
    MaskRefinementResponse,
)
from reefvision.schemas.raster_edits import RasterMaskEditResponse
from reefvision.services.annotations import mask_annotation_snapshot
from reefvision.services.mask_measurements import MaskMeasurementService
from reefvision.storage.mask_refinements import (
    load_prior,
    save_candidate,
    save_candidate_png,
    verified_file,
)

WARNING = (
    "Suggested alternative boundary from geometry-guided SAM points; not guaranteed tightening. "
    "Inspect holes, thin branches and fragments before replacing."
)


def snapshot(mask: MaskAnnotation) -> dict[str, Any]:
    return {**mask_annotation_snapshot(mask), "measurement_json": dict(mask.measurement_json or {})}


def metrics(prior: Any, proposed: Any) -> dict[str, Any]:
    import numpy as np

    if proposed.shape != prior.shape or not proposed.any():
        raise ValidationError("Candidate must be a non-empty mask at source-image dimensions")
    old_area, area = int(prior.sum()), int(proposed.sum())
    intersection = int(np.logical_and(prior, proposed).sum())
    union = old_area + area - intersection
    warnings = [WARNING]
    # Comparing foreground and background components catches lost fragments and filled holes.
    topology_changed = len(component_points(prior)) != len(component_points(proposed)) or len(
        component_points(~prior)
    ) != len(component_points(~proposed))
    removed = old_area - intersection
    if removed:
        warnings.append(
            f"The suggestion removes {removed} original foreground pixels; inspect thin branches."
        )
    if topology_changed:
        warnings.append(
            "Connected foreground/background regions changed; inspect holes and fragments."
        )
    large = abs(area - old_area) / old_area > 0.25 or intersection / union < 0.70
    if large:
        warnings.append("Large geometry change: explicit confirmation is required.")
    return {
        "old_area_pixels": old_area,
        "proposed_area_pixels": area,
        "iou": intersection / union,
        "edge_change_percent": 100 * (union - intersection) / union,
        "warnings": warnings,
        "requires_confirmation": large or topology_changed,
    }


class MaskRefinementService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _claim(self, job: Job) -> None:
        """Serialize against edits/discards read by another request before this transaction."""
        result = self.session.execute(
            update(Job)
            .where(
                Job.id == job.id,
                Job.result_json == job.result_json,
            )
            .values(result_json=job.result_json)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            self.session.rollback()
            raise ConflictError("Refinement changed in another request; reload the candidate")

    def _mask(self, mask_id: str) -> tuple[MaskAnnotation, ImageAsset, Project]:
        mask = self.session.get(MaskAnnotation, mask_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        if mask.status == "locked" or (mask.provenance_json or {}).get("locked"):
            raise ConflictError("This mask is locked")
        image = self.session.get(ImageAsset, mask.image_id)
        project = self.session.get(Project, image.project_id) if image else None
        if image is None or project is None:
            raise NotFoundError("Source image or project not found")
        if mask.label_class_id not in {item.id for item in project.label_classes}:
            raise ValidationError("Mask class does not belong to its source project")
        return mask, image, project

    def _candidate(self, candidate_id: str, *, pending: bool = False) -> tuple[Job, dict[str, Any]]:
        job = self.session.get(Job, candidate_id)
        if job is None or job.job_type != "mask_refinement" or job.result_json is None:
            raise NotFoundError("Mask refinement candidate not found")
        data = dict(job.result_json)
        if pending:
            if data["status"] != "pending":
                raise ConflictError("Only a pending refinement can be edited or accepted")
            if datetime.fromisoformat(data["expires_at"]) <= datetime.now(UTC):
                raise ConflictError("Refinement candidate expired; generate a new preview")
        return job, data

    def get(self, candidate_id: str) -> MaskRefinementResponse:
        _, data = self._candidate(candidate_id)
        return MaskRefinementResponse.model_validate(data)

    def content(self, candidate_id: str) -> Path:
        _, data = self._candidate(candidate_id)
        return verified_file(
            self.settings, data["geometry"]["mask_path"], data["geometry"]["mask_sha256"]
        )

    def preview(
        self, mask_id: str, payload: MaskRefinementPreviewRequest
    ) -> MaskRefinementResponse:
        mask, image, project = self._mask(mask_id)
        if mask.revision != payload.expected_revision:
            raise ConflictError("Mask revision conflict")
        original = snapshot(mask)
        prior = load_prior(self.settings, original, image.width_px, image.height_px)
        prediction, provenance = infer_refinement(
            settings=self.settings,
            source_image_path=image.managed_path,
            variant=payload.variant,
            device=payload.device,
            prior=prior,
            positive_points=payload.positive_points,
            negative_points=payload.negative_points,
        )
        import numpy as np

        candidate = np.asarray(prediction.mask, dtype=bool)
        report = metrics(prior, candidate)
        geometry = save_candidate(self.settings, project.storage_root, image.id, candidate)
        candidate_id = str(uuid4())
        now = utc_now()
        data = {
            "candidate_id": candidate_id,
            "mask_annotation_id": mask.id,
            "image_id": image.id,
            "expected_revision": mask.revision,
            "status": "pending",
            "mask_url": f"/api/v1/mask-refinements/{candidate_id}/content",
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "before": original,
            "geometry": geometry,
            "provenance": provenance,
            "image_sha256": image.sha256,
            "source_mask_sha256": sha256(prior.tobytes()).hexdigest(),
            **report,
        }
        self.session.add(
            Job(
                id=candidate_id,
                project_id=project.id,
                job_type="mask_refinement",
                status="succeeded",
                progress_current=1,
                progress_total=1,
                request_json=payload.model_dump(mode="json"),
                result_json=data,
                started_at=now,
                completed_at=now,
            )
        )
        self.session.commit()
        return MaskRefinementResponse.model_validate(data)

    def edit(
        self, candidate_id: str, payload: MaskRefinementGeometryRequest
    ) -> MaskRefinementResponse:
        job, data = self._candidate(candidate_id, pending=True)
        self._claim(job)
        mask, image, project = self._mask(data["mask_annotation_id"])
        if mask.revision != data["expected_revision"]:
            raise ConflictError("Mask changed after refinement preview")
        geometry = save_candidate_png(
            self.settings,
            project.storage_root,
            image.id,
            payload.mask_png_base64,
            image.width_px,
            image.height_px,
        )
        prior = load_prior(self.settings, data["before"], image.width_px, image.height_px)
        proposed = load_prior(
            self.settings,
            {**geometry, "geometry_kind": "raster_mask"},
            image.width_px,
            image.height_px,
        )
        data.update(metrics(prior, proposed))
        data["geometry"] = geometry
        data["edited"] = True
        job.result_json = data
        self.session.commit()
        return MaskRefinementResponse.model_validate(data)

    def discard(self, candidate_id: str) -> MaskRefinementResponse:
        job, data = self._candidate(candidate_id)
        self._claim(job)
        if data["status"] not in {"pending", "discarded"}:
            raise ConflictError("Only a pending refinement can be discarded")
        data["status"] = "discarded"
        job.result_json = data
        self.session.commit()
        return MaskRefinementResponse.model_validate(data)

    def accept(
        self, candidate_id: str, payload: MaskRefinementAcceptRequest
    ) -> RasterMaskEditResponse:
        job, data = self._candidate(candidate_id, pending=True)
        self._claim(job)
        mask, image, _ = self._mask(data["mask_annotation_id"])
        if mask.revision != data["expected_revision"] or mask.revision != payload.expected_revision:
            raise ConflictError("Mask changed after refinement preview")
        if snapshot(mask) != data["before"] or image.sha256 != data["image_sha256"]:
            raise ConflictError("Source mask or image changed after refinement preview")
        prior = load_prior(self.settings, data["before"], image.width_px, image.height_px)
        if sha256(prior.tobytes()).hexdigest() != data["source_mask_sha256"]:
            raise ConflictError("Source raster content changed after refinement preview")
        self.content(candidate_id)
        if data["requires_confirmation"] and not payload.confirm_large_change:
            raise ValidationError(
                "Review warnings and explicitly confirm this large or topological geometry change"
            )
        geometry = data["geometry"]
        target = {
            **snapshot(mask),
            **{
                k: geometry[k]
                for k in ("mask_path", "area_pixels", "x_min", "y_min", "x_max", "y_max")
            },
            "geometry_kind": "raster_mask",
            "polygon_json": None,
            "provenance_json": {
                **(mask.provenance_json or {}),
                "last_refinement": {
                    "candidate_id": candidate_id,
                    "accepted_at": utc_now().isoformat(),
                    "actor": "local_user",
                    "mask_sha256": geometry["mask_sha256"],
                    "edited": data.get("edited", False),
                    "confirmed_geometry_change": payload.confirm_large_change,
                    **data["provenance"],
                },
                "dependent_analysis_stale": True,
            },
        }
        data["status"] = "accepted"
        return self._replace(job, data, mask, image, target, payload.expected_revision, "refined")

    def history(
        self, candidate_id: str, payload: MaskRefinementAcceptRequest, *, redo: bool
    ) -> RasterMaskEditResponse:
        job, data = self._candidate(candidate_id)
        self._claim(job)
        required = "undone" if redo else "accepted"
        if data["status"] != required:
            raise ConflictError(f"Refinement must be {required} before this history action")
        mask, image, _ = self._mask(data["mask_annotation_id"])
        if mask.revision != data["last_revision"]:
            raise ConflictError("Mask changed since this refinement history action")
        target = data["after"] if redo else data["before"]
        if target.get("mask_path"):
            verified_file(self.settings, target["mask_path"])
        data["status"] = "accepted" if redo else "undone"
        return self._replace(
            job,
            data,
            mask,
            image,
            target,
            payload.expected_revision,
            "refinement_redone" if redo else "refinement_undone",
        )

    def _replace(
        self,
        job: Job,
        data: dict[str, Any],
        mask: MaskAnnotation,
        image: ImageAsset,
        target: dict[str, Any],
        expected: int,
        event_type: str,
    ) -> RasterMaskEditResponse:
        before = snapshot(mask)
        result = self.session.execute(
            update(MaskAnnotation)
            .where(
                MaskAnnotation.id == mask.id,
                MaskAnnotation.revision == expected,
                MaskAnnotation.deleted_at.is_(None),
            )
            .values(revision=expected + 1)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            self.session.rollback()
            raise ConflictError("Mask revision conflict")
        for key in (
            "geometry_kind",
            "mask_path",
            "polygon_json",
            "x_min",
            "y_min",
            "x_max",
            "y_max",
            "area_pixels",
            "provenance_json",
            "measurement_json",
        ):
            setattr(mask, key, target[key])
        mask.revision = expected + 1
        self.session.execute(
            update(ImageAsset)
            .where(ImageAsset.id == image.id)
            .values(annotation_revision=ImageAsset.annotation_revision + 1)
        )
        self.session.flush()
        # Measurements are computed from canonical geometry and the unchanged calibration/profile.
        measurement = MaskMeasurementService(self.session, self.settings).measure(mask.id)
        data["measurements"] = measurement.model_dump(mode="json")
        after = snapshot(mask)
        if event_type == "refined":
            data["after"] = after
        data["last_revision"] = mask.revision
        job.result_json = data
        self.session.add(
            MaskAnnotationEvent(
                mask_annotation_id=mask.id,
                image_id=image.id,
                event_type=event_type,
                before_json=before,
                after_json=after,
                actor="local_user",
            )
        )
        self.session.commit()
        self.session.refresh(image)
        self.session.refresh(mask)
        return RasterMaskEditResponse(
            image=ImageResponse.model_validate(image),
            mask_annotation=MaskAnnotationResponse.model_validate(mask),
        )
