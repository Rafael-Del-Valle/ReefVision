"""Image persistence and stable pagination."""

from __future__ import annotations

from typing import cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, load_only

from reefvision.db.models import Annotation, ImageAsset


class ImageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, image: ImageAsset) -> None:
        self.session.add(image)

    def get_basic(self, image_id: str) -> ImageAsset | None:
        statement = select(ImageAsset).where(ImageAsset.id == image_id)
        return self.session.scalar(statement)

    def get(self, image_id: str) -> ImageAsset | None:
        count_subquery = (
            select(func.count(Annotation.id))
            .where(Annotation.image_id == ImageAsset.id, Annotation.deleted_at.is_(None))
            .correlate(ImageAsset)
            .scalar_subquery()
        )
        statement = select(ImageAsset, count_subquery.label("annotation_count")).where(
            ImageAsset.id == image_id
        )
        row = self.session.execute(statement).one_or_none()
        if row is None:
            return None
        image = cast(ImageAsset, row[0])
        image.__dict__["annotation_count"] = int(row[1] or 0)
        return image

    def find_duplicate(self, project_id: str, sha256: str) -> ImageAsset | None:
        statement = select(ImageAsset).where(
            ImageAsset.project_id == project_id, ImageAsset.sha256 == sha256
        )
        return self.session.scalar(statement)

    def ordered_ids_for_project(self, project_id: str) -> list[str]:
        statement = (
            select(ImageAsset.id)
            .where(ImageAsset.project_id == project_id)
            .order_by(ImageAsset.created_at.desc(), ImageAsset.id)
        )
        return list(self.session.scalars(statement))

    def neighbor_ids_for_image(self, image: ImageAsset) -> tuple[str | None, str | None]:
        previous_statement = (
            select(ImageAsset.id)
            .where(
                ImageAsset.project_id == image.project_id,
                or_(
                    ImageAsset.created_at > image.created_at,
                    and_(ImageAsset.created_at == image.created_at, ImageAsset.id < image.id),
                ),
            )
            .order_by(ImageAsset.created_at.asc(), ImageAsset.id.desc())
            .limit(1)
        )
        next_statement = (
            select(ImageAsset.id)
            .where(
                ImageAsset.project_id == image.project_id,
                or_(
                    ImageAsset.created_at < image.created_at,
                    and_(ImageAsset.created_at == image.created_at, ImageAsset.id > image.id),
                ),
            )
            .order_by(ImageAsset.created_at.desc(), ImageAsset.id.asc())
            .limit(1)
        )
        previous_image_id = self.session.scalar(previous_statement)
        next_image_id = self.session.scalar(next_statement)
        return previous_image_id, next_image_id

    def list_by_ids(self, image_ids: list[str]) -> list[ImageAsset]:
        if not image_ids:
            return []
        statement = select(ImageAsset).where(ImageAsset.id.in_(image_ids))
        items = list(self.session.scalars(statement))
        by_id = {image.id: image for image in items}
        return [by_id[image_id] for image_id in image_ids if image_id in by_id]

    def list_page(
        self,
        project_id: str,
        *,
        page: int,
        page_size: int,
        filename: str | None = None,
        annotation_status: str | None = None,
        group_key: str | None = None,
    ) -> tuple[list[ImageAsset], int]:
        filters = [ImageAsset.project_id == project_id]
        if filename:
            filters.append(ImageAsset.original_filename.ilike(f"%{filename}%"))
        if annotation_status:
            filters.append(ImageAsset.annotation_status == annotation_status)
        if group_key:
            filters.append(ImageAsset.group_key.ilike(f"%{group_key}%"))

        count_statement = select(func.count(ImageAsset.id)).where(*filters)
        total = int(self.session.scalar(count_statement) or 0)
        statement = (
            select(ImageAsset)
            .options(
                load_only(
                    ImageAsset.id,
                    ImageAsset.project_id,
                    ImageAsset.original_filename,
                    ImageAsset.thumbnail_path,
                    ImageAsset.width_px,
                    ImageAsset.height_px,
                    ImageAsset.group_key,
                    ImageAsset.annotation_status,
                    ImageAsset.annotation_revision,
                    ImageAsset.created_at,
                    ImageAsset.updated_at,
                )
            )
            .where(*filters)
            .order_by(ImageAsset.created_at.desc(), ImageAsset.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        page_items = list(self.session.scalars(statement))
        if not page_items:
            return [], total

        page_ids = [item.id for item in page_items]
        annotation_counts = {
            image_id: int(count or 0)
            for image_id, count in self.session.execute(
                select(Annotation.image_id, func.count(Annotation.id))
                .where(
                    Annotation.deleted_at.is_(None),
                    Annotation.image_id.in_(page_ids),
                )
                .group_by(Annotation.image_id)
            ).all()
        }

        items: list[ImageAsset] = []
        for image in page_items:
            item = cast(ImageAsset, image)
            item.__dict__["annotation_count"] = annotation_counts.get(item.id, 0)
            items.append(item)
        return items, total
