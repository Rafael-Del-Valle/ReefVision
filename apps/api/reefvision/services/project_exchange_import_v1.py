"""CoralVision 1.0 import extensions for portable training state."""

from __future__ import annotations

from collections.abc import BinaryIO

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import TrainingDraft
from reefvision.schemas.project_exchange import ProjectExchangeImportResponse
from reefvision.services import project_exchange_import as base_import


def _register_v1_sections() -> None:
    base_import.SECTION_MODELS["training_drafts"] = TrainingDraft
    if "training_drafts" not in base_import.SECTION_ORDER:
        model_index = base_import.SECTION_ORDER.index("models")
        base_import.SECTION_ORDER.insert(model_index + 1, "training_drafts")


def import_project_exchange_v1(
    source: BinaryIO,
    session: Session,
    settings: Settings,
    *,
    project_name: str | None = None,
) -> ProjectExchangeImportResponse:
    """Import the complete 1.0 portable record inventory into a new project."""

    _register_v1_sections()
    return base_import.import_project_exchange(
        source,
        session,
        settings,
        project_name=project_name,
    )
