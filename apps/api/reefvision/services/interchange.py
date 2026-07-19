"""Preview, apply, and export external annotation interchange formats."""

from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as element_tree
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Annotation, ImageAsset, LabelClass, MaskAnnotation, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.interchange import (
    InterchangeApplyRequest,
    InterchangeApplyResponse,
    InterchangeCategoryMapping,
    InterchangeExportRequest,
    InterchangeExportResponse,
    InterchangeImageMatch,
    InterchangePreviewRequest,
    InterchangePreviewResponse,
)
from reefvision.services.interchange_parsers import (
    ParsedInterchange,
    SourceCategory,
    parse_interchange,
)
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

_CREATE = "__create__"
_SKIP = "__skip__"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _color_for_name(name: str) -> str:
    digest = hashlib.sha256(name.casefold().encode("utf-8")).digest()
    values = [64 + value % 160 for value in digest[:3]]
    return "#" + "".join(f"{value:02X}" for value in values)


def _polygon_bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    return min(x_values), min(y_values), max(x_values), max(y_values)


def _polygon_area(points: list[list[float]]) -> float:
    return abs(
        sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(points, points[1:] + points[:1], strict=True)
        )
        / 2.0
    )


def _raster_bounds(mask: np.ndarray) -> tuple[float, float, float, float]:
    rows, columns = np.where(mask)
    if rows.size == 0 or columns.size == 0:
        raise ValidationError("Imported raster masks cannot be empty")
    return (
        float(columns.min()),
        float(rows.min()),
        float(columns.max() + 1),
        float(rows.max() + 1),
    )


def _uncompressed_rle(mask: np.ndarray) -> dict[str, Any]:
    height, width = mask.shape
    flattened = mask.astype(np.uint8).T.reshape(-1)
    counts: list[int] = []
    current = 0
    length = 0
    for value in flattened:
        normalized = 1 if value else 0
        if normalized == current:
            length += 1
        else:
            counts.append(length)
            current = normalized
            length = 1
    counts.append(length)
    return {"size": [height, width], "counts": counts}


def _normalized_source(parsed: ParsedInterchange) -> dict[str, Any]:
    return {
        "categories": sorted(
            [{"key": item.key, "name": item.name} for item in parsed.categories],
            key=lambda item: (item["key"], item["name"]),
        ),
        "images": sorted(
            [
                {
                    "key": item.key,
                    "filename": item.filename,
                    "width": item.width,
                    "height": item.height,
                    "reefvision_image_id": item.reefvision_image_id,
                }
                for item in parsed.images
            ],
            key=lambda item: item["key"],
        ),
        "annotations": sorted(
            [
                {
                    "source_id": item.source_id,
                    "image_key": item.image_key,
                    "category_key": item.category_key,
                    "geometry_kind": item.geometry_kind,
                    "bbox": list(item.bbox) if item.bbox else None,
                    "polygon": item.polygon,
                    "raster_sha256": (
                        hashlib.sha256(item.raster.astype(np.uint8).tobytes()).hexdigest()
                        if item.raster is not None
                        else None
                    ),
                    "metadata": item.metadata,
                }
                for item in parsed.annotations
            ],
            key=lambda item: item["source_id"],
        ),
    }


class InterchangeService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _classes(self, project_id: str) -> list[LabelClass]:
        return list(
            self.session.scalars(
                select(LabelClass)
                .where(LabelClass.project_id == project_id)
                .order_by(LabelClass.display_order, LabelClass.class_index, LabelClass.id)
            )
        )

    def _images(self, project_id: str) -> list[ImageAsset]:
        return list(
            self.session.scalars(
                select(ImageAsset)
                .where(ImageAsset.project_id == project_id)
                .order_by(ImageAsset.created_at, ImageAsset.id)
            )
        )

    def _resolve_mappings(
        self,
        categories: list[SourceCategory],
        classes: list[LabelClass],
        request: InterchangePreviewRequest,
    ) -> tuple[list[InterchangeCategoryMapping], dict[str, str]]:
        by_id = {item.id: item for item in classes}
        by_name: dict[str, list[LabelClass]] = defaultdict(list)
        for item in classes:
            by_name[item.name.casefold()].append(item)
        mappings: list[InterchangeCategoryMapping] = []
        resolved: dict[str, str] = {}
        for category in categories:
            explicit = request.class_mapping.get(
                category.key,
                request.class_mapping.get(category.name),
            )
            target: LabelClass | None = None
            resolution = "unmapped"
            message: str | None = None
            if explicit == _SKIP:
                resolution = "skip"
                resolved[category.key] = _SKIP
            elif explicit == _CREATE:
                resolution = "create"
                resolved[category.key] = _CREATE
            elif explicit:
                target = by_id.get(explicit)
                if target is None:
                    resolution = "conflict"
                    message = "The explicitly mapped ReefVision class does not exist."
                else:
                    resolution = "explicit"
                    resolved[category.key] = target.id
            else:
                exact = by_name.get(category.name.casefold(), [])
                if len(exact) == 1:
                    target = exact[0]
                    resolution = "matched"
                    resolved[category.key] = target.id
                elif len(exact) > 1:
                    resolution = "conflict"
                    message = "Multiple ReefVision classes match this category name."
                elif request.create_missing_classes:
                    resolution = "create"
                    resolved[category.key] = _CREATE
                else:
                    resolution = "unmapped"
                    message = "Map this category or enable creation of missing classes."
            mappings.append(
                InterchangeCategoryMapping(
                    source_key=category.key,
                    source_name=category.name,
                    target_class_id=target.id if target else None,
                    target_class_name=target.name if target else None,
                    resolution=resolution,
                    message=message,
                )
            )

        target_sources: dict[str, list[str]] = defaultdict(list)
        for source_key, target_id in resolved.items():
            if target_id not in {_CREATE, _SKIP}:
                target_sources[target_id].append(source_key)
        collisions = {
            target_id: source_keys
            for target_id, source_keys in target_sources.items()
            if len(source_keys) > 1
        }
        if collisions and request.class_conflict_policy != "merge":
            for _target_id, source_keys in collisions.items():
                for mapping in mappings:
                    if mapping.source_key not in source_keys:
                        continue
                    if (
                        request.class_conflict_policy == "skip"
                        and mapping.source_key != source_keys[0]
                    ):
                        mapping.resolution = "skip"
                        mapping.message = (
                            "Skipped because another source category already maps here."
                        )
                        resolved[mapping.source_key] = _SKIP
                    elif request.class_conflict_policy == "error":
                        mapping.resolution = "conflict"
                        mapping.message = (
                            "Multiple source categories map to one ReefVision class; "
                            "choose merge or map them separately."
                        )
                        resolved.pop(mapping.source_key, None)
        return mappings, resolved

    def _match_images(
        self,
        parsed: ParsedInterchange,
        images: list[ImageAsset],
    ) -> tuple[list[InterchangeImageMatch], dict[str, ImageAsset]]:
        by_id = {item.id: item for item in images}
        by_filename: dict[str, list[ImageAsset]] = defaultdict(list)
        for image in images:
            by_filename[Path(image.original_filename).name.casefold()].append(image)
        annotation_counts = Counter(item.image_key for item in parsed.annotations)
        matches: list[InterchangeImageMatch] = []
        resolved: dict[str, ImageAsset] = {}
        for source in parsed.images:
            target: ImageAsset | None = None
            candidates: list[ImageAsset] = []
            if source.reefvision_image_id:
                direct = by_id.get(source.reefvision_image_id)
                candidates = [direct] if direct else []
            if not candidates:
                candidates = by_filename.get(Path(source.filename).name.casefold(), [])
            if len(candidates) == 1:
                target = candidates[0]
                if (
                    source.width is not None
                    and source.height is not None
                    and (source.width != target.width_px or source.height != target.height_px)
                ):
                    status = "dimension_mismatch"
                    message = (
                        f"Source is {source.width}x{source.height}; managed image is "
                        f"{target.width_px}x{target.height_px}."
                    )
                else:
                    status = "matched"
                    message = None
                    resolved[source.key] = target
            elif not candidates:
                status = "missing"
                message = "No managed image matches this filename or ReefVision image ID."
            else:
                status = "ambiguous"
                message = "Multiple managed images share this source filename."
            matches.append(
                InterchangeImageMatch(
                    source_key=source.key,
                    source_filename=source.filename,
                    target_image_id=target.id if target else None,
                    target_filename=target.original_filename if target else None,
                    status=status,
                    annotation_count=annotation_counts[source.key],
                    message=message,
                )
            )
        return matches, resolved

    def preview(
        self,
        project_id: str,
        request: InterchangePreviewRequest,
    ) -> InterchangePreviewResponse:
        self._project(project_id)
        parsed = parse_interchange(request.format, request.document)
        classes = self._classes(project_id)
        images = self._images(project_id)
        mappings, resolved_mappings = self._resolve_mappings(parsed.categories, classes, request)
        image_matches, resolved_images = self._match_images(parsed, images)
        blockers = list(parsed.blockers)
        warnings = list(parsed.warnings)
        blockers.extend(
            mapping.message or "Category mapping conflict"
            for mapping in mappings
            if mapping.resolution in {"conflict", "unmapped"}
        )
        blockers.extend(
            match.message or "Image matching conflict"
            for match in image_matches
            if match.status in {"ambiguous", "dimension_mismatch"}
        )
        missing_matches = [match for match in image_matches if match.status == "missing"]
        if missing_matches:
            warnings.append(
                f"{len(missing_matches)} source images are not present in the "
                "managed project and will be skipped."
            )

        existing_counts: dict[str, int] = {}
        for image_id in {image.id for image in resolved_images.values()}:
            existing_counts[image_id] = len(
                list(
                    self.session.scalars(
                        select(Annotation.id).where(
                            Annotation.image_id == image_id,
                            Annotation.deleted_at.is_(None),
                        )
                    )
                )
            ) + len(
                list(
                    self.session.scalars(
                        select(MaskAnnotation.id).where(
                            MaskAnnotation.image_id == image_id,
                            MaskAnnotation.deleted_at.is_(None),
                        )
                    )
                )
            )
        images_with_existing = [image_id for image_id, count in existing_counts.items() if count]
        if images_with_existing and request.existing_annotation_policy == "error":
            blockers.append(
                f"{len(images_with_existing)} matched images already contain annotations."
            )
        elif images_with_existing and request.existing_annotation_policy == "skip_image":
            warnings.append(
                f"{len(images_with_existing)} matched images will be skipped "
                "because they already contain annotations."
            )
        elif images_with_existing and request.existing_annotation_policy == "append":
            warnings.append(
                "Imported annotations will be appended to images that already contain annotations."
            )

        importable_boxes = 0
        importable_masks = 0
        skipped = 0
        for annotation in parsed.annotations:
            image = resolved_images.get(annotation.image_key)
            target = resolved_mappings.get(annotation.category_key)
            if (
                image is None
                or target in {None, _SKIP}
                or (
                    request.existing_annotation_policy == "skip_image"
                    and existing_counts.get(image.id, 0) > 0
                )
            ):
                skipped += 1
                continue
            if annotation.geometry_kind == "bounding_box":
                importable_boxes += 1
            else:
                importable_masks += 1
        if skipped:
            warnings.append(f"{skipped} annotations are excluded by image or class mapping rules.")

        checksum = canonical_json_sha256(
            {
                "project_id": project_id,
                "format": request.format,
                "source": _normalized_source(parsed),
                "mappings": [item.model_dump(mode="json") for item in mappings],
                "images": [item.model_dump(mode="json") for item in image_matches],
                "create_missing_classes": request.create_missing_classes,
                "class_conflict_policy": request.class_conflict_policy,
                "existing_annotation_policy": request.existing_annotation_policy,
            }
        )
        return InterchangePreviewResponse(
            project_id=project_id,
            format=request.format,
            preview_checksum=checksum,
            valid=not blockers,
            source_category_count=len(parsed.categories),
            matched_category_count=sum(
                item.resolution in {"matched", "explicit"} for item in mappings
            ),
            created_category_count=sum(item.resolution == "create" for item in mappings),
            skipped_category_count=sum(item.resolution == "skip" for item in mappings),
            source_image_count=len(parsed.images),
            matched_image_count=sum(item.status == "matched" for item in image_matches),
            missing_image_count=sum(item.status == "missing" for item in image_matches),
            source_annotation_count=len(parsed.annotations),
            importable_box_count=importable_boxes,
            importable_mask_count=importable_masks,
            mappings=mappings,
            images=image_matches,
            warnings=warnings,
            blockers=blockers,
        )

    def _write_imported_raster(
        self,
        project: Project,
        image: ImageAsset,
        mask: np.ndarray,
        mask_id: str,
    ) -> tuple[str, Path]:
        if mask.shape != (image.height_px, image.width_px):
            raise ValidationError(
                f"Raster mask dimensions {mask.shape[1]}x{mask.shape[0]} do not match "
                f"{image.original_filename} ({image.width_px}x{image.height_px})"
            )
        relative = f"{project.storage_root}/masks/imported/{mask_id}.png"
        path = resolve_managed_project_path(self.settings, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex[:8]}.tmp")
        Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(
            temporary,
            format="PNG",
        )
        temporary.replace(path)
        return relative, path

    def apply(
        self,
        project_id: str,
        request: InterchangeApplyRequest,
    ) -> InterchangeApplyResponse:
        preview_request = InterchangePreviewRequest.model_validate(
            request.model_dump(exclude={"preview_checksum"})
        )
        preview = self.preview(project_id, preview_request)
        if preview.preview_checksum != request.preview_checksum:
            raise ConflictError("The interchange preview is stale; generate a new preview")
        if not preview.valid:
            raise ValidationError("The interchange preview contains blocking conflicts")
        project = self._project(project_id)
        parsed = parse_interchange(request.format, request.document)
        classes = self._classes(project_id)
        category_by_key = {item.key: item for item in parsed.categories}
        class_by_id = {item.id: item for item in classes}
        mapping_by_key = {item.source_key: item for item in preview.mappings}
        image_by_key = {
            match.source_key: self.session.get(ImageAsset, match.target_image_id)
            for match in preview.images
            if match.status == "matched" and match.target_image_id
        }
        created_class_ids: list[str] = []
        resolved_class_ids: dict[str, str] = {}
        next_class_index = max((item.class_index for item in classes), default=-1) + 1
        next_display_order = max((item.display_order for item in classes), default=-1) + 1
        for source_key, mapping in mapping_by_key.items():
            if mapping.resolution in {"matched", "explicit"} and mapping.target_class_id:
                resolved_class_ids[source_key] = mapping.target_class_id
            elif mapping.resolution == "create":
                category = category_by_key[source_key]
                created = LabelClass(
                    project_id=project_id,
                    class_index=next_class_index,
                    display_order=next_display_order,
                    name=category.name,
                    scientific_name=None,
                    state_name=None,
                    description=f"Created during {request.format} import.",
                    display_color=_color_for_name(category.name),
                    is_active=True,
                )
                self.session.add(created)
                self.session.flush()
                resolved_class_ids[source_key] = created.id
                class_by_id[created.id] = created
                created_class_ids.append(created.id)
                next_class_index += 1
                next_display_order += 1

        created_annotation_ids: list[str] = []
        created_mask_ids: list[str] = []
        created_files: list[Path] = []
        affected_images: set[str] = set()
        skipped = 0
        now = datetime.now(UTC)
        replaced_images: set[str] = set()
        try:
            for annotation in parsed.annotations:
                image = image_by_key.get(annotation.image_key)
                class_id = resolved_class_ids.get(annotation.category_key)
                if image is None or class_id is None:
                    skipped += 1
                    continue
                if request.existing_annotation_policy == "skip_image":
                    existing = self.session.scalar(
                        select(Annotation.id).where(
                            Annotation.image_id == image.id,
                            Annotation.deleted_at.is_(None),
                        )
                    ) or self.session.scalar(
                        select(MaskAnnotation.id).where(
                            MaskAnnotation.image_id == image.id,
                            MaskAnnotation.deleted_at.is_(None),
                        )
                    )
                    if existing:
                        skipped += 1
                        continue
                if (
                    request.existing_annotation_policy == "replace_imported"
                    and image.id not in replaced_images
                ):
                    for existing_box in self.session.scalars(
                        select(Annotation).where(
                            Annotation.image_id == image.id,
                            Annotation.deleted_at.is_(None),
                            Annotation.source_type == "external_import",
                        )
                    ):
                        existing_box.deleted_at = now
                    for existing_mask in self.session.scalars(
                        select(MaskAnnotation).where(
                            MaskAnnotation.image_id == image.id,
                            MaskAnnotation.deleted_at.is_(None),
                            MaskAnnotation.source_type == "external_import",
                        )
                    ):
                        existing_mask.deleted_at = now
                    replaced_images.add(image.id)
                provenance = {
                    "interchange_format": request.format,
                    "source_name": request.source_name,
                    "source_annotation_id": annotation.source_id,
                    "source_category_key": annotation.category_key,
                    "preview_checksum": preview.preview_checksum,
                    "source_metadata": annotation.metadata,
                }
                if annotation.geometry_kind == "bounding_box":
                    if annotation.bbox is None:
                        skipped += 1
                        continue
                    x_min, y_min, x_max, y_max = annotation.bbox
                    x_min = max(0.0, min(float(image.width_px), x_min))
                    y_min = max(0.0, min(float(image.height_px), y_min))
                    x_max = max(0.0, min(float(image.width_px), x_max))
                    y_max = max(0.0, min(float(image.height_px), y_max))
                    if x_max <= x_min or y_max <= y_min:
                        skipped += 1
                        continue
                    annotation_id = str(uuid4())
                    self.session.add(
                        Annotation(
                            id=annotation_id,
                            image_id=image.id,
                            label_class_id=class_id,
                            x_min=x_min,
                            y_min=y_min,
                            x_max=x_max,
                            y_max=y_max,
                            source_type="external_import",
                            provenance_json=provenance,
                            created_by="external_import",
                        )
                    )
                    created_annotation_ids.append(annotation_id)
                elif annotation.geometry_kind == "polygon" and annotation.polygon:
                    points = [
                        [
                            max(0.0, min(float(image.width_px), float(point[0]))),
                            max(0.0, min(float(image.height_px), float(point[1]))),
                        ]
                        for point in annotation.polygon
                    ]
                    if len({(point[0], point[1]) for point in points}) < 3:
                        skipped += 1
                        continue
                    x_min, y_min, x_max, y_max = _polygon_bounds(points)
                    mask_id = str(uuid4())
                    self.session.add(
                        MaskAnnotation(
                            id=mask_id,
                            image_id=image.id,
                            label_class_id=class_id,
                            geometry_kind="polygon",
                            polygon_json=points,
                            x_min=x_min,
                            y_min=y_min,
                            x_max=x_max,
                            y_max=y_max,
                            area_pixels=max(1, round(_polygon_area(points))),
                            measurement_json={},
                            source_type="external_import",
                            provenance_json=provenance,
                            status="verified",
                            created_by="external_import",
                        )
                    )
                    created_mask_ids.append(mask_id)
                elif annotation.geometry_kind == "raster_mask" and annotation.raster is not None:
                    mask = np.asarray(annotation.raster, dtype=bool)
                    x_min, y_min, x_max, y_max = _raster_bounds(mask)
                    mask_id = str(uuid4())
                    relative, path = self._write_imported_raster(project, image, mask, mask_id)
                    created_files.append(path)
                    self.session.add(
                        MaskAnnotation(
                            id=mask_id,
                            image_id=image.id,
                            label_class_id=class_id,
                            geometry_kind="raster_mask",
                            mask_path=relative,
                            polygon_json=None,
                            x_min=x_min,
                            y_min=y_min,
                            x_max=x_max,
                            y_max=y_max,
                            area_pixels=int(mask.sum()),
                            measurement_json={
                                "mask_sha256": _file_sha256(path),
                                "width_px": image.width_px,
                                "height_px": image.height_px,
                            },
                            source_type="external_import",
                            provenance_json=provenance,
                            status="verified",
                            created_by="external_import",
                        )
                    )
                    created_mask_ids.append(mask_id)
                else:
                    skipped += 1
                    continue
                affected_images.add(image.id)
            for image_id in affected_images:
                image = self.session.get(ImageAsset, image_id)
                if image is not None:
                    image.annotation_revision += 1
                    if image.annotation_status == "unannotated":
                        image.annotation_status = "in_progress"
            self.session.commit()
        except Exception:
            self.session.rollback()
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
        return InterchangeApplyResponse(
            project_id=project_id,
            format=request.format,
            preview_checksum=preview.preview_checksum,
            created_class_ids=created_class_ids,
            created_annotation_ids=created_annotation_ids,
            created_mask_annotation_ids=created_mask_ids,
            skipped_annotation_count=skipped,
            affected_image_ids=sorted(affected_images),
            warnings=preview.warnings,
        )

    def _load_raster(self, mask: MaskAnnotation, image: ImageAsset) -> np.ndarray:
        if not mask.mask_path:
            raise ValidationError("Raster mask is missing its managed path")
        path = resolve_managed_project_path(self.settings, mask.mask_path)
        if not path.is_file():
            raise ValidationError(f"Managed raster mask is missing: {mask.mask_path}")
        with Image.open(path) as source:
            array = np.asarray(source.convert("L"), dtype=np.uint8) > 0
        if array.shape != (image.height_px, image.width_px):
            raise ValidationError("Raster mask dimensions do not match the source image")
        return array

    def _mask_polygon(
        self,
        mask: MaskAnnotation,
        image: ImageAsset,
        warnings: list[str],
    ) -> list[list[float]]:
        if mask.geometry_kind == "polygon" and mask.polygon_json:
            return [[float(point[0]), float(point[1])] for point in mask.polygon_json]
        array = self._load_raster(mask, image)
        try:
            import cv2

            contours, _hierarchy = cv2.findContours(
                array.astype(np.uint8),
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            if contours:
                contour = max(contours, key=cv2.contourArea).reshape(-1, 2)
                if len(contour) >= 3:
                    return [[float(point[0]), float(point[1])] for point in contour]
        except Exception:
            pass
        x_min, y_min, x_max, y_max = _raster_bounds(array)
        warnings.append(
            f"Raster mask {mask.id} was exported as its bounding polygon because "
            "contour extraction was unavailable."
        )
        return [
            [x_min, y_min],
            [x_max, y_min],
            [x_max, y_max],
            [x_min, y_max],
        ]

    def export(
        self,
        project_id: str,
        request: InterchangeExportRequest,
    ) -> InterchangeExportResponse:
        project = self._project(project_id)
        image_query = select(ImageAsset).where(ImageAsset.project_id == project_id)
        if request.image_ids:
            image_query = image_query.where(ImageAsset.id.in_(request.image_ids))
        images = list(
            self.session.scalars(image_query.order_by(ImageAsset.created_at, ImageAsset.id))
        )
        if request.image_ids and len(images) != len(set(request.image_ids)):
            raise ValidationError("One or more export image IDs are missing")
        class_query = select(LabelClass).where(LabelClass.project_id == project_id)
        if not request.include_archived_classes:
            class_query = class_query.where(LabelClass.archived_at.is_(None))
        classes = list(
            self.session.scalars(class_query.order_by(LabelClass.class_index, LabelClass.id))
        )
        allowed_class_ids = {item.id for item in classes}
        boxes_by_image: dict[str, list[Annotation]] = defaultdict(list)
        masks_by_image: dict[str, list[MaskAnnotation]] = defaultdict(list)
        image_ids = [image.id for image in images]
        if request.include_boxes and image_ids:
            for annotation in self.session.scalars(
                select(Annotation).where(
                    Annotation.image_id.in_(image_ids),
                    Annotation.deleted_at.is_(None),
                    Annotation.label_class_id.in_(allowed_class_ids),
                )
            ):
                boxes_by_image[annotation.image_id].append(annotation)
        if request.include_masks and image_ids:
            for mask in self.session.scalars(
                select(MaskAnnotation).where(
                    MaskAnnotation.image_id.in_(image_ids),
                    MaskAnnotation.deleted_at.is_(None),
                    MaskAnnotation.label_class_id.in_(allowed_class_ids),
                )
            ):
                masks_by_image[mask.image_id].append(mask)

        export_id = str(uuid4())
        relative_root = f"{project.storage_root}/interchange/{export_id}"
        output_root = resolve_managed_project_path(self.settings, relative_root)
        temporary = output_root.with_name(f".{output_root.name}.tmp")
        temporary.mkdir(parents=True, exist_ok=False)
        warnings: list[str] = []
        try:
            image_directory = temporary / "images"
            if request.include_images:
                image_directory.mkdir(parents=True, exist_ok=True)
                for image in images:
                    source = resolve_managed_project_path(self.settings, image.managed_path)
                    if not source.is_file():
                        raise ValidationError(f"Managed image is missing: {image.managed_path}")
                    shutil.copy2(source, image_directory / Path(image.original_filename).name)

            if request.format in {
                "coco_detection",
                "coco_instance",
                "coco_panoptic",
                "roboflow_coco",
            }:
                self._write_coco_export(
                    temporary,
                    request=request,
                    images=images,
                    classes=classes,
                    boxes_by_image=boxes_by_image,
                    masks_by_image=masks_by_image,
                    warnings=warnings,
                )
            elif request.format == "cvat":
                self._write_cvat_export(
                    temporary,
                    images=images,
                    classes=classes,
                    boxes_by_image=boxes_by_image,
                    masks_by_image=masks_by_image,
                    warnings=warnings,
                )
            elif request.format == "labelme":
                self._write_labelme_export(
                    temporary,
                    images=images,
                    classes=classes,
                    boxes_by_image=boxes_by_image,
                    masks_by_image=masks_by_image,
                    warnings=warnings,
                )
            elif request.format == "roboflow_yolo":
                self._write_yolo_export(
                    temporary,
                    images=images,
                    classes=classes,
                    boxes_by_image=boxes_by_image,
                    masks_by_image=masks_by_image,
                    warnings=warnings,
                )
            else:
                raise ValidationError("Unsupported interchange export format")

            manifest = {
                "format": "reefvision-interchange",
                "format_version": "1.0",
                "export_id": export_id,
                "project_id": project_id,
                "interchange_format": request.format,
                "created_at": datetime.now(UTC).isoformat(),
                "image_count": len(images),
                "box_annotation_count": sum(len(items) for items in boxes_by_image.values()),
                "mask_annotation_count": sum(len(items) for items in masks_by_image.values()),
                "class_map": [
                    {
                        "id": item.id,
                        "class_index": item.class_index,
                        "name": item.name,
                        "display_color": item.display_color,
                    }
                    for item in classes
                ],
                "warnings": warnings,
            }
            manifest_path = temporary / "reefvision-manifest.json"
            manifest_path.write_bytes(canonical_json_bytes(manifest))
            archive_path = temporary / "interchange.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(temporary.rglob("*")):
                    if path.is_file() and path != archive_path:
                        archive.write(path, path.relative_to(temporary).as_posix())
            output_root.parent.mkdir(parents=True, exist_ok=True)
            if output_root.exists():
                shutil.rmtree(output_root)
            temporary.replace(output_root)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        final_archive = output_root / "interchange.zip"
        return InterchangeExportResponse(
            project_id=project_id,
            export_id=export_id,
            format=request.format,
            archive_path=f"{relative_root}/interchange.zip",
            manifest_path=f"{relative_root}/reefvision-manifest.json",
            archive_sha256=_file_sha256(final_archive),
            archive_size_bytes=final_archive.stat().st_size,
            image_count=len(images),
            box_annotation_count=sum(len(items) for items in boxes_by_image.values()),
            mask_annotation_count=sum(len(items) for items in masks_by_image.values()),
            warnings=warnings,
        )

    def _write_coco_export(
        self,
        root: Path,
        *,
        request: InterchangeExportRequest,
        images: list[ImageAsset],
        classes: list[LabelClass],
        boxes_by_image: dict[str, list[Annotation]],
        masks_by_image: dict[str, list[MaskAnnotation]],
        warnings: list[str],
    ) -> None:
        category_id = {item.id: index + 1 for index, item in enumerate(classes)}
        image_id = {item.id: index + 1 for index, item in enumerate(images)}
        categories = [
            {
                "id": category_id[item.id],
                "name": item.name,
                "supercategory": item.scientific_name or "reefvision",
                "reefvision_label_class_id": item.id,
            }
            for item in classes
        ]
        image_records = [
            {
                "id": image_id[item.id],
                "file_name": (
                    f"images/{Path(item.original_filename).name}"
                    if request.include_images
                    else Path(item.original_filename).name
                ),
                "width": item.width_px,
                "height": item.height_px,
                "reefvision_image_id": item.id,
                "reefvision_image_sha256": item.sha256,
            }
            for item in images
        ]
        if request.format == "coco_panoptic":
            annotations: list[dict[str, Any]] = []
            panoptic_directory = root / "panoptic"
            panoptic_directory.mkdir(parents=True, exist_ok=True)
            segment_id = 1
            for image in images:
                ids = np.zeros((image.height_px, image.width_px), dtype=np.int64)
                segments: list[dict[str, Any]] = []
                geometries: list[tuple[str, Any, str]] = []
                geometries.extend(
                    ("box", item, item.label_class_id) for item in boxes_by_image[image.id]
                )
                geometries.extend(
                    ("mask", item, str(item.label_class_id))
                    for item in masks_by_image[image.id]
                    if item.label_class_id
                )
                for geometry_kind, geometry, label_class_id in geometries:
                    if geometry_kind == "box":
                        mask_array = np.zeros_like(ids, dtype=bool)
                        x_min = max(0, int(np.floor(geometry.x_min)))
                        y_min = max(0, int(np.floor(geometry.y_min)))
                        x_max = min(image.width_px, int(np.ceil(geometry.x_max)))
                        y_max = min(image.height_px, int(np.ceil(geometry.y_max)))
                        mask_array[y_min:y_max, x_min:x_max] = True
                    elif geometry.geometry_kind == "raster_mask":
                        mask_array = self._load_raster(geometry, image)
                    else:
                        mask_image = Image.new("1", (image.width_px, image.height_px), 0)
                        draw = ImageDraw.Draw(mask_image)
                        draw.polygon(
                            [
                                (float(point[0]), float(point[1]))
                                for point in geometry.polygon_json or []
                            ],
                            fill=1,
                        )
                        mask_array = np.asarray(mask_image, dtype=bool)
                    if not mask_array.any():
                        continue
                    ids[mask_array] = segment_id
                    y_values, x_values = np.where(mask_array)
                    segments.append(
                        {
                            "id": segment_id,
                            "category_id": category_id[label_class_id],
                            "area": int(mask_array.sum()),
                            "bbox": [
                                int(x_values.min()),
                                int(y_values.min()),
                                int(x_values.max() - x_values.min() + 1),
                                int(y_values.max() - y_values.min() + 1),
                            ],
                            "iscrowd": 0,
                        }
                    )
                    segment_id += 1
                filename = f"{image_id[image.id]:08d}.png"
                rgb = np.stack(
                    [ids % 256, (ids // 256) % 256, (ids // 65536) % 256],
                    axis=-1,
                ).astype(np.uint8)
                Image.fromarray(rgb, mode="RGB").save(panoptic_directory / filename)
                annotations.append(
                    {
                        "image_id": image_id[image.id],
                        "file_name": f"panoptic/{filename}",
                        "segments_info": segments,
                    }
                )
            payload = {
                "info": {"description": "ReefVision panoptic export"},
                "images": image_records,
                "categories": categories,
                "annotations": annotations,
            }
            (root / "panoptic.json").write_bytes(canonical_json_bytes(payload))
            return

        annotations: list[dict[str, Any]] = []
        annotation_id = 1
        for image in images:
            for box in boxes_by_image[image.id]:
                annotations.append(
                    {
                        "id": annotation_id,
                        "image_id": image_id[image.id],
                        "category_id": category_id[box.label_class_id],
                        "bbox": [
                            box.x_min,
                            box.y_min,
                            box.x_max - box.x_min,
                            box.y_max - box.y_min,
                        ],
                        "area": (box.x_max - box.x_min) * (box.y_max - box.y_min),
                        "segmentation": [],
                        "iscrowd": 0,
                        "reefvision_annotation_id": box.id,
                    }
                )
                annotation_id += 1
            if request.format == "coco_detection":
                continue
            for mask in masks_by_image[image.id]:
                if not mask.label_class_id:
                    continue
                if mask.geometry_kind == "polygon" and mask.polygon_json:
                    points = [[float(point[0]), float(point[1])] for point in mask.polygon_json]
                    segmentation: Any = [[coordinate for point in points for coordinate in point]]
                    x_min, y_min, x_max, y_max = _polygon_bounds(points)
                    area = _polygon_area(points)
                else:
                    raster = self._load_raster(mask, image)
                    segmentation = _uncompressed_rle(raster)
                    x_min, y_min, x_max, y_max = _raster_bounds(raster)
                    area = float(raster.sum())
                annotations.append(
                    {
                        "id": annotation_id,
                        "image_id": image_id[image.id],
                        "category_id": category_id[mask.label_class_id],
                        "bbox": [x_min, y_min, x_max - x_min, y_max - y_min],
                        "area": area,
                        "segmentation": segmentation,
                        "iscrowd": 0,
                        "reefvision_mask_annotation_id": mask.id,
                    }
                )
                annotation_id += 1
        payload = {
            "info": {"description": "ReefVision COCO interchange export"},
            "licenses": [],
            "images": image_records,
            "annotations": annotations,
            "categories": categories,
        }
        filename = "roboflow-coco.json" if request.format == "roboflow_coco" else "annotations.json"
        (root / filename).write_bytes(canonical_json_bytes(payload))

    def _write_cvat_export(
        self,
        root: Path,
        *,
        images: list[ImageAsset],
        classes: list[LabelClass],
        boxes_by_image: dict[str, list[Annotation]],
        masks_by_image: dict[str, list[MaskAnnotation]],
        warnings: list[str],
    ) -> None:
        class_by_id = {item.id: item for item in classes}
        annotations = element_tree.Element("annotations")
        meta = element_tree.SubElement(annotations, "meta")
        task = element_tree.SubElement(meta, "task")
        labels = element_tree.SubElement(task, "labels")
        for label_class in classes:
            label = element_tree.SubElement(labels, "label")
            element_tree.SubElement(label, "name").text = label_class.name
            element_tree.SubElement(label, "color").text = label_class.display_color
        for index, image in enumerate(images):
            image_element = element_tree.SubElement(
                annotations,
                "image",
                {
                    "id": str(index),
                    "name": Path(image.original_filename).name,
                    "width": str(image.width_px),
                    "height": str(image.height_px),
                },
            )
            for box in boxes_by_image[image.id]:
                element_tree.SubElement(
                    image_element,
                    "box",
                    {
                        "label": class_by_id[box.label_class_id].name,
                        "xtl": str(box.x_min),
                        "ytl": str(box.y_min),
                        "xbr": str(box.x_max),
                        "ybr": str(box.y_max),
                        "occluded": "0",
                    },
                )
            for mask in masks_by_image[image.id]:
                if not mask.label_class_id:
                    continue
                polygon = self._mask_polygon(mask, image, warnings)
                element_tree.SubElement(
                    image_element,
                    "polygon",
                    {
                        "label": class_by_id[mask.label_class_id].name,
                        "points": ";".join(f"{point[0]},{point[1]}" for point in polygon),
                        "occluded": "0",
                    },
                )
        element_tree.ElementTree(annotations).write(
            root / "annotations.xml",
            encoding="utf-8",
            xml_declaration=True,
        )

    def _write_labelme_export(
        self,
        root: Path,
        *,
        images: list[ImageAsset],
        classes: list[LabelClass],
        boxes_by_image: dict[str, list[Annotation]],
        masks_by_image: dict[str, list[MaskAnnotation]],
        warnings: list[str],
    ) -> None:
        class_by_id = {item.id: item for item in classes}
        labels_directory = root / "labelme"
        labels_directory.mkdir(parents=True, exist_ok=True)
        for image in images:
            shapes: list[dict[str, Any]] = []
            for box in boxes_by_image[image.id]:
                shapes.append(
                    {
                        "label": class_by_id[box.label_class_id].name,
                        "points": [[box.x_min, box.y_min], [box.x_max, box.y_max]],
                        "group_id": None,
                        "shape_type": "rectangle",
                        "flags": {},
                    }
                )
            for mask in masks_by_image[image.id]:
                if not mask.label_class_id:
                    continue
                shapes.append(
                    {
                        "label": class_by_id[mask.label_class_id].name,
                        "points": self._mask_polygon(mask, image, warnings),
                        "group_id": None,
                        "shape_type": "polygon",
                        "flags": {},
                    }
                )
            payload = {
                "version": "5.0.0",
                "flags": {},
                "shapes": shapes,
                "imagePath": Path(image.original_filename).name,
                "imageData": None,
                "imageHeight": image.height_px,
                "imageWidth": image.width_px,
                "reefvision_image_id": image.id,
            }
            filename = f"{Path(image.original_filename).stem}.json"
            (labels_directory / filename).write_bytes(canonical_json_bytes(payload))

    def _write_yolo_export(
        self,
        root: Path,
        *,
        images: list[ImageAsset],
        classes: list[LabelClass],
        boxes_by_image: dict[str, list[Annotation]],
        masks_by_image: dict[str, list[MaskAnnotation]],
        warnings: list[str],
    ) -> None:
        labels_directory = root / "labels"
        labels_directory.mkdir(parents=True, exist_ok=True)
        class_index = {item.id: index for index, item in enumerate(classes)}
        for image in images:
            lines: list[str] = []
            for box in boxes_by_image[image.id]:
                center_x = ((box.x_min + box.x_max) / 2.0) / image.width_px
                center_y = ((box.y_min + box.y_max) / 2.0) / image.height_px
                width = (box.x_max - box.x_min) / image.width_px
                height = (box.y_max - box.y_min) / image.height_px
                lines.append(
                    f"{class_index[box.label_class_id]} {center_x:.8f} "
                    f"{center_y:.8f} {width:.8f} {height:.8f}"
                )
            for mask in masks_by_image[image.id]:
                if not mask.label_class_id:
                    continue
                polygon = self._mask_polygon(mask, image, warnings)
                coordinates = " ".join(
                    f"{point[0] / image.width_px:.8f} {point[1] / image.height_px:.8f}"
                    for point in polygon
                )
                lines.append(f"{class_index[mask.label_class_id]} {coordinates}")
            (labels_directory / f"{Path(image.original_filename).stem}.txt").write_text(
                "\n".join(lines) + ("\n" if lines else ""),
                encoding="utf-8",
            )
        (root / "data.yaml").write_text(
            "path: .\ntrain: images\nval: images\nnames:\n"
            + "".join(
                f"  {index}: {json.dumps(item.name)}\n" for index, item in enumerate(classes)
            ),
            encoding="utf-8",
        )
