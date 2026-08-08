"""Import CoralNet-Toolbox annotations into native ReefVision records."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import PurePath, PureWindowsPath
from typing import Any, BinaryIO
from uuid import NAMESPACE_URL, uuid4, uuid5

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    MaskAnnotationEvent,
    Project,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.annotation_imports import (
    AnnotationImportIssue,
    AnnotationImportResponse,
)
from reefvision.schemas.annotations import MaskAnnotationDraft, PolygonPoint
from reefvision.services.annotations import (
    AnnotationService,
    annotation_snapshot,
    mask_annotation_snapshot,
)


class AnnotationImportService:
    """Translate CoralNet-Toolbox JSON into ReefVision's canonical annotation models."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.annotation_service = AnnotationService(session, settings)

    @staticmethod
    def _normalize_label(value: object) -> str:
        text = " ".join(str(value or "").strip().split()).casefold()
        words = text.split()
        if words and words[-1] == "c":
            words[-1] = "closed"
        elif words and words[-1] == "o":
            words[-1] = "open"
        return " ".join(words)

    @staticmethod
    def _basename(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        windows_name = PureWindowsPath(text).name
        return windows_name or PurePath(text.replace("\\", "/")).name

    @staticmethod
    def _decode(upload: BinaryIO) -> str:
        data = upload.read()
        if isinstance(data, str):
            return data
        return data.decode("utf-8-sig")

    @staticmethod
    def _as_mapping(payload: object) -> dict[str, Any] | None:
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _looks_like_class_mapping(payload: dict[str, Any]) -> bool:
        if not payload:
            return False
        values = list(payload.values())
        return all(
            isinstance(item, dict) and "short_label_code" in item and "long_label_code" in item
            for item in values
        )

    @staticmethod
    def _looks_like_annotations(payload: dict[str, Any]) -> bool:
        return bool(payload) and all(isinstance(value, list) for value in payload.values())

    @staticmethod
    def _parse_dataset_names(payload: object) -> dict[str, int]:
        if not isinstance(payload, dict):
            return {}
        names = payload.get("names")
        if isinstance(names, list):
            return {str(name): index for index, name in enumerate(names)}
        if not isinstance(names, dict):
            return {}
        parsed: dict[str, int] = {}
        for raw_index, raw_name in names.items():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            parsed[str(raw_name)] = index
        return parsed

    @staticmethod
    def _color_hex(value: object) -> str:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                red, green, blue = (max(0, min(255, int(channel))) for channel in value[:3])
                return f"#{red:02X}{green:02X}{blue:02X}"
            except (TypeError, ValueError):
                pass
        return "#4F86C6"

    @staticmethod
    def _state_name(long_label: str) -> str | None:
        normalized = AnnotationImportService._normalize_label(long_label)
        if normalized.endswith(" closed"):
            return "Closed"
        if normalized.endswith(" open"):
            return "Open"
        return None

    @staticmethod
    def _stable_id(project_id: str, external_id: object, suffix: str = "") -> str:
        source = str(external_id or uuid4())
        return str(uuid5(NAMESPACE_URL, f"reefvision:{project_id}:{source}:{suffix}"))

    @staticmethod
    def _point_pair(value: object) -> tuple[float, float] | None:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return None
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _strip_closing_point(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(points) > 3 and points[0] == points[-1]:
            return points[:-1]
        return points

    @staticmethod
    def _provenance(
        *,
        source_file: str,
        annotation: dict[str, Any],
        external_type: str,
        image_reference: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "import_format": "coralnet_toolbox",
            "source_file": source_file,
            "external_annotation_id": annotation.get("id"),
            "external_label_id": annotation.get("label_id"),
            "external_label_short_code": annotation.get("label_short_code"),
            "external_label_long_code": annotation.get("label_long_code"),
            "external_annotation_type": external_type,
            "external_image_reference": image_reference,
            "external_verified": bool(annotation.get("verified", True)),
        }
        if annotation.get("data"):
            result["external_data"] = annotation.get("data")
        if extra:
            result.update(extra)
        return result

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _images_by_reference(
        self, project_id: str
    ) -> tuple[dict[str, list[ImageAsset]], dict[str, list[ImageAsset]]]:
        images = list(
            self.session.scalars(select(ImageAsset).where(ImageAsset.project_id == project_id))
        )
        by_basename: dict[str, list[ImageAsset]] = defaultdict(list)
        by_import_source: dict[str, list[ImageAsset]] = defaultdict(list)
        for image in images:
            by_basename[image.original_filename.casefold()].append(image)
            if image.import_source:
                normalized = str(image.import_source).replace("\\", "/").casefold()
                by_import_source[normalized].append(image)
        return by_basename, by_import_source

    def _match_image(
        self,
        reference: str,
        by_basename: dict[str, list[ImageAsset]],
        by_import_source: dict[str, list[ImageAsset]],
    ) -> ImageAsset | None:
        normalized_reference = reference.replace("\\", "/").casefold()
        exact = by_import_source.get(normalized_reference, [])
        if len(exact) == 1:
            return exact[0]
        basename = self._basename(reference).casefold()
        matches = by_basename.get(basename, [])
        return matches[0] if len(matches) == 1 else None

    def _ensure_class(
        self,
        *,
        project_id: str,
        annotation: dict[str, Any],
        class_mapping: dict[str, dict[str, Any]],
        dataset_indices: dict[str, int],
        project_classes: list[LabelClass],
        matched_class_ids: set[str],
        created_class_ids: set[str],
    ) -> LabelClass | None:
        short_code = str(annotation.get("label_short_code") or "").strip()
        long_code = str(annotation.get("label_long_code") or "").strip()
        external_label_id = str(annotation.get("label_id") or "").strip()

        mapping_entry: dict[str, Any] | None = None
        for key, entry in class_mapping.items():
            if not isinstance(entry, dict):
                continue
            if external_label_id and str(entry.get("id") or "") == external_label_id:
                mapping_entry = entry
                break
            if self._normalize_label(key) == self._normalize_label(short_code):
                mapping_entry = entry
                break
            if self._normalize_label(entry.get("short_label_code")) == self._normalize_label(
                short_code
            ):
                mapping_entry = entry
                break

        if mapping_entry is not None:
            short_code = str(mapping_entry.get("short_label_code") or short_code).strip()
            long_code = str(mapping_entry.get("long_label_code") or long_code).strip()

        candidate_names = {
            self._normalize_label(short_code),
            self._normalize_label(long_code),
        }
        candidate_names.discard("")
        for label_class in project_classes:
            if self._normalize_label(label_class.name) in candidate_names:
                matched_class_ids.add(label_class.id)
                return label_class

        display_name = long_code or short_code
        if not display_name:
            return None

        used_indices = {item.class_index for item in project_classes}
        preferred_index = dataset_indices.get(short_code)
        if preferred_index is None:
            preferred_index = dataset_indices.get(display_name)
        if preferred_index is None or preferred_index in used_indices:
            preferred_index = max(used_indices, default=-1) + 1

        color_source = (
            mapping_entry.get("color")
            if mapping_entry is not None
            else annotation.get("annotation_color")
        )
        label_class = LabelClass(
            id=str(uuid4()),
            project_id=project_id,
            class_index=preferred_index,
            display_order=max((item.display_order for item in project_classes), default=-1) + 1,
            name=display_name,
            scientific_name=None,
            state_name=self._state_name(display_name),
            description="Imported from CoralNet-Toolbox metadata.",
            display_color=self._color_hex(color_source),
        )
        self.session.add(label_class)
        self.session.flush()
        project_classes.append(label_class)
        created_class_ids.add(label_class.id)
        return label_class

    @staticmethod
    def _valid_box(image: ImageAsset, coordinates: tuple[float, float, float, float]) -> bool:
        x_min, y_min, x_max, y_max = coordinates
        return 0 <= x_min < x_max <= image.width_px and 0 <= y_min < y_max <= image.height_px

    def _add_box(
        self,
        *,
        project_id: str,
        image: ImageAsset,
        label_class: LabelClass,
        annotation: dict[str, Any],
        source_file: str,
        image_reference: str,
        external_type: str,
        coordinates: tuple[float, float, float, float],
        suffix: str = "",
    ) -> str:
        annotation_id = self._stable_id(project_id, annotation.get("id"), suffix)
        if self.session.get(Annotation, annotation_id) is not None:
            return "duplicate"
        if self.session.get(MaskAnnotation, annotation_id) is not None:
            return "duplicate"
        if not self._valid_box(image, coordinates):
            raise ValidationError("Imported bounding box falls outside the source image")

        x_min, y_min, x_max, y_max = coordinates
        record = Annotation(
            id=annotation_id,
            image_id=image.id,
            label_class_id=label_class.id,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            source_type="imported",
            provenance_json=self._provenance(
                source_file=source_file,
                annotation=annotation,
                external_type=external_type,
                image_reference=image_reference,
            ),
            created_by="coralnet_toolbox_importer",
            revision=1,
        )
        self.session.add(record)
        self.session.flush()
        self.session.add(
            AnnotationEvent(
                annotation_id=record.id,
                image_id=image.id,
                event_type="imported",
                before_json=None,
                after_json=annotation_snapshot(record),
                actor="coralnet_toolbox_importer",
            )
        )
        return "imported"

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
        if holes:
            raise ValidationError(
                "Polygon contains holes; ReefVision's editable polygon schema "
                "cannot preserve them yet"
            )
        if not isinstance(points_value, list):
            raise ValidationError("Polygon annotation has no point list")
        parsed_points = [self._point_pair(point) for point in points_value]
        if any(point is None for point in parsed_points):
            raise ValidationError("Polygon contains malformed coordinates")
        points = self._strip_closing_point([point for point in parsed_points if point is not None])
        annotation_id = self._stable_id(project_id, annotation.get("id"), suffix)
        if self.session.get(MaskAnnotation, annotation_id) is not None:
            return "duplicate"
        if self.session.get(Annotation, annotation_id) is not None:
            return "duplicate"

        draft = MaskAnnotationDraft(
            id=annotation_id,
            label_class_id=label_class.id,
            geometry_kind="polygon",
            points=[PolygonPoint(x=x, y=y) for x, y in points],
        )
        polygon, x_min, y_min, x_max, y_max, area_pixels = (
            self.annotation_service._validated_polygon(draft, image)
        )
        record = MaskAnnotation(
            id=annotation_id,
            image_id=image.id,
            label_class_id=label_class.id,
            geometry_kind="polygon",
            polygon_json=polygon,
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

    def import_streams(
        self,
        project_id: str,
        uploads: list[tuple[str | None, BinaryIO]],
    ) -> AnnotationImportResponse:
        project = self._project(project_id)
        project_classes = list(project.label_classes)
        class_mapping: dict[str, dict[str, Any]] = {}
        dataset_indices: dict[str, int] = {}
        annotation_payloads: list[tuple[str, dict[str, Any]]] = []
        issues: list[AnnotationImportIssue] = []
        class_mapping_files = 0
        dataset_yaml_files = 0
        annotation_files = 0

        for raw_filename, stream in uploads:
            filename = str(raw_filename or "annotations.json")
            try:
                text = self._decode(stream)
                if filename.casefold().endswith((".yaml", ".yml")):
                    dataset_indices.update(self._parse_dataset_names(yaml.safe_load(text)))
                    dataset_yaml_files += 1
                    continue
                payload = self._as_mapping(json.loads(text))
                if payload is None:
                    raise ValidationError("Top-level JSON value must be an object")
                if self._looks_like_class_mapping(payload):
                    class_mapping.update(
                        {
                            str(key): value
                            for key, value in payload.items()
                            if isinstance(value, dict)
                        }
                    )
                    class_mapping_files += 1
                    continue
                if self._looks_like_annotations(payload):
                    annotation_payloads.append((filename, payload))
                    annotation_files += 1
                    continue
                raise ValidationError("JSON is not a recognized CoralNet-Toolbox export")
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                yaml.YAMLError,
                ValidationError,
            ) as exc:
                issues.append(AnnotationImportIssue(source_file=filename, detail=str(exc)))

        if not annotation_payloads:
            return AnnotationImportResponse(
                project_id=project_id,
                files_processed=len(uploads),
                annotation_files=annotation_files,
                class_mapping_files=class_mapping_files,
                dataset_yaml_files=dataset_yaml_files,
                classes_matched=0,
                classes_created=0,
                boxes_imported=0,
                masks_imported=0,
                duplicate_annotations=0,
                unmatched_images=0,
                unknown_classes=0,
                skipped_annotations=0,
                issues=issues,
            )

        by_basename, by_import_source = self._images_by_reference(project_id)
        matched_class_ids: set[str] = set()
        created_class_ids: set[str] = set()
        unmatched_references: set[str] = set()
        modified_images: dict[str, bool] = {}
        boxes_imported = 0
        masks_imported = 0
        duplicate_annotations = 0
        unknown_classes = 0
        skipped_annotations = 0

        for source_file, payload in annotation_payloads:
            for top_level_reference, raw_annotations in payload.items():
                image_reference = str(top_level_reference)
                image = self._match_image(
                    image_reference,
                    by_basename,
                    by_import_source,
                )
                if image is None:
                    unmatched_references.add(image_reference)
                    issues.append(
                        AnnotationImportIssue(
                            source_file=source_file,
                            image_reference=image_reference,
                            detail=(
                                "No unique ReefVision image matched this "
                                "CoralNet-Toolbox image path"
                            ),
                        )
                    )
                    continue

                if not isinstance(raw_annotations, list):
                    continue
                for raw_annotation in raw_annotations:
                    if not isinstance(raw_annotation, dict):
                        skipped_annotations += 1
                        continue
                    annotation = raw_annotation
                    annotation_id = str(annotation.get("id") or "") or None
                    external_type = str(annotation.get("type") or "")
                    label_class = self._ensure_class(
                        project_id=project_id,
                        annotation=annotation,
                        class_mapping=class_mapping,
                        dataset_indices=dataset_indices,
                        project_classes=project_classes,
                        matched_class_ids=matched_class_ids,
                        created_class_ids=created_class_ids,
                    )
                    if label_class is None:
                        unknown_classes += 1
                        skipped_annotations += 1
                        issues.append(
                            AnnotationImportIssue(
                                source_file=source_file,
                                image_reference=image_reference,
                                annotation_id=annotation_id,
                                detail="Annotation has no resolvable class label",
                            )
                        )
                        continue

                    try:
                        results: list[tuple[str, str]] = []
                        if external_type == "RectangleAnnotation":
                            top_left = self._point_pair(annotation.get("top_left"))
                            bottom_right = self._point_pair(annotation.get("bottom_right"))
                            if top_left is None or bottom_right is None:
                                raise ValidationError(
                                    "Rectangle coordinates are missing or malformed"
                                )
                            coordinates = (
                                min(top_left[0], bottom_right[0]),
                                min(top_left[1], bottom_right[1]),
                                max(top_left[0], bottom_right[0]),
                                max(top_left[1], bottom_right[1]),
                            )
                            results.append(
                                (
                                    "box",
                                    self._add_box(
                                        project_id=project_id,
                                        image=image,
                                        label_class=label_class,
                                        annotation=annotation,
                                        source_file=source_file,
                                        image_reference=image_reference,
                                        external_type=external_type,
                                        coordinates=coordinates,
                                    ),
                                )
                            )
                        elif external_type == "PatchAnnotation":
                            center = self._point_pair(annotation.get("center_xy"))
                            raw_size = annotation.get("annotation_size")
                            try:
                                size = float(raw_size) if raw_size is not None else 0.0
                            except (TypeError, ValueError) as exc:
                                raise ValidationError("Patch size is missing or malformed") from exc
                            if center is None or size <= 0:
                                raise ValidationError("Patch geometry is missing or malformed")
                            half = size / 2.0
                            results.append(
                                (
                                    "box",
                                    self._add_box(
                                        project_id=project_id,
                                        image=image,
                                        label_class=label_class,
                                        annotation=annotation,
                                        source_file=source_file,
                                        image_reference=image_reference,
                                        external_type=external_type,
                                        coordinates=(
                                            center[0] - half,
                                            center[1] - half,
                                            center[0] + half,
                                            center[1] + half,
                                        ),
                                    ),
                                )
                            )
                        elif external_type == "PolygonAnnotation":
                            results.append(
                                (
                                    "mask",
                                    self._add_polygon(
                                        project_id=project_id,
                                        image=image,
                                        label_class=label_class,
                                        annotation=annotation,
                                        source_file=source_file,
                                        image_reference=image_reference,
                                        external_type=external_type,
                                        points_value=annotation.get("points"),
                                        holes_value=annotation.get("holes", []),
                                    ),
                                )
                            )
                        elif external_type == "MultiPolygonAnnotation":
                            polygons = annotation.get("polygons")
                            if not isinstance(polygons, list) or not polygons:
                                raise ValidationError("Multipolygon contains no polygon parts")
                            for part_index, raw_polygon in enumerate(polygons):
                                if not isinstance(raw_polygon, dict):
                                    raise ValidationError(
                                        "Multipolygon contains a malformed polygon part"
                                    )
                                results.append(
                                    (
                                        "mask",
                                        self._add_polygon(
                                            project_id=project_id,
                                            image=image,
                                            label_class=label_class,
                                            annotation=annotation,
                                            source_file=source_file,
                                            image_reference=image_reference,
                                            external_type=external_type,
                                            points_value=raw_polygon.get("points"),
                                            holes_value=raw_polygon.get("holes", []),
                                            suffix=f"part-{part_index}",
                                            extra_provenance={
                                                "external_multipolygon_part": part_index,
                                                "external_multipolygon_part_count": len(polygons),
                                            },
                                        ),
                                    )
                                )
                        elif external_type == "MaskAnnotation":
                            raise ValidationError(
                                "Semantic MaskAnnotation JSON needs its raster mask file; "
                                "import the exported mask image instead"
                            )
                        else:
                            unsupported_type = external_type or "unknown"
                            raise ValidationError(
                                f"Unsupported CoralNet-Toolbox annotation type: {unsupported_type}"
                            )

                        imported_here = False
                        verified_here = bool(annotation.get("verified", True))
                        for geometry_kind, result in results:
                            if result == "duplicate":
                                duplicate_annotations += 1
                            elif geometry_kind == "box":
                                boxes_imported += 1
                                imported_here = True
                            else:
                                masks_imported += 1
                                imported_here = True
                        if imported_here:
                            if image.id not in modified_images:
                                modified_images[image.id] = verified_here
                            else:
                                modified_images[image.id] = (
                                    modified_images[image.id] and verified_here
                                )
                    except (ValidationError, ValueError, TypeError) as exc:
                        skipped_annotations += 1
                        issues.append(
                            AnnotationImportIssue(
                                source_file=source_file,
                                image_reference=image_reference,
                                annotation_id=annotation_id,
                                detail=str(exc),
                            )
                        )

        for image_id, all_verified in modified_images.items():
            image = self.session.get(ImageAsset, image_id)
            if image is None:
                continue
            image.annotation_revision += 1
            if image.annotation_status == "unannotated":
                image.annotation_status = "annotated" if all_verified else "in_progress"

        self.session.commit()
        return AnnotationImportResponse(
            project_id=project_id,
            files_processed=len(uploads),
            annotation_files=annotation_files,
            class_mapping_files=class_mapping_files,
            dataset_yaml_files=dataset_yaml_files,
            classes_matched=len(matched_class_ids),
            classes_created=len(created_class_ids),
            boxes_imported=boxes_imported,
            masks_imported=masks_imported,
            duplicate_annotations=duplicate_annotations,
            unmatched_images=len(unmatched_references),
            unknown_classes=unknown_classes,
            skipped_annotations=skipped_annotations,
            issues=issues,
        )
