"""Camera-style JPEG metadata must survive inspection without changing the source.

Synthetic fixtures exercise standard EXIF orientation and embedded ICC bytes.
They do not substitute for physical Canon/Sony camera acceptance.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from reefvision.storage.images import inspect_staged_image


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_camera_jpeg_exif_orientation_and_icc_are_read_only(tmp_path, orientation: int) -> None:
    path = tmp_path / f"camera_orientation_{orientation}.JPG"
    exif = Image.Exif()
    exif[271] = "Synthetic Camera"
    exif[274] = orientation
    # A synthetic profile payload exercises metadata handling; it is not a
    # colorimetrically valid ICC profile and must not be used for color QC.
    icc_payload = b"synthetic-icc-fixture-" + bytes(range(32))
    Image.new("RGB", (23, 13), (12, 45, 90)).save(
        path, format="JPEG", exif=exif, icc_profile=icc_payload
    )
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()

    inspected = inspect_staged_image(path, digest, len(original))

    assert inspected.sha256 == digest
    assert inspected.file_size_bytes == len(original)
    # EXIF orientation is advisory; never silently rotate the scientific
    # pixel coordinate system or change dimensions during import inspection.
    assert (inspected.width_px, inspected.height_px) == (23, 13)
    assert inspected.extension == ".jpg"
    assert inspected.media_type == "image/jpeg"
    assert inspected.metadata["exif"]["Orientation"] == orientation
    assert inspected.metadata["exif"]["Make"] == "Synthetic Camera"
    assert path.read_bytes() == original
