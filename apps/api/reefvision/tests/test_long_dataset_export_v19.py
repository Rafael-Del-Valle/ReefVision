from pathlib import Path

from reefvision.storage.datasets import copy_export_image
from reefvision.storage.projects import filesystem_io_path


def test_export_preserves_bytes_under_a_long_managed_training_directory(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"immutable source image bytes")
    output = tmp_path
    while len(str(output)) < 270:
        output = output / "a-research-project-with-a-long-directory-name"
    filesystem_io_path(output).mkdir(parents=True)
    target = output / "image.png"
    copy_export_image(source, target)
    assert filesystem_io_path(target).read_bytes() == source.read_bytes()
