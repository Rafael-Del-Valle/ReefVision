"""Read-only annotation summaries for ReefVision 1.1.

Canonical boxes, verified masks and model proposals remain
separate. Mask pixel totals are sums, not union coverage.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    PredictionProposal,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.annotation_aggregates import (
    AnnotationClassAggregate,
    AnnotationImageAggregate,
)
from reefvision.services.annotations import (
    annotation_snapshot,
    mask_annotation_snapshot,
)
from reefvision.services.scientific_data import content_hash

AGGREGATE_VERSION = "reefvision-image-annotation-summary-1"
MAX_OBJECTS = 100_000


class AnnotationAggregateService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summarize_image(
        self,
        project_id: str,
        image_id: str,
    ) -> AnnotationImageAggregate:

        image = self.session.get(ImageAsset, image_id)
        if image is None or image.project_id != project_id:
            raise NotFoundError("Project image not found")

        boxes = self.session.scalars(
            select(Annotation)
            .where(
                Annotation.image_id == image_id,
                Annotation.deleted_at.is_(None),
            )
            .order_by(Annotation.id)
        ).all()

        masks = self.session.scalars(
            select(MaskAnnotation)
            .where(
                MaskAnnotation.image_id == image_id,
                MaskAnnotation.deleted_at.is_(None),
            )
            .order_by(MaskAnnotation.id)
        ).all()

        proposals = self.session.scalars(
            select(PredictionProposal)
            .where(
                PredictionProposal.project_id == project_id,
                PredictionProposal.image_id == image_id,
            )
            .order_by(PredictionProposal.id)
        ).all()

        if len(boxes) + len(masks) + len(proposals) > MAX_OBJECTS:
            raise ValidationError("Image exceeds the annotation summary object limit")

        labels = {
            label.id: label
            for label in self.session.scalars(
                select(LabelClass).where(LabelClass.project_id == project_id)
            ).all()
        }

        grouping: dict[str | None, dict[str, Any]] = defaultdict(
            lambda: {
                "box_count": 0,
                "verified_mask_count": 0,
                "draft_or_unverified_mask_count": 0,
                "known_mask_area_px2_sum": 0,
                "mask_area_unknown_count": 0,
                "boxes_by_source": Counter(),
                "verified_masks_by_geometry": Counter(),
            }
        )

        for box in boxes:
            if box.label_class_id not in labels:
                raise ValidationError("Annotation label does not belong to project")

            if not (
                0 <= box.x_min < box.x_max <= image.width_px
                and 0 <= box.y_min < box.y_max <= image.height_px
            ):
                raise ValidationError("Invalid source-image annotation bounds")

            item = grouping[box.label_class_id]
            item["box_count"] += 1
            item["boxes_by_source"][box.source_type] += 1

        for mask in masks:
            if mask.label_class_id is not None and mask.label_class_id not in labels:
                raise ValidationError("Mask label does not belong to project")

            item = grouping[mask.label_class_id]

            if mask.status != "verified":
                item["draft_or_unverified_mask_count"] += 1
                continue

            item["verified_mask_count"] += 1
            item["verified_masks_by_geometry"][mask.geometry_kind] += 1

            if mask.area_pixels is None:
                item["mask_area_unknown_count"] += 1
                continue

            if not (0 <= mask.area_pixels <= image.width_px * image.height_px):
                raise ValidationError("Verified mask has invalid source-pixel area")

            item["known_mask_area_px2_sum"] += mask.area_pixels

        classes = []

        for label_id, item in grouping.items():
            label = labels.get(label_id) if label_id else None

            classes.append(
                AnnotationClassAggregate(
                    label_class_id=UUID(label_id) if label_id is not None else None,
                    label_name=(label.name if label else "Unclassified"),
                    box_count=item["box_count"],
                    verified_mask_count=item["verified_mask_count"],
                    draft_or_unverified_mask_count=item["draft_or_unverified_mask_count"],
                    known_mask_area_px2_sum=item["known_mask_area_px2_sum"],
                    mask_area_unknown_count=item["mask_area_unknown_count"],
                    boxes_by_source=dict(sorted(item["boxes_by_source"].items())),
                    verified_masks_by_geometry=dict(
                        sorted(item["verified_masks_by_geometry"].items())
                    ),
                )
            )

        classes.sort(
            key=lambda row: (
                row.label_name.casefold(),
                str(row.label_class_id),
            )
        )

        statuses = Counter(proposal.review_status for proposal in proposals)

        snapshot = {
            "version": AGGREGATE_VERSION,
            "image_id": image.id,
            "image_sha256": image.sha256,
            "annotation_revision": image.annotation_revision,
            "annotation_status": image.annotation_status,
            "boxes": [annotation_snapshot(box) for box in boxes],
            "masks": [mask_annotation_snapshot(mask) for mask in masks],
            "proposals": [
                {
                    "id": p.id,
                    "review_status": p.review_status,
                    "model_checksum": p.model_checksum,
                    "label_class_id": p.label_class_id,
                    "predicted_label": p.predicted_label,
                    "geometry_kind": p.geometry_kind,
                    "confidence": p.confidence,
                    "accepted_annotation_id": p.accepted_annotation_id,
                    "accepted_mask_annotation_id": p.accepted_mask_annotation_id,
                }
                for p in proposals
            ],
        }

        return AnnotationImageAggregate(
            schema_version=AGGREGATE_VERSION,
            project_id=UUID(project_id),
            image_id=UUID(image_id),
            image_sha256=image.sha256,
            image_annotation_revision=image.annotation_revision,
            image_annotation_status=image.annotation_status,
            image_width_px=image.width_px,
            image_height_px=image.height_px,
            classes=classes,
            total_saved_box_count=len(boxes),
            total_verified_mask_count=sum(row.verified_mask_count for row in classes),
            total_unverified_mask_count=sum(row.draft_or_unverified_mask_count for row in classes),
            prediction_proposals_by_review_status=dict(sorted(statuses.items())),
            snapshot_sha256=content_hash(snapshot),
            methodological_notes=[
                "Boxes and masks are separate annotation modalities.",
                "Box and mask counts may describe the same organism.",
                "Summed mask area is not union coverage.",
                "Overlapping masks can double-count image pixels.",
                "Physical area requires separate calibration.",
                "Unreviewed predictions are never verified counts.",
                "Image review status affects scientific interpretation.",
                "This is a read-only snapshot, not a saved metric result.",
            ],
        )
