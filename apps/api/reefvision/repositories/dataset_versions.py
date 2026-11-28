"""Dataset-version and export persistence helpers."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only, selectinload

from reefvision.db.models import DatasetVersion, DatasetVersionItem, ExportRecord, ImageAsset


class DatasetVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_version(self, version: DatasetVersion) -> None:
        self.session.add(version)

    def add_item(self, item: DatasetVersionItem) -> None:
        self.session.add(item)

    def get_version(self, version_id: str) -> DatasetVersion | None:
        statement = (
            select(DatasetVersion)
            .options(selectinload(DatasetVersion.items), selectinload(DatasetVersion.exports))
            .where(DatasetVersion.id == version_id)
        )
        return self.session.scalar(statement)

    def get_version_header(self, version_id: str) -> DatasetVersion | None:
        statement = (
            select(DatasetVersion)
            .options(
                load_only(
                    DatasetVersion.id,
                    DatasetVersion.project_id,
                    DatasetVersion.name,
                    DatasetVersion.status,
                    DatasetVersion.version_number,
                    DatasetVersion.manifest_sha256,
                    DatasetVersion.image_count,
                    DatasetVersion.annotation_count,
                    DatasetVersion.warnings_json,
                )
            )
            .where(DatasetVersion.id == version_id)
        )
        return self.session.scalar(statement)

    def list_versions(self, project_id: str) -> list[DatasetVersion]:
        statement = (
            select(DatasetVersion)
            .where(DatasetVersion.project_id == project_id)
            .order_by(DatasetVersion.version_number.desc(), DatasetVersion.created_at.desc())
        )
        return list(self.session.scalars(statement))

    def next_version_number(self, project_id: str) -> int:
        statement = select(func.max(DatasetVersion.version_number)).where(
            DatasetVersion.project_id == project_id
        )
        current = self.session.scalar(statement)
        return int(current or 0) + 1

    def items_for_version(self, version_id: str) -> list[DatasetVersionItem]:
        statement = (
            select(DatasetVersionItem)
            .where(DatasetVersionItem.dataset_version_id == version_id)
            .order_by(
                DatasetVersionItem.split,
                DatasetVersionItem.group_key,
                DatasetVersionItem.original_filename,
                DatasetVersionItem.image_id,
            )
        )
        return list(self.session.scalars(statement))

    def project_test_image_ids(self, project_id: str) -> set[str]:
        """Resolve historical test identities across frozen and current project membership."""
        versions = select(DatasetVersion.id).where(
            DatasetVersion.project_id == project_id,
            DatasetVersion.status.in_(("complete", "archived")),
        )
        holdouts = set(
            self.session.scalars(
                select(DatasetVersionItem.image_id).where(
                    DatasetVersionItem.dataset_version_id.in_(versions),
                    DatasetVersionItem.split == "test",
                )
            )
        )
        if not holdouts:
            return holdouts
        identities = (
            select(ImageAsset.id, ImageAsset.sha256, ImageAsset.group_key)
            .where(ImageAsset.project_id == project_id)
            .union(
                select(
                    DatasetVersionItem.image_id,
                    DatasetVersionItem.image_sha256,
                    DatasetVersionItem.group_key,
                ).where(DatasetVersionItem.dataset_version_id.in_(versions))
            )
        )
        keys_by_image: dict[str, set[tuple[str, str]]] = defaultdict(set)
        members: dict[tuple[str, str], set[str]] = defaultdict(set)
        for image_id, checksum, group in self.session.execute(identities):
            keys = {("sha256", checksum)}
            if group is not None:
                keys.add(("group", group))
            keys_by_image[image_id].update(keys)
            for key in keys:
                members[key].add(image_id)
        # A renamed group or restored copy can link two historical identities.
        # Each distinct checksum/group is expanded at most once.
        pending = list(holdouts)
        while pending:
            for key in keys_by_image[pending.pop()]:
                related = members.pop(key, set()) - holdouts
                holdouts.update(related)
                pending.extend(related)
        return holdouts


class ExportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_export(self, export: ExportRecord) -> None:
        self.session.add(export)

    def get_export(self, export_id: str) -> ExportRecord | None:
        statement = (
            select(ExportRecord)
            .options(selectinload(ExportRecord.dataset_version))
            .where(ExportRecord.id == export_id)
        )
        return self.session.scalar(statement)

    def list_exports(
        self, project_id: str, *, dataset_version_id: str | None = None
    ) -> list[ExportRecord]:
        filters = [ExportRecord.project_id == project_id]
        if dataset_version_id is not None:
            filters.append(ExportRecord.dataset_version_id == dataset_version_id)
        statement = (
            select(ExportRecord)
            .where(*filters)
            .order_by(ExportRecord.created_at.desc(), ExportRecord.id.desc())
        )
        return list(self.session.scalars(statement))
