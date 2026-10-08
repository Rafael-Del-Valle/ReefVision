"""Compatibility entry points for retired installer model seeding.

ReefVision 1.0 ships architectures without weights. Startup must not scan legacy
bundle locations, copy their files, or modify existing researcher models/jobs.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings


def install_bundled_catalog_models(settings: Settings) -> tuple[list[str], list[str]]:
    """Leave all model acquisition to explicit researcher registration or training."""
    return [], []


def reconcile_bundled_model_jobs(
    factory: sessionmaker[Session], bundled_catalog_ids: list[str]
) -> None:
    """Never claim legacy downloads succeeded because of an installer bundle."""
    return None
