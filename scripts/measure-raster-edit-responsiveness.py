"""Measure the real high-resolution raster revision path for release evidence."""

from __future__ import annotations

import json
import platform
import statistics
import tempfile
from pathlib import Path
from time import perf_counter

from reefvision.config import Settings
from reefvision.schemas.raster_edits import RasterEditPoint, RasterEditStroke
from reefvision.storage.raster_edits import write_raster_mask_revision


def main() -> None:
    width, height = 4096, 3072
    durations: list[float] = []
    with tempfile.TemporaryDirectory(prefix="reefvision-raster-benchmark-") as directory:
        settings = Settings(data_dir=Path(directory))
        project_root = settings.resolved_data_dir / "projects" / "benchmark"
        project_root.mkdir(parents=True)
        points = [
            RasterEditPoint(x=64 + index * 16, y=64 + (index % 40) * 48) for index in range(200)
        ]
        stroke = RasterEditStroke(points=points)
        for iteration in range(5):
            started = perf_counter()
            relative_path, destination, area, bounds = write_raster_mask_revision(
                settings,
                project_storage_root="projects/benchmark",
                image_id="high-resolution-image",
                mask_annotation_id=f"benchmark-mask-{iteration}",
                revision=1,
                source_relative_path=None,
                expected_width=width,
                expected_height=height,
                strokes=[stroke],
                brush_radius=12,
                mode="paint",
            )
            durations.append((perf_counter() - started) * 1000)
            if not relative_path or destination is None or area <= 0 or bounds is None:
                raise RuntimeError("Raster benchmark did not create a valid immutable revision")

    print(
        json.dumps(
            {
                "scenario": "4096x3072 raster paint, 200-point stroke, immutable PNG",
                "iterations": len(durations),
                "median_ms": round(statistics.median(durations), 3),
                "min_ms": round(min(durations), 3),
                "max_ms": round(max(durations), 3),
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
