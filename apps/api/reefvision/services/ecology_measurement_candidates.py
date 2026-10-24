"""Conservative projected measurements from registered ecological evidence.

These source-linked values are *not* verified longitudinal observations:
identity, timepoint, experimental independence and projection remain subject
to scientist review. No predictions or unreviewed source masks are accepted.
"""

from __future__ import annotations

import math
from datetime import timezone

from sqlalchemy.orm import Session

from reefvision.db.models.annotation import Annotation
from reefvision.db.models.image import ImageAsset
from reefvision.db.models.mask_annotation import MaskAnnotation
from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyMeasurementCandidatesResponse,
    EcologyMeasurementExclusion,
)
from reefvision.services.ecology_identity import EcologyIdentityService
from reefvision.storage.datasets import canonical_json_sha256


class EcologyMeasurementCandidateService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def candidates(
        self,
        project_id: str,
        *,
        registry: EcologyIdentityRegistryResponse | None = None,
    ) -> EcologyMeasurementCandidatesResponse:
        # The existing registry validates project ownership, human review,
        # annotation revisions, source-image fingerprints and frozen calibration.
        snapshot = registry or EcologyIdentityService(self.session).registry(project_id)
        if snapshot.project_id != project_id:
            raise ValidationError("Measurement registry belongs to another project")
        identities = {row.organism_key: row for row in snapshot.identities}
        image_links = {row.id: row for row in snapshot.image_evidence_links}
        annotations = {row.id: row for row in snapshot.annotation_evidence_links}
        candidates: list[EcologyMeasurementCandidate] = []
        exclusions: list[EcologyMeasurementExclusion] = []
        for calibration in sorted(
            snapshot.calibration_evidence_links, key=lambda row: row.id
        ):
            annotation = annotations[calibration.annotation_evidence_id]
            image_link = image_links[annotation.image_evidence_id]
            identity = identities[image_link.organism_key]
            image = self.session.get(ImageAsset, calibration.image_id)
            if image is None or image.project_id != project_id:
                raise ValidationError("Ecological measurement source image is missing")
            # A perspective homography needs per-point reprojection, not a
            # naive scalar area/length conversion. Never mislabel it as growth.
            if calibration.calibration_json.get("perspective_homography") is not None:
                exclusions.append(
                    EcologyMeasurementExclusion(
                        calibration_evidence_id=calibration.id,
                        reason="perspective_transform_requires_review",
                    )
                )
                continue
            scale = float(calibration.calibration_json["distance_per_pixel"])
            unit = str(calibration.calibration_json["unit"])
            source = (
                self.session.get(Annotation, annotation.annotation_id)
                if annotation.annotation_kind == "box"
                else self.session.get(MaskAnnotation, annotation.annotation_id)
            )
            if source is None:
                raise ValidationError("Ecological measurement annotation is missing")
            if annotation.annotation_kind == "box":
                assert isinstance(source, Annotation)
                values = [
                    ("box_width", (source.x_max - source.x_min) * scale, unit),
                    ("box_height", (source.y_max - source.y_min) * scale, unit),
                ]
            else:
                assert isinstance(source, MaskAnnotation)
                values = (
                    [(
                        "mask_projected_area",
                        float(source.area_pixels) * scale * scale,
                        f"{unit}^2",
                    )]
                    if source.area_pixels is not None
                    else []
                )
            if not values:
                exclusions.append(
                    EcologyMeasurementExclusion(
                        calibration_evidence_id=calibration.id,
                        reason="unsupported_geometry",
                    )
                )
                continue
            captured = image.capture_timestamp
            if captured is None:
                time_status = "missing"
                captured_utc = None
            elif captured.tzinfo is None or captured.utcoffset() is None:
                time_status = "timezone_missing"
                captured_utc = None
            else:
                time_status = "timezone_aware"
                captured_utc = captured.astimezone(timezone.utc)
            for metric, value, metric_unit in values:
                if not math.isfinite(value) or value <= 0:
                    raise ValidationError(
                        "Ecological projected measurement must be positive and finite"
                    )
                candidates.append(
                    EcologyMeasurementCandidate(
                        organism_key=identity.organism_key,
                        identity_revision=image_link.identity_revision,
                        parent_colony_key=identity.parent_colony_key,
                        experimental_unit_type=identity.experimental_unit_type,
                        experimental_unit_id=identity.experimental_unit_id,
                        image_id=image.id,
                        image_sha256=image.sha256,
                        annotation_evidence_id=annotation.id,
                        calibration_evidence_id=calibration.id,
                        annotation_kind=annotation.annotation_kind,
                        annotation_id=annotation.annotation_id,
                        annotation_revision=annotation.annotation_revision,
                        annotation_sha256=annotation.annotation_sha256,
                        calibration_sha256=calibration.calibration_sha256,
                        metric=metric,
                        value=value,
                        unit=metric_unit,
                        capture_timestamp_utc=captured_utc,
                        capture_time_status=time_status,
                    )
                )
        candidates.sort(
            key=lambda row: (
                row.organism_key,
                row.image_id,
                row.annotation_kind,
                row.annotation_id,
                row.metric,
            )
        )
        rows = [row.model_dump(mode="json") for row in candidates]
        skipped = [row.model_dump(mode="json") for row in exclusions]
        fingerprint = canonical_json_sha256(
            {
                "algorithm_version": "ecology-measurement-candidates-0001",
                "project_id": project_id,
                "registry_history_sha256": snapshot.history_sha256,
                "registry_image_evidence_sha256": snapshot.image_evidence_sha256,
                "registry_annotation_evidence_sha256": snapshot.annotation_evidence_sha256,
                "registry_calibration_evidence_sha256": snapshot.calibration_evidence_sha256,
                "candidates": rows,
                "exclusions": skipped,
            }
        )
        return EcologyMeasurementCandidatesResponse(
            project_id=project_id,
            source_registry_history_sha256=snapshot.history_sha256,
            source_calibration_evidence_sha256=snapshot.calibration_evidence_sha256,
            candidates=candidates,
            candidate_count=len(candidates),
            exclusions=exclusions,
            input_sha256=fingerprint,
        )
