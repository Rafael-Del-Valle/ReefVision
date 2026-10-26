"""Image import, query, and update services."""

from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, Project
from reefvision.domain.enums import ANNOTATION_STATUSES
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.jobs import JobRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.images import (
    ImageImportResponse,
    ImageListItemResponse,
    ImagePageResponse,
    ImageUpdate,
    ImportItemResponse,
)
from reefvision.storage.images import (
    InvalidImageError,
    UnsupportedImageError,
    commit_staged_image,
    create_browser_display,
    create_thumbnail,
    ensure_supported_extension,
    inspect_staged_image,
    project_image_directories,
    safe_original_name,
    stream_to_staging,
)
from reefvision.storage.projects import resolve_managed_project_path


class ImageService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.images = ImageRepository(session)
        self.jobs = JobRepository(session)

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def import_streams(
        self,
        project_id: str,
        uploads: list[tuple[str | None, BinaryIO]],
        relative_paths: list[str] | None = None,
    ) -> ImageImportResponse:
        project = self._project(project_id)
        directories = project_image_directories(self.settings, project.storage_root)
        paths = relative_paths or []
        report: dict[str, list[ImportItemResponse]] = {
            "successful": [],
            "duplicates": [],
            "unsupported": [],
            "failed": [],
        }

        for index, (raw_filename, source) in enumerate(uploads):
            filename = safe_original_name(raw_filename)
            relative_path = paths[index] if index < len(paths) and paths[index] else None
            staging = directories["staging"] / f"{uuid4()}.part"
            managed_destination: Path | None = None
            staging_owned = False
            uncommitted_original = False
            try:
                ensure_supported_extension(filename)
                sha256, size = stream_to_staging(source, staging)
                staging_owned = True
                inspected = inspect_staged_image(staging, sha256, size)
                duplicate = self.images.find_duplicate(project_id, sha256)
                if duplicate is not None:
                    staging.unlink(missing_ok=True)
                    report["duplicates"].append(
                        ImportItemResponse(
                            filename=filename,
                            relative_path=relative_path,
                            status="duplicate",
                            detail="Exact file already exists in this project",
                            duplicate_image_id=duplicate.id,
                        )
                    )
                    continue

                image_id = str(uuid4())
                relative_managed = (
                    f"{project.storage_root}/images/originals/{image_id}{inspected.extension}"
                )
                relative_thumbnail = f"{project.storage_root}/images/thumbnails/{image_id}.jpg"
                managed_destination = resolve_managed_project_path(self.settings, relative_managed)
                commit_staged_image(staging, managed_destination)
                staging_owned = False
                uncommitted_original = True
                image = ImageAsset(
                    id=image_id,
                    project_id=project_id,
                    original_filename=filename,
                    managed_path=relative_managed,
                    sha256=inspected.sha256,
                    width_px=inspected.width_px,
                    height_px=inspected.height_px,
                    file_size_bytes=inspected.file_size_bytes,
                    media_type=inspected.media_type,
                    import_source=relative_path or filename,
                    capture_timestamp=inspected.capture_timestamp,
                    metadata_json=inspected.metadata,
                )
                job = Job(
                    project_id=project_id,
                    job_type="thumbnail",
                    status="queued",
                    progress_total=1,
                    request_json={
                        "image_id": image_id,
                        "source_path": relative_managed,
                        "thumbnail_path": relative_thumbnail,
                    },
                )
                self.images.add(image)
                self.jobs.add(job)
                self.session.commit()
                # A successful database commit makes the managed original
                # durable, even if a subsequent response refresh fails.
                uncommitted_original = False
                self.session.refresh(image)
                self.session.refresh(job)
                report["successful"].append(
                    ImportItemResponse(
                        filename=filename,
                        relative_path=relative_path,
                        status="successful",
                        image_id=image.id,
                        thumbnail_job_id=job.id,
                    )
                )
            except UnsupportedImageError as exc:
                self.session.rollback()
                if staging_owned:
                    staging.unlink(missing_ok=True)
                report["unsupported"].append(
                    ImportItemResponse(
                        filename=filename,
                        relative_path=relative_path,
                        status="unsupported",
                        detail=str(exc),
                    )
                )
            except (InvalidImageError, OSError, IntegrityError, ValidationError) as exc:
                self.session.rollback()
                if staging_owned:
                    staging.unlink(missing_ok=True)
                # Do not delete an existing original when exclusive placement
                # failed, or a committed original after a response error.
                if uncommitted_original and managed_destination is not None:
                    managed_destination.unlink(missing_ok=True)
                report["failed"].append(
                    ImportItemResponse(
                        filename=filename,
                        relative_path=relative_path,
                        status="failed",
                        detail=str(exc),
                    )
                )
            except Exception as exc:
                self.session.rollback()
                if staging_owned:
                    staging.unlink(missing_ok=True)
                # Do not delete an existing original when exclusive placement
                # failed, or a committed original after a response error.
                if uncommitted_original and managed_destination is not None:
                    managed_destination.unlink(missing_ok=True)
                report["failed"].append(
                    ImportItemResponse(
                        filename=filename,
                        relative_path=relative_path,
                        status="failed",
                        detail=f"Unexpected import failure: {exc}",
                    )
                )

        return ImageImportResponse(project_id=project_id, **report)

    def list_images(
        self,
        project_id: str,
        *,
        page: int,
        page_size: int,
        filename: str | None,
        annotation_status: str | None,
        group_key: str | None,
        sort_by: str,
    ) -> ImagePageResponse:
        self._project(project_id)
        if annotation_status and annotation_status not in ANNOTATION_STATUSES:
            raise ValidationError("Unknown annotation status")
        items, total = self.images.list_page(
            project_id,
            page=page,
            page_size=page_size,
            filename=filename,
            annotation_status=annotation_status,
            group_key=group_key,
            sort_by=sort_by,
        )
        return ImagePageResponse(
            items=[ImageListItemResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    def get_image(self, image_id: str) -> ImageAsset:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def get_image_record(self, image_id: str) -> ImageAsset:
        image = self.images.get_basic(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def update_image(self, image_id: str, payload: ImageUpdate) -> ImageAsset:
        image = self.get_image(image_id)
        changes = payload.model_dump(exclude_unset=True)
        if "annotation_status" in changes and changes["annotation_status"] is None:
            changes.pop("annotation_status")
        status_changed = (
            "annotation_status" in changes
            and changes["annotation_status"] != image.annotation_status
        )
        for key, value in changes.items():
            setattr(image, key, value)
        if status_changed:
            image.annotation_revision += 1
        self.session.commit()
        self.session.refresh(image)
        return image

    def content_path_for_image(self, image: ImageAsset, *, thumbnail: bool = False) -> Path:
        relative = image.thumbnail_path if thumbnail else image.managed_path
        if relative is None:
            raise NotFoundError("Thumbnail is not available yet")
        path = resolve_managed_project_path(self.settings, relative)
        if not path.is_file():
            raise NotFoundError("Managed image file is missing")
        return path

    def content_path(self, image_id: str, *, thumbnail: bool = False) -> Path:
        image = self.get_image_record(image_id)
        return self.content_path_for_image(image, thumbnail=thumbnail)

    def display_path_for_image(self, image: ImageAsset) -> tuple[Path, str]:
        source = self.content_path_for_image(image)
        # Browser/WebView rendering of TIFF, BMP, GIF and CMYK JPEG is not
        # consistently supported. Keep original source and source-pixel geometry;
        # a separate PNG rendition is used for the display only.
        metadata = image.metadata_json or {}
        source_mode = str(metadata.get("mode", ""))
        exif = metadata.get("exif")
        orientation = exif.get("Orientation") if isinstance(exif, dict) else None
        # WebView2 can auto-rotate an EXIF-oriented JPEG even though persisted
        # masks, dimensions and calibration are in the camera's raw pixel frame.
        # Serve a PNG with unrotated pixels and no orientation tag instead.
        needs_png = (
            image.media_type in {"image/tiff", "image/bmp", "image/gif"}
            or (image.media_type == "image/jpeg" and source_mode not in {"RGB", "L"})
            or orientation not in (None, 1)
            # Unreadable EXIF may hide camera orientation from the metadata.
            # Force a raw-pixel PNG so WebView2 cannot silently rotate it.
            or (image.media_type == "image/jpeg" and bool(metadata.get("exif_warning")))
        )
        if not needs_png:
            return source, image.media_type

        # Version the derived cache: older PNGs were EXIF-transposed and must
        # not be reused against raw-pixel scientific annotations.
        display_path = source.parent.parent / "display-v2" / f"{image.id}.png"
        if not display_path.is_file():
            create_browser_display(source, display_path)
        return display_path, "image/png"

    def thumbnail_path_for_image(self, image: ImageAsset) -> Path:
        metadata = image.metadata_json or {}
        mode = str(metadata.get("mode", ""))
        exif = metadata.get("exif")
        orientation = exif.get("Orientation") if isinstance(exif, dict) else None
        # Earlier thumbnails used EXIF presentation orientation, which can
        # disagree with stored source-pixel masks. Regenerate those JPEGs in a
        # new cache namespace rather than reusing misaligned legacy thumbnails.
        needs_raw_thumbnail = (
            (image.media_type == "image/tiff" and mode in {"I;16", "I;16L", "I;16B"})
            or orientation not in (None, 1)
            or (image.media_type == "image/jpeg" and bool(metadata.get("exif_warning")))
        )
        if needs_raw_thumbnail:
            source = self.content_path_for_image(image)
            corrected = source.parent.parent / "thumbnails-v3" / f"{image.id}.jpg"
            if not corrected.is_file():
                create_thumbnail(
                    source,
                    corrected,
                    max_width=self.settings.thumbnail_max_width,
                    max_height=self.settings.thumbnail_max_height,
                )
            return corrected
        return self.content_path_for_image(image, thumbnail=True)
