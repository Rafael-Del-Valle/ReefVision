"""Freeze registered original bands and replay analyses against the same measured samples."""

from datetime import UTC
from typing import TypeVar

import numpy as np
from numpy.typing import NDArray
from pydantic import ValidationError as SchemaError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ImageAsset,
    Project,
    SpectralAcquisition,
    SpectralBandBinding,
    SpectralIndex,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.multispectral import Planes, composite, normalized_difference
from reefvision.schemas.multispectral import (
    AcquisitionInput,
    AcquisitionSnapshot,
    FrozenBand,
    IndexInput,
    IndexSnapshot,
    SpectralPage,
    SpectralRecord,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.multispectral import encode_index, encode_rgba, load_band

Snapshot = TypeVar("Snapshot", AcquisitionSnapshot, IndexSnapshot)
Row = TypeVar("Row", SpectralAcquisition, SpectralIndex)


def _receipt(
    row: SpectralAcquisition | SpectralIndex, model: type[Snapshot]
) -> SpectralRecord[Snapshot]:
    if canonical_json_sha256(row.snapshot_json) != row.content_sha256:
        raise ConflictError("The saved spectral receipt differs from its content checksum")
    try:
        snapshot = model.model_validate(row.snapshot_json)
    except SchemaError as exc:
        raise ConflictError(
            "The saved spectral receipt has invalid calibration or source fields"
        ) from exc
    return SpectralRecord[Snapshot](
        id=row.id,
        project_id=row.project_id,
        content_sha256=row.content_sha256,
        created_at=row.created_at.replace(tzinfo=UTC),
        snapshot=snapshot,
    )


class MultispectralService:
    def __init__(self, session: Session, settings: Settings):
        self.session, self.settings = session, settings

    def _owned(self, model: type[Row], project_id: str, item_id: str) -> Row:
        row = self.session.get(model, item_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("The selected multispectral record is unavailable in this project")
        return row

    def _image(self, project_id: str, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None or image.project_id != project_id:
            raise NotFoundError("Choose an original band image from the current project")
        return image

    def _page(
        self, model: type[Row], project_id: str, limit: int, offset: int
    ) -> tuple[list[Row], int]:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        query = select(model).where(model.project_id == project_id)
        count = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(model.created_at.desc(), model.id).limit(limit).offset(offset)
        )
        return list(rows), count

    def acquisitions(
        self, project_id: str, limit: int, offset: int
    ) -> SpectralPage[AcquisitionSnapshot]:
        rows, total = self._page(SpectralAcquisition, project_id, limit, offset)
        return SpectralPage[AcquisitionSnapshot](
            items=[_receipt(r, AcquisitionSnapshot) for r in rows], total=total
        )

    def indices(self, project_id: str, limit: int, offset: int) -> SpectralPage[IndexSnapshot]:
        rows, total = self._page(SpectralIndex, project_id, limit, offset)
        return SpectralPage[IndexSnapshot](
            items=[_receipt(r, IndexSnapshot) for r in rows], total=total
        )

    def acquisition(self, project_id: str, item_id: str) -> SpectralRecord[AcquisitionSnapshot]:
        return _receipt(self._owned(SpectralAcquisition, project_id, item_id), AcquisitionSnapshot)

    def index(self, project_id: str, item_id: str) -> SpectralRecord[IndexSnapshot]:
        return _receipt(self._owned(SpectralIndex, project_id, item_id), IndexSnapshot)

    def save(self, project_id: str, body: AcquisitionInput) -> SpectralRecord[AcquisitionSnapshot]:
        bands = []
        for selection in body.bands:
            image = self._image(project_id, str(selection.image_id))
            _, bits = load_band(self.settings, image, selection.original_sha256)
            limit = 2**bits - 1
            if (selection.nodata is not None and selection.nodata > limit) or (
                selection.calibration and selection.calibration.white_dn > limit
            ):
                raise ValidationError(
                    f"The calibration or NoData for {selection.name} exceeds its {bits}-bit range"
                )
            bands.append(
                FrozenBand(
                    **selection.model_dump(),
                    width=image.width_px,
                    height=image.height_px,
                    bits=bits,
                )
            )
        snap = AcquisitionSnapshot(
            source_project_id=project_id,
            label=body.label,
            sensor=body.sensor,
            alignment=body.alignment,
            bands=bands,
        )
        raw = snap.model_dump(mode="json")
        digest = canonical_json_sha256(raw)
        query = select(SpectralAcquisition).where(
            SpectralAcquisition.project_id == project_id,
            SpectralAcquisition.content_sha256 == digest,
        )
        row = self.session.scalar(query)
        if row is None:
            try:
                row = SpectralAcquisition(
                    project_id=project_id, snapshot_json=raw, content_sha256=digest
                )
                self.session.add(row)
                self.session.flush()
                self.session.add_all(
                    [
                        SpectralBandBinding(
                            project_id=project_id,
                            acquisition_id=row.id,
                            position=i,
                            image_id=str(b.image_id),
                        )
                        for i, b in enumerate(bands)
                    ]
                )
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                existing = self.session.scalar(query)
                if existing is None:
                    raise ConflictError(
                        "The band sources changed while the acquisition was being registered"
                    ) from None
                row = existing
        return _receipt(row, AcquisitionSnapshot)

    def _planes(
        self,
        project_id: str,
        acquisition: SpectralRecord[AcquisitionSnapshot],
        indices: tuple[int, ...],
    ) -> Planes:
        rows = self.session.scalars(
            select(SpectralBandBinding)
            .where(
                SpectralBandBinding.acquisition_id == str(acquisition.id),
                SpectralBandBinding.project_id == project_id,
            )
            .order_by(SpectralBandBinding.position)
        ).all()
        bands = acquisition.snapshot.bands
        if [row.position for row in rows] != list(range(len(bands))):
            raise ConflictError("The acquisition is missing a recorded band binding")
        result: Planes = {}
        for index in set(indices):
            if not 0 <= index < len(bands):
                raise ValidationError("Select a band present in this acquisition")
            image = self._image(project_id, rows[index].image_id)
            band = bands[index]
            values, bits = load_band(self.settings, image, band.original_sha256)
            if (image.width_px, image.height_px, bits) != (band.width, band.height, band.bits):
                raise ConflictError("The original band layout differs from its acquisition receipt")
            result[index] = values
        return result

    def display(self, project_id: str, item_id: str, channels: tuple[int, int, int]) -> bytes:
        acquisition = self.acquisition(project_id, item_id)
        return encode_rgba(
            composite(
                acquisition.snapshot, channels, self._planes(project_id, acquisition, channels)
            )
        )

    def _calculate(
        self, project_id: str, acquisition_id: str, inputs: IndexInput
    ) -> tuple[IndexSnapshot, NDArray[np.float32] | None]:
        acquisition = self.acquisition(project_id, acquisition_id)
        if acquisition.content_sha256 != inputs.acquisition_sha256:
            raise ConflictError("The acquisition checksum differs from the selected analysis input")
        planes = self._planes(project_id, acquisition, (inputs.positive, inputs.negative))
        result, samples = normalized_difference(acquisition.snapshot, inputs, planes)
        return IndexSnapshot(
            acquisition=acquisition.snapshot, selection=inputs, result=result
        ), samples

    def analyze(
        self, project_id: str, acquisition_id: str, inputs: IndexInput
    ) -> SpectralRecord[IndexSnapshot]:
        snapshot, _ = self._calculate(project_id, acquisition_id, inputs)
        raw = snapshot.model_dump(mode="json")
        digest = canonical_json_sha256(raw)
        query = select(SpectralIndex).where(
            SpectralIndex.project_id == project_id,
            SpectralIndex.acquisition_id == acquisition_id,
            SpectralIndex.content_sha256 == digest,
        )
        row = self.session.scalar(query)
        if row is None:
            row = SpectralIndex(
                project_id=project_id,
                acquisition_id=acquisition_id,
                snapshot_json=raw,
                content_sha256=digest,
            )
            self.session.add(row)
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                existing = self.session.scalar(query)
                if existing is None:
                    raise ConflictError(
                        "The acquisition changed while the index was being saved"
                    ) from None
                row = existing
        return _receipt(row, IndexSnapshot)

    def replay(
        self, project_id: str, item_id: str, digest: str | None = None
    ) -> tuple[SpectralRecord[IndexSnapshot], NDArray[np.float32] | None]:
        row = self._owned(SpectralIndex, project_id, item_id)
        saved = _receipt(row, IndexSnapshot)
        if digest is not None and digest != saved.content_sha256:
            raise ConflictError("The selected index checksum differs from its frozen study result")
        computed, samples = self._calculate(
            project_id, row.acquisition_id, saved.snapshot.selection
        )
        if computed != saved.snapshot:
            raise ConflictError("Replayed spectral samples differ from the frozen result")
        return saved, samples

    def raster(self, project_id: str, item_id: str) -> bytes:
        _, samples = self.replay(project_id, item_id)
        if samples is None:
            raise ValidationError(
                "The saved index is withheld. Review the recorded calibration and alignment."
            )
        return encode_index(samples)
