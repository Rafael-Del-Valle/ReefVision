"""Seed an isolated database for the guarded Phase 5 Chromium acceptance test.

This is deterministic engineering data, not biological validation. Run Alembic first and
set REEFVISION_DATA_DIR/REEFVISION_DATABASE_URL to a disposable location.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from reefvision.config import get_settings
from reefvision.db.models import LabelClass, Project, VideoAsset
from reefvision.db.session import create_database_engine, create_session_factory

PROJECT_NAME = "Phase 5 synthetic gape acceptance"


def main() -> None:
    settings = get_settings()
    settings.ensure_directories()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        existing = session.scalar(select(Project).where(Project.name == PROJECT_NAME))
        if existing is not None:
            print(json.dumps({"project_id": existing.id, "created": False}))
            return
        project = Project(
            name=PROJECT_NAME,
            slug="phase-5-synthetic-gape-acceptance",
            description="Deterministic synthetic engineering fixture; not biological validation.",
            storage_root="projects/phase-5-synthetic-gape-acceptance",
            default_annotation_type="bbox",
        )
        session.add(project)
        session.flush()
        session.add(
            LabelClass(
                project_id=project.id,
                class_index=0,
                display_order=0,
                name="Synthetic fish",
                scientific_name=None,
                state_name=None,
                description="Engineering-only fish fixture",
                display_color="#22C55E",
            )
        )
        managed_path = (
            settings.resolved_data_dir
            / project.storage_root
            / "videos"
            / "phase5-synthetic-gape.mp4"
        )
        managed_path.parent.mkdir(parents=True, exist_ok=True)
        managed_path.write_bytes(b"ReefVision Phase 5 synthetic metadata fixture")
        video = VideoAsset(
            project_id=project.id,
            original_filename="phase5-synthetic-gape.mp4",
            managed_path=str(managed_path),
            sha256="5" * 64,
            media_type="video/mp4",
            width_px=320,
            height_px=180,
            frame_count=12,
            fps=10.0,
            duration_seconds=1.2,
            metadata_json={"fixture": "synthetic_engineering", "scientific_validation": False},
            status="imported",
            revision=1,
        )
        session.add(video)
        session.commit()
        print(json.dumps({"project_id": project.id, "video_id": video.id, "created": True}))
    engine.dispose()


if __name__ == "__main__":
    main()
