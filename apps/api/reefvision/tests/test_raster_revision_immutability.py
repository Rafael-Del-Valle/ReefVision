from __future__ import annotations

import pytest

from reefvision.config import Settings
from reefvision.domain.errors import ConflictError
from reefvision.schemas.raster_edits import RasterEditPoint, RasterEditStroke
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.raster_edits import write_raster_mask_revision


def _stroke(x: float, y: float) -> RasterEditStroke:
    return RasterEditStroke(points=[RasterEditPoint(x=x, y=y)])


def test_existing_raster_revision_is_never_replaced(test_settings: Settings) -> None:
    project_storage_root = "projects/raster-immutability"
    resolve_managed_project_path(test_settings, project_storage_root).mkdir(
        parents=True,
        exist_ok=True,
    )

    _, destination, _, _ = write_raster_mask_revision(
        test_settings,
        project_storage_root=project_storage_root,
        image_id="image-1",
        mask_annotation_id="mask-1",
        revision=1,
        source_relative_path=None,
        expected_width=64,
        expected_height=64,
        strokes=[_stroke(12, 12)],
        brush_radius=4,
        mode="paint",
    )
    original_bytes = destination.read_bytes()

    with pytest.raises(ConflictError, match="revision already exists"):
        write_raster_mask_revision(
            test_settings,
            project_storage_root=project_storage_root,
            image_id="image-1",
            mask_annotation_id="mask-1",
            revision=1,
            source_relative_path=None,
            expected_width=64,
            expected_height=64,
            strokes=[_stroke(48, 48)],
            brush_radius=4,
            mode="paint",
        )

    assert destination.read_bytes() == original_bytes
