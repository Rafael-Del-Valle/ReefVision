from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from reefvision.testing.synthetic_acceptance import generate_synthetic_acceptance_dataset


def test_synthetic_acceptance_bundle_is_deterministic_and_measurable(tmp_path: Path) -> None:
    first = generate_synthetic_acceptance_dataset(tmp_path / "first")
    second = generate_synthetic_acceptance_dataset(tmp_path / "second")

    assert first.files == second.files
    assert first.checksums == second.checksums
    assert first.expected["geometry"]["rectangle"]["area_pixels"] == 4800
    assert first.expected["classification_counts"] == {
        "MC": 4,
        "TC": 4,
        "MO": 4,
        "SO": 4,
        "SC": 4,
        "TO": 4,
        "open": 6,
        "closed": 6,
    }

    with Image.open(Path(first.root) / "masks" / "known-area-rectangle.png") as source:
        mask = np.asarray(source.convert("L"), dtype=np.uint8) > 0
    assert int(mask.sum()) == 4800

    metric = np.load(Path(first.root) / "depth" / "metric-depth-metres.npy")
    assert metric.shape == (192, 256)
    assert float(metric.min()) == pytest.approx(0.6)
    assert float(metric.max()) == pytest.approx(1.8)

    avi = (Path(first.root) / "video" / "identity-crossing.avi").read_bytes()
    assert avi[:4] == b"RIFF"
    assert avi[8:12] == b"AVI "

    manifest = json.loads(Path(first.manifest_path).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert set(manifest["files"]) == set(first.files)
    assert manifest["checksums"] == first.checksums
