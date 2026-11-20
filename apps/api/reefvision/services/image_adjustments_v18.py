"""Immutable image adjustment history and verified model-input rendition lookup."""

from datetime import UTC
from pathlib import Path
from typing import Any

from pydantic import ValidationError as SchemaValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.image import ImageAsset
from reefvision.db.models.image_adjustment import ImageAdjustmentRecipe
from reefvision.db.models.model_registration import ModelRegistration
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.image_adjustments_v18 import (
    ImageAdjustmentDraft,
    ImageAdjustmentPage,
    ImageAdjustmentPin,
    ImageAdjustmentReceipt,
    ImageAdjustmentRecord,
)
from reefvision.services.model_runtime import verify_checkpoint
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.image_adjustments_v18 import (
    AdjustmentRendition,
    adjustment_cache_path,
    publish_adjusted_rendition,
    render_managed_adjustment,
    verify_cached_rendition,
    verify_original,
)


def verify_receipt(body: object, digest: str) -> ImageAdjustmentReceipt:
    try:
        receipt = ImageAdjustmentReceipt.model_validate(body)
    except SchemaValidationError as exc:
        raise ConflictError("The image adjustment receipt is invalid") from exc
    if not isinstance(body, dict) or canonical_json_sha256(body) != digest:
        raise ConflictError("The image adjustment receipt checksum does not match")
    if body != receipt.model_dump(mode="json"):
        raise ConflictError("The image adjustment receipt is missing canonical fields")
    return receipt


def image_adjustment_pin(record: ImageAdjustmentRecord) -> ImageAdjustmentPin:
    return ImageAdjustmentPin(
        recipe_id=record.id,
        content_sha256=record.content_sha256,
        original_sha256=record.receipt.original_sha256,
        rendition_sha256=record.receipt.rendition_sha256,
    )


def adjusted_inference_binding(
    session: Session,
    settings: Settings,
    project_id: str,
    image_ids: list[str],
    pin: ImageAdjustmentPin,
    model: ModelRegistration,
) -> dict[str, Any]:
    """Admit one explicit verified adjusted input to an existing inference job."""
    if len(image_ids) != 1 or model.project_id != project_id:
        raise ValidationError(
            "Adjusted inference must select exactly one original image in the model's project"
        )
    ImageAdjustmentService(session, settings).verified_input(project_id, image_ids[0], pin)
    verify_checkpoint(settings, model, model.sha256, model.file_size_bytes)
    return {"image_adjustment": pin.model_dump(mode="json"), "checkpoint_sha256": model.sha256}


def adjusted_input_provenance(record: ImageAdjustmentRecord) -> dict[str, Any]:
    receipt = record.receipt
    return {
        "kind": "adjusted_rgb8",
        **image_adjustment_pin(record).model_dump(mode="json"),
        "rgb_sha256": receipt.rgb_sha256,
        "pixel_axes": receipt.pixel_axes,
        "original_project_id": str(receipt.project_id),
        "original_image_id": str(receipt.image_id),
        "width_px": receipt.width_px,
        "height_px": receipt.height_px,
    }


class ImageAdjustmentService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _image(self, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("The image for this adjustment is unavailable")
        return image

    def _row(self, image: ImageAsset, recipe_id: str) -> ImageAdjustmentRecipe:
        row = self.session.get(ImageAdjustmentRecipe, recipe_id)
        if row is None or row.image_id != image.id or row.project_id != image.project_id:
            raise NotFoundError("This recipe does not belong to the selected original image")
        return row

    def _record(self, image: ImageAsset, row: ImageAdjustmentRecipe) -> ImageAdjustmentRecord:
        receipt = verify_receipt(row.receipt_json, row.content_sha256)
        if (receipt.original_sha256, receipt.width_px, receipt.height_px) != (
            image.sha256,
            image.width_px,
            image.height_px,
        ):
            raise ConflictError(
                "The recipe no longer matches the original image and its pixel grid"
            )
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
        return ImageAdjustmentRecord(
            id=row.id,
            project_id=row.project_id,
            image_id=row.image_id,
            content_sha256=row.content_sha256,
            receipt=receipt,
            created_at=created,
        )

    def list(self, image_id: str, page: int, page_size: int) -> ImageAdjustmentPage:
        image = self._image(image_id)
        condition = (
            ImageAdjustmentRecipe.image_id == image.id,
            ImageAdjustmentRecipe.project_id == image.project_id,
        )
        rows = self.session.scalars(
            select(ImageAdjustmentRecipe)
            .where(*condition)
            .order_by(ImageAdjustmentRecipe.created_at.desc(), ImageAdjustmentRecipe.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        total = self.session.scalar(
            select(func.count()).select_from(ImageAdjustmentRecipe).where(*condition)
        )
        return ImageAdjustmentPage(
            items=[self._record(image, row) for row in rows],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    def get(self, image_id: str, recipe_id: str) -> ImageAdjustmentRecord:
        image = self._image(image_id)
        return self._record(image, self._row(image, recipe_id))

    def _render(self, image: ImageAsset, draft: ImageAdjustmentDraft) -> AdjustmentRendition:
        if draft.original_sha256 != image.sha256:
            raise ConflictError(
                "The original image checksum changed. Reopen the image before adjusting it."
            )
        return render_managed_adjustment(self.settings, image, draft.parameters)

    def preview(self, image_id: str, draft: ImageAdjustmentDraft) -> AdjustmentRendition:
        return self._render(self._image(image_id), draft)

    def save(self, image_id: str, draft: ImageAdjustmentDraft) -> ImageAdjustmentRecord:
        image = self._image(image_id)
        rendition = self._render(image, draft)
        body = ImageAdjustmentReceipt(
            project_id=image.project_id,
            image_id=image.id,
            original_sha256=image.sha256,
            width_px=image.width_px,
            height_px=image.height_px,
            parameters=draft.parameters,
            rendition_sha256=rendition.rendition_sha256,
            rgb_sha256=rendition.rgb_sha256,
        ).model_dump(mode="json")
        digest = canonical_json_sha256(body)
        path = adjustment_cache_path(
            self.settings, image.project.storage_root, rendition.rendition_sha256
        )
        publish_adjusted_rendition(path, rendition)
        lookup = select(ImageAdjustmentRecipe).where(
            ImageAdjustmentRecipe.image_id == image.id,
            ImageAdjustmentRecipe.content_sha256 == digest,
        )
        existing = self.session.scalar(lookup)
        if existing is not None:
            return self._record(image, existing)
        row = ImageAdjustmentRecipe(
            project_id=image.project_id,
            image_id=image.id,
            content_sha256=digest,
            receipt_json=body,
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(lookup)
            if existing is None:
                raise
            row = existing
        return self._record(image, row)

    def _rendition_path(self, image: ImageAsset, record: ImageAdjustmentRecord) -> Path:
        verify_original(self.settings, image)
        receipt = record.receipt
        path = adjustment_cache_path(
            self.settings, image.project.storage_root, receipt.rendition_sha256
        )
        if not verify_cached_rendition(path, receipt.rendition_sha256):
            rebuilt = render_managed_adjustment(self.settings, image, receipt.parameters)
            if (rebuilt.rendition_sha256, rebuilt.rgb_sha256) != (
                receipt.rendition_sha256,
                receipt.rgb_sha256,
            ):
                raise ConflictError(
                    "The adjusted rendition could not reproduce its pinned byte and pixel checksums"
                )
            publish_adjusted_rendition(path, rebuilt)
        return path

    def rendition(self, image_id: str, recipe_id: str) -> Path:
        image = self._image(image_id)
        record = self._record(image, self._row(image, recipe_id))
        return self._rendition_path(image, record)

    def verified_input(
        self,
        project_id: str,
        image_id: str,
        pin: ImageAdjustmentPin,
    ) -> tuple[Path, ImageAdjustmentRecord]:
        """Return a validated same-grid local input for inference or paired evaluation."""
        image = self._image(image_id)
        if image.project_id != project_id:
            raise ValidationError("An adjusted model input must belong to this project")
        record = self._record(image, self._row(image, str(pin.recipe_id)))
        if image_adjustment_pin(record) != pin:
            raise ConflictError(
                "The saved image adjustment does not match the requested source and rendition pins"
            )
        return self._rendition_path(image, record), record
