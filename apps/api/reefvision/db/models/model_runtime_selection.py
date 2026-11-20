"""A researcher's immutable, reviewed local model and runtime configuration."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reefvision.db.base import Base
from reefvision.db.models.project import utc_now


class ModelRuntimeSelection(Base):
    __tablename__ = "model_runtime_selections"
    __table_args__ = (
        UniqueConstraint("project_id", "content_sha256", name="uq_model_runtime_selection"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_registrations.id"), index=True
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_id_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
