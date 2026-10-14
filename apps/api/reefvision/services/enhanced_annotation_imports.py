"""Lossless CoralNet-Toolbox annotation import extensions for Milestone 2."""

from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from contextlib import suppress
from io import BytesIO
from pathlib import PureWindowsPath
from typing import Any, BinaryIO

import yaml
from PIL import Image, ImageChops, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    MaskAnnotationEvent,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.annotation_imports import AnnotationImportIssue, AnnotationImportResponse
from reefvision.schemas.annotations import MaskAnnotationDraft, PolygonPoint
from reefvision.services.annotation_format_adapters import (
    convert_coco,
    convert_yolo,
    is_coco,
    yolo_names,
)
from reefvision.services.annotation_imports import AnnotationImportService
from reefvision.services.annotations import mask_annotation_snapshot
from reefvision.storage.masks import write_mask_png


class EnhancedAnnotationImportService(AnnotationImportService):
    """Add lossless hole and CoralNet semantic-mask handling to the base importer."""

    LOCK_BIT = 128

    def __init__(self, session: Session, settings: Settings) -> None:
        super().__init__(session, settings)

    @staticmethod
    def _stream_bytes(stream: BinaryIO) -> bytes:
        value = stream.read()
        if isinstance(value, str):
            return value.encode("utf-8")
        return value

    @staticmethod
    def _decode_coco_counts(encoded_counts: object) -> list[int]:
        if not isinstance(encoded_counts, str) or not encoded_counts:
            raise ValidationError("Semantic mask RLE counts are missing")
        try:
            compressed = base64.b64decode(encoded_counts, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("Semantic mask RLE counts are not valid base64") from exc

        counts: list[int] = []
        position = 0
        while position < len(compressed):
            value = 0
            shift = 0
            more = True
            last_chunk = 0
            while more:
                if position >= len(compressed):
                    raise ValidationError("Semantic mask RLE counts are truncated")
                chunk = int(compressed[position]) - 48
                position += 1
                if chunk < 0 or chunk > 0x3F:
                    raise ValidationError("Semantic mask RLE counts contain invalid data")
                value |= (chunk & 0x1F) << (5 * shift)
                more = bool(chunk & 0x20)
                last_chunk = chunk
                shift += 1
            if last_chunk & 0x10:
                value |= -1 << (5 * shift)
            if len(counts) > 2:
                value += counts[-2]
            if value < 0:
                raise ValidationError("Semantic mask RLE contains a negative run length")
            counts.append(value)
        return counts

    @classmethod
    def _decode_rle_image(cls, rle_value: object) -> Image.Image:
        if not isinstance(rle_value, dict):
            raise ValidationError("Semantic mask RLE entry is malformed")
        raw_size = rle_value.get("size")
        if not isinstance(raw_size, (list, tuple)) or len(raw_size) != 2:
            raise ValidationError("Semantic mask RLE size is missing")
        try:
            height = int(raw_size[0])
            width = int(raw_size[1])
        except (TypeError, ValueError) as exc:
            raise ValidationError("Semantic mask RLE size is malformed") from exc
        if height <= 0 or width <= 0:
            raise ValidationError("Semantic mask RLE dimensions must be positive")

        counts = cls._decode_coco_counts(rle_value.get("counts"))
        total = height * width
        flat_fortran = bytearray(total)
        offset = 0
        foreground = False
        for run_length in counts:
            end = offset + run_length
            if end > total:
                raise ValidationError("Semantic mask RLE exceeds its declared dimensions")
            if foreground and run_length:
                flat_fortran[offset:end] = b"\xff" * run_length
            offset = end
            foreground = not foreground
        if offset != total:
            raise ValidationError("Semantic mask RLE does not fill its declared dimensions")

        # COCO RLE is column-major. Interpreting it as a width=height temporary
        # image and transposing recovers the original (width, height) raster.
        temporary = Image.frombytes("L", (height, width), bytes(flat_fortran))
        return temporary.transpose(Image.Transpose.TRANSPOSE)

    @classmethod
    def _semantic_class_masks(
        cls,
        annotation: dict[str, Any],
        image: ImageAsset,
    ) -> dict[int, Image.Image]:
        raw_shape = annotation.get("shape")
        if not isinstance(raw_shape, (list, tuple)) or len(raw_shape) != 2:
            raise ValidationError("Semantic MaskAnnotation is missing its image shape")
        try:
            height = int(raw_shape[0])
            width = int(raw_shape[1])
        except (TypeError, ValueError) as exc:
            raise ValidationError("Semantic MaskAnnotation shape is malformed") from exc
        if (width, height) != (image.width_px, image.height_px):
            raise ValidationError(
                "Semantic MaskAnnotation dimensions do not match the ReefVision image"
            )

        raw_masks = annotation.get("rle_masks")
        if not isinstance(raw_masks, list):
            raise ValidationError("Semantic MaskAnnotation is missing its RLE masks")

        class_masks: dict[int, Image.Image] = {}
        for item in raw_masks:
            if not isinstance(item, dict):
                raise ValidationError("Semantic MaskAnnotation contains a malformed RLE item")
            try:
                stored_class_id = int(str(item.get("class_id")))
            except (TypeError, ValueError) as exc:
                raise ValidationError("Semantic MaskAnnotation class ID is malformed") from exc
            real_class_id = stored_class_id % cls.LOCK_BIT
            if real_class_id == 0:
                continue

            decoded = cls._decode_rle_image(item.get("rle"))
            bbox = item.get("bbox")
            if bbox is None:
                if decoded.size != (width, height):
                    raise ValidationError("Legacy semantic RLE dimensions do not match the image")
                full_mask = decoded
            else:
                if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    raise ValidationError("Semantic mask crop RLE has a malformed bounding box")
                try:
                    x_min, y_min, x_max, y_max = [int(value) for value in bbox]
                except (TypeError, ValueError) as exc:
                    raise ValidationError("Semantic mask crop bounding box is malformed") from exc
                if not (0 <= x_min <= x_max < width and 0 <= y_min <= y_max < height):
                    raise ValidationError("Semantic mask crop bounding box falls outside the image")
                expected_crop_size = (x_max - x_min + 1, y_max - y_min + 1)
                if decoded.size != expected_crop_size:
                    raise ValidationError("Semantic mask crop RLE does not match its bounding box")
                full_mask = Image.new("L", (width, height), 0)
                full_mask.paste(decoded, (x_min, y_min))

            existing = class_masks.get(real_class_id)
            class_masks[real_class_id] = (
                full_mask if existing is None else ImageChops.lighter(existing, full_mask)
            )
        return class_masks

    @staticmethod
    def _label_map_value(label_map: object, stored_class_id: int) -> str:
        if not isinstance(label_map, dict):
            return ""
        candidates: tuple[object, ...] = (
            stored_class_id,
            str(stored_class_id),
            stored_class_id % EnhancedAnnotationImportService.LOCK_BIT,
            str(stored_class_id % EnhancedAnnotationImportService.LOCK_BIT),
        )
        for candidate in candidates:
            value = label_map.get(candidate)
            if value:
                return str(value)
        return ""

    def _add_raster_mask(
        self,
        *,
        project_id: str,
        image: ImageAsset,
        label_class: LabelClass,
        annotation: dict[str, Any],
        source_file: str,
        image_reference: str,
        external_type: str,
        raster: Image.Image,
        suffix: str,
        extra_provenance: dict[str, Any] | None = None,
    ) -> str:
        annotation_id = self._stable_id(project_id, annotation.get("id"), suffix)
        if self.session.get(MaskAnnotation, annotation_id) is not None:
            return "duplicate"
        if self.session.get(Annotation, annotation_id) is not None:
            return "duplicate"

        binary = raster.convert("L").point(lambda value: 255 if value > 0 else 0)
        if binary.size != (image.width_px, image.height_px):
            raise ValidationError("Imported raster mask dimensions do not match the source image")
        if binary.getbbox() is None:
            raise ValidationError("Imported raster mask is empty")

        project = self._project(project_id)
        stream = BytesIO()
        binary.save(stream, format="PNG", optimize=True)
        destination = None
        try:
            (
                relative_mask_path,
                destination,
                area_pixels,
                x_min,
                y_min,
                x_max,
                y_max,
            ) = write_mask_png(
                self.settings,
                project_storage_root=project.storage_root,
                image_id=image.id,
                mask_annotation_id=annotation_id,
                png_base64=base64.b64encode(stream.getvalue()).decode("ascii"),
                expected_width=image.width_px,
                expected_height=image.height_px,
            )
            record = MaskAnnotation(
                id=annotation_id,
                image_id=image.id,
                label_class_id=label_class.id,
                geometry_kind="raster_mask",
                mask_path=relative_mask_path,
                polygon_json=None,
                x_min=x_min,
                y_min=y_min,
                x_max=x_max,
                y_max=y_max,
                area_pixels=area_pixels,
                source_type="imported",
                provenance_json=self._provenance(
                    source_file=source_file,
                    annotation=annotation,
                    external_type=external_type,
                    image_reference=image_reference,
                    extra=extra_provenance,
                ),
                status="verified" if bool(annotation.get("verified", True)) else "needs_review",
                created_by="coralnet_toolbox_importer",
                revision=1,
            )
            self.session.add(record)
            self.session.flush()
            self.session.add(
                MaskAnnotationEvent(
                    mask_annotation_id=record.id,
                    image_id=image.id,
                    event_type="imported",
                    before_json=None,
                    after_json=mask_annotation_snapshot(record),
                    actor="coralnet_toolbox_importer",
                )
            )
            return "imported"
        except Exception:
            if destination is not None:
                destination.unlink(missing_ok=True)
            raise

    def _validated_ring(
        self,
        points_value: object,
        image: ImageAsset,
    ) -> list[tuple[float, float]]:
        if not isinstance(points_value, list):
            raise ValidationError("Polygon ring has no point list")
        parsed = [self._point_pair(point) for point in points_value]
        if any(point is None for point in parsed):
            raise ValidationError("Polygon ring contains malformed coordinates")
        points = self._strip_closing_point([point for point in parsed if point is not None])
        draft = MaskAnnotationDraft(
            id="ring-validation",
            label_class_id="ring-validation",
            geometry_kind="polygon",
            points=[PolygonPoint(x=x, y=y) for x, y in points],
        )
        self.annotation_service._validated_polygon(draft, image)
        return points

    def _add_polygon(
        self,
        *,
        project_id: str,
        image: ImageAsset,
        label_class: LabelClass,
        annotation: dict[str, Any],
        source_file: str,
        image_reference: str,
        external_type: str,
        points_value: object,
        holes_value: object,
        suffix: str = "",
        extra_provenance: dict[str, Any] | None = None,
    ) -> str:
        holes = holes_value if isinstance(holes_value, list) else []
        if not holes:
            return super()._add_polygon(
                project_id=project_id,
                image=image,
                label_class=label_class,
                annotation=annotation,
                source_file=source_file,
                image_reference=image_reference,
                external_type=external_type,
                points_value=points_value,
                holes_value=holes,
                suffix=suffix,
                extra_provenance=extra_provenance,
            )

        exterior = self._validated_ring(points_value, image)
        interior_rings = [self._validated_ring(hole, image) for hole in holes]
        raster = Image.new("L", (image.width_px, image.height_px), 0)
        draw = ImageDraw.Draw(raster)
        draw.polygon(exterior, fill=255)
        for ring in interior_rings:
            draw.polygon(ring, fill=0)
        provenance = {
            **(extra_provenance or {}),
            "external_polygon_holes_preserved": True,
            "external_polygon_hole_count": len(interior_rings),
            "external_polygon_exterior": [[x, y] for x, y in exterior],
            "external_polygon_holes": [[[x, y] for x, y in ring] for ring in interior_rings],
            "conversion": "rasterized_polygon_with_holes",
        }
        return self._add_raster_mask(
            project_id=project_id,
            image=image,
            label_class=label_class,
            annotation=annotation,
            source_file=source_file,
            image_reference=image_reference,
            external_type=external_type,
            raster=raster,
            suffix=suffix or "polygon-with-holes",
            extra_provenance=provenance,
        )

    def _semantic_annotation_metadata(
        self,
        annotation: dict[str, Any],
        *,
        short_code: str,
        class_mapping: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        metadata = dict(annotation)
        mapping_entry = class_mapping.get(short_code)
        if mapping_entry is None:
            normalized = self._normalize_label(short_code)
            mapping_entry = next(
                (
                    value
                    for key, value in class_mapping.items()
                    if self._normalize_label(key) == normalized
                    or self._normalize_label(value.get("short_label_code")) == normalized
                ),
                None,
            )
        metadata["label_short_code"] = short_code
        if mapping_entry is not None:
            metadata["label_id"] = mapping_entry.get("id")
            metadata["label_long_code"] = mapping_entry.get("long_label_code")
            metadata["annotation_color"] = mapping_entry.get("color")
        else:
            metadata["label_long_code"] = short_code
        return metadata

    @classmethod
    def _decode_external_coco_rle(cls, segmentation: object) -> Image.Image:
        if not isinstance(segmentation, dict):
            raise ValidationError("COCO RLE mask must be an object")
        size = segmentation.get("size")
        if not isinstance(size, list) or len(size) != 2:
            raise ValidationError("COCO RLE requires [height,width]")
        height, width = int(size[0]), int(size[1])
        if height <= 0 or width <= 0:
            raise ValidationError("COCO RLE dimensions must be positive")
        counts = segmentation.get("counts")
        if isinstance(counts, str):
            # Standard COCO encoded RLE is ASCII. The legacy CoralNet decoder
            # accepts base64-wrapped COCO bytes; convert the representation.
            return cls._decode_rle_image(
                {
                    "size": [height, width],
                    "counts": base64.b64encode(counts.encode("ascii")).decode("ascii"),
                }
            )
        if isinstance(counts, list):
            raster = bytearray(height * width)
            offset = 0
            for index, raw_length in enumerate(counts):
                if not isinstance(raw_length, int) or raw_length < 0:
                    raise ValidationError("COCO run lengths must be nonnegative integers")
                end = offset + raw_length
                if end > len(raster):
                    raise ValidationError("COCO RLE exceeds the declared dimensions")
                if index % 2:
                    raster[offset:end] = bytes([255]) * raw_length
                offset = end
            if offset != len(raster):
                raise ValidationError("COCO RLE does not fill the declared dimensions")
            return Image.frombytes("L", (height, width), bytes(raster)).transpose(
                Image.Transpose.TRANSPOSE
            )
        raise ValidationError("COCO RLE counts must be an ASCII string or integer list")

    def import_streams(
        self,
        project_id: str,
        uploads: list[tuple[str | None, BinaryIO]],
    ) -> AnnotationImportResponse:
        buffered: list[tuple[str, bytes]] = []
        for raw_filename, stream in uploads:
            buffered.append((str(raw_filename or "annotations.json"), self._stream_bytes(stream)))

        # Resolve YOLO data.yaml even when uploaded after .txt files.
        names_by_index: dict[int, str] = {}
        for filename, data in buffered:
            if filename.casefold().endswith((".yaml", ".yml")):
                with suppress(ValueError, TypeError, yaml.YAMLError):
                    names_by_index.update(yolo_names(yaml.safe_load(data)))
        known_images: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
        for item in self.session.scalars(
            select(ImageAsset).where(ImageAsset.project_id == project_id)
        ):
            stem = PureWindowsPath(item.original_filename).stem.casefold()
            known_images[stem].append((item.original_filename, item.width_px, item.height_px))

        before_revisions = {
            image.id: image.annotation_revision
            for image in self.session.scalars(
                select(ImageAsset).where(ImageAsset.project_id == project_id)
            )
        }
        class_mapping: dict[str, dict[str, Any]] = {}
        dataset_indices: dict[str, int] = {}
        semantic_annotations: list[tuple[str, str, dict[str, Any]]] = []
        coco_rle_annotations: list[tuple[str, str, str, dict[str, Any]]] = []
        import_warnings: list[AnnotationImportIssue] = []
        external_class_names: set[str] = set(names_by_index.values())
        base_uploads: list[tuple[str | None, BinaryIO]] = []

        for filename, data in buffered:
            if filename.casefold().endswith((".txt",)):
                if not names_by_index:
                    import_warnings.append(
                        AnnotationImportIssue(
                            source_file=filename,
                            detail="YOLO TXT requires a companion data.yaml with class names",
                        )
                    )
                    continue
                try:
                    converted, warnings = convert_yolo(
                        filename, data.decode("utf-8-sig"), names_by_index, known_images
                    )
                except UnicodeDecodeError as exc:
                    import_warnings.append(
                        AnnotationImportIssue(
                            source_file=filename, detail=f"Invalid YOLO UTF-8 text: {exc}"
                        )
                    )
                    continue
                import_warnings.extend(
                    AnnotationImportIssue(source_file=filename, detail=warning)
                    for warning in warnings
                )
                if converted:
                    base_uploads.append(
                        (
                            filename + ".json",
                            BytesIO(json.dumps(converted).encode("utf-8")),
                        )
                    )
                continue
            if filename.casefold().endswith((".yaml", ".yml")):
                with suppress(yaml.YAMLError):
                    dataset_indices.update(self._parse_dataset_names(yaml.safe_load(data)))
                base_uploads.append((filename, BytesIO(data)))
                continue
            try:
                payload = self._as_mapping(json.loads(data.decode("utf-8-sig")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if payload is not None and is_coco(payload):
                try:
                    converted, mapping, warnings, rle_masks = convert_coco(payload, filename)
                except (ValidationError, ValueError, KeyError, TypeError) as exc:
                    import_warnings.append(
                        AnnotationImportIssue(
                            source_file=filename, detail=f"Invalid COCO JSON: {exc}"
                        )
                    )
                    continue
                class_mapping.update(mapping)
                external_class_names.update(mapping)
                coco_rle_annotations.extend(
                    (filename, image_ref, label, annotation)
                    for image_ref, label, annotation in rle_masks
                )
                import_warnings.extend(
                    AnnotationImportIssue(source_file=filename, detail=warning)
                    for warning in warnings
                )
                if converted:
                    base_uploads.append(
                        (
                            filename + ".converted.json",
                            BytesIO(json.dumps(converted).encode("utf-8")),
                        )
                    )
                continue
            if payload is not None and self._looks_like_class_mapping(payload):
                class_mapping.update(
                    {str(key): value for key, value in payload.items() if isinstance(value, dict)}
                )
                external_class_names.update(
                    str(value.get("long_label_code") or value.get("short_label_code") or key)
                    for key, value in payload.items()
                    if isinstance(value, dict)
                )
                base_uploads.append((filename, BytesIO(data)))
                continue
            if payload is not None and self._looks_like_annotations(payload):
                filtered: dict[str, list[Any]] = {}
                for image_reference, entries in payload.items():
                    vector_entries: list[Any] = []
                    for entry in entries:
                        is_semantic = (
                            isinstance(entry, dict)
                            and str(entry.get("type") or "") == "MaskAnnotation"
                        )
                        if is_semantic:
                            semantic_annotations.append((filename, str(image_reference), entry))
                        else:
                            vector_entries.append(entry)
                    filtered[str(image_reference)] = vector_entries
                base_uploads.append((filename, BytesIO(json.dumps(filtered).encode("utf-8"))))
                continue
            base_uploads.append((filename, BytesIO(data)))

        # Converted external annotations include their resolved class labels.
        # A synthetic mapping file would double-count class mappings supplied
        # by a user and is not needed to preserve COCO/YOLO label identities.
        report = super().import_streams(project_id, base_uploads)

        # Transfer class catalogs even when some classes have zero annotations.
        # The SQLAlchemy Project.label_classes relationship can remain cached
        # after the base importer created labels through this same session.
        # Query current rows directly to avoid duplicate class-name inserts.
        project_classes = list(
            self.session.scalars(select(LabelClass).where(LabelClass.project_id == project_id))
        )
        precreated_class_ids: set[str] = set()
        catalog_matched: set[str] = set()
        for label in sorted(external_class_names):
            if not label or not label.strip():
                continue
            self._ensure_class(
                project_id=project_id,
                annotation={
                    "label_short_code": label,
                    "label_long_code": label,
                    "label_id": class_mapping.get(label, {}).get("id"),
                },
                class_mapping=class_mapping,
                dataset_indices=dataset_indices,
                project_classes=project_classes,
                matched_class_ids=catalog_matched,
                created_class_ids=precreated_class_ids,
            )
        if precreated_class_ids:
            self.session.commit()

        if not semantic_annotations and not coco_rle_annotations:
            return report.model_copy(
                update={
                    "files_processed": len(buffered),
                    "classes_created": report.classes_created + len(precreated_class_ids),
                    "issues": [*report.issues, *import_warnings],
                }
            )

        project_classes = list(
            self.session.scalars(select(LabelClass).where(LabelClass.project_id == project_id))
        )
        by_basename, by_import_source = self._images_by_reference(project_id)
        matched_class_ids: set[str] = set()
        created_class_ids: set[str] = set()
        semantic_modified: dict[str, bool] = {}
        semantic_imported = 0
        semantic_duplicates = 0
        semantic_unknown_classes = 0
        semantic_skipped = 0
        semantic_unmatched: set[str] = set()
        semantic_issues: list[AnnotationImportIssue] = []

        for source_file, image_reference, annotation in semantic_annotations:
            image = self._match_image(image_reference, by_basename, by_import_source)
            if image is None:
                semantic_unmatched.add(image_reference)
                semantic_issues.append(
                    AnnotationImportIssue(
                        source_file=source_file,
                        image_reference=image_reference,
                        annotation_id=str(annotation.get("id") or "") or None,
                        detail="No unique ReefVision image matched this CoralNet image path",
                    )
                )
                continue
            try:
                class_masks = self._semantic_class_masks(annotation, image)
                label_map = annotation.get("label_map")
                for real_class_id, raster in class_masks.items():
                    short_code = self._label_map_value(label_map, real_class_id)
                    if not short_code:
                        semantic_unknown_classes += 1
                        semantic_skipped += 1
                        semantic_issues.append(
                            AnnotationImportIssue(
                                source_file=source_file,
                                image_reference=image_reference,
                                annotation_id=str(annotation.get("id") or "") or None,
                                detail=f"Semantic class {real_class_id} has no label-map entry",
                            )
                        )
                        continue
                    metadata = self._semantic_annotation_metadata(
                        annotation,
                        short_code=short_code,
                        class_mapping=class_mapping,
                    )
                    label_class = self._ensure_class(
                        project_id=project_id,
                        annotation=metadata,
                        class_mapping=class_mapping,
                        dataset_indices=dataset_indices,
                        project_classes=project_classes,
                        matched_class_ids=matched_class_ids,
                        created_class_ids=created_class_ids,
                    )
                    if label_class is None:
                        semantic_unknown_classes += 1
                        semantic_skipped += 1
                        continue
                    result = self._add_raster_mask(
                        project_id=project_id,
                        image=image,
                        label_class=label_class,
                        annotation=metadata,
                        source_file=source_file,
                        image_reference=image_reference,
                        external_type="MaskAnnotation",
                        raster=raster,
                        suffix=f"semantic-class-{real_class_id}",
                        extra_provenance={
                            "external_semantic_class_id": real_class_id,
                            "external_semantic_short_code": short_code,
                            "external_semantic_shape": annotation.get("shape"),
                            "external_semantic_rle": True,
                            "external_lock_bit_normalized": self.LOCK_BIT,
                        },
                    )
                    if result == "duplicate":
                        semantic_duplicates += 1
                    else:
                        semantic_imported += 1
                        verified = bool(annotation.get("verified", True))
                        semantic_modified[image.id] = (
                            semantic_modified.get(image.id, True) and verified
                        )
            except (ValidationError, ValueError, TypeError) as exc:
                semantic_skipped += 1
                semantic_issues.append(
                    AnnotationImportIssue(
                        source_file=source_file,
                        image_reference=image_reference,
                        annotation_id=str(annotation.get("id") or "") or None,
                        detail=str(exc),
                    )
                )

        # COCO polygon/box annotations went through the shared vector importer.
        # Decode COCO RLE directly as editable raster masks, never flatten masks
        # into bounding boxes or silently claim external labels are verified.
        for source_file, image_reference, label, raw in coco_rle_annotations:
            image = self._match_image(image_reference, by_basename, by_import_source)
            if image is None:
                semantic_unmatched.add(image_reference)
                semantic_issues.append(
                    AnnotationImportIssue(
                        source_file=source_file,
                        image_reference=image_reference,
                        annotation_id=str(raw.get("id", "")),
                        detail="No unique ReefVision image matched the COCO image reference",
                    )
                )
                continue
            try:
                label_class = self._ensure_class(
                    project_id=project_id,
                    annotation={
                        "label_short_code": label,
                        "label_long_code": label,
                        "label_id": f"coco:{source_file}:{raw.get('category_id')}",
                    },
                    class_mapping=class_mapping,
                    dataset_indices=dataset_indices,
                    project_classes=project_classes,
                    matched_class_ids=matched_class_ids,
                    created_class_ids=created_class_ids,
                )
                if label_class is None:
                    raise ValidationError("COCO category could not be resolved")
                raster = self._decode_external_coco_rle(raw.get("segmentation"))
                annotation = {
                    "id": f"coco:{source_file}:{raw.get('id')}",
                    "label_id": f"coco:{source_file}:{raw.get('category_id')}",
                    "label_short_code": label,
                    "label_long_code": label,
                    "verified": False,
                    "data": {
                        "external_format": "coco",
                        "external_category_id": raw.get("category_id"),
                    },
                }
                result = self._add_raster_mask(
                    project_id=project_id,
                    image=image,
                    label_class=label_class,
                    annotation=annotation,
                    source_file=source_file,
                    image_reference=image_reference,
                    external_type="COCO_RLE",
                    raster=raster,
                    suffix="coco-rle",
                    extra_provenance={
                        "external_format": "coco",
                        "external_category_id": raw.get("category_id"),
                        "source_annotation_id": raw.get("id"),
                        "requires_researcher_review": True,
                    },
                )
                if result == "duplicate":
                    semantic_duplicates += 1
                else:
                    semantic_imported += 1
                    semantic_modified[image.id] = False
            except (ValidationError, ValueError, TypeError, KeyError) as exc:
                semantic_skipped += 1
                semantic_issues.append(
                    AnnotationImportIssue(
                        source_file=source_file,
                        image_reference=image_reference,
                        annotation_id=str(raw.get("id", "")),
                        detail=f"COCO RLE mask import: {exc}",
                    )
                )

        for image_id, all_verified in semantic_modified.items():
            image = self.session.get(ImageAsset, image_id)
            if image is None:
                continue
            previous_revision = before_revisions.get(image_id, image.annotation_revision)
            if image.annotation_revision == previous_revision:
                image.annotation_revision += 1
            if not all_verified:
                image.annotation_status = "in_progress"
            elif image.annotation_status == "unannotated":
                image.annotation_status = "annotated"

        self.session.commit()
        return report.model_copy(
            update={
                "classes_matched": report.classes_matched + len(matched_class_ids),
                "classes_created": (
                    report.classes_created + len(created_class_ids) + len(precreated_class_ids)
                ),
                "masks_imported": report.masks_imported + semantic_imported,
                "duplicate_annotations": report.duplicate_annotations + semantic_duplicates,
                "unmatched_images": report.unmatched_images + len(semantic_unmatched),
                "unknown_classes": report.unknown_classes + semantic_unknown_classes,
                "skipped_annotations": report.skipped_annotations + semantic_skipped,
                "files_processed": len(buffered),
                "issues": [*report.issues, *import_warnings, *semantic_issues],
            }
        )
