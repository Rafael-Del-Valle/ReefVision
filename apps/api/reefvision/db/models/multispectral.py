from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class SpectralReceipt:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SpectralAcquisition(SpectralReceipt, Base):
    __tablename__ = "multispectral_acquisitions"
    __table_args__ = (
        UniqueConstraint("project_id", "content_sha256", name="uq_spectral_acquisition"),
    )


class SpectralBandBinding(Base):
    __tablename__ = "multispectral_band_bindings"
    __table_args__ = (
        UniqueConstraint("acquisition_id", "position", name="uq_spectral_position"),
        UniqueConstraint("acquisition_id", "image_id", name="uq_spectral_image"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    acquisition_id: Mapped[str] = mapped_column(
        ForeignKey("multispectral_acquisitions.id", ondelete="CASCADE")
    )
    image_id: Mapped[str] = mapped_column(ForeignKey("images.id"))
    position: Mapped[int] = mapped_column(Integer)


class SpectralIndex(SpectralReceipt, Base):
    __tablename__ = "multispectral_indices"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "acquisition_id", "content_sha256", name="uq_spectral_index"
        ),
    )
    acquisition_id: Mapped[str] = mapped_column(
        ForeignKey("multispectral_acquisitions.id", ondelete="CASCADE")
    )
