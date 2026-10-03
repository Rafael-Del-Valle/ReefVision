"""Temporary artifact lifecycle for optional pose interoperability."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reefvision.domain.errors import ValidationError


def load_exchange(sio: Any, content: bytes, filename: str, fmt: str) -> Any:
    with TemporaryDirectory(prefix="reefvision-pose-import-") as temp:
        source = Path(temp) / Path(filename).name
        source.write_bytes(content)
        if fmt == "slp":
            return sio.load_slp(str(source), open_videos=False)
        if fmt == "nwb":
            from reefvision.storage.pose_nwb import read_nwb

            return read_nwb(sio, source)
        from reefvision.storage.pose_exchange_text import read_text

        return read_text(sio, source, fmt)


def save_exchange(sio: Any, labels: Any, stem: str, fmt: str) -> tuple[str, str, bytes]:
    with TemporaryDirectory(prefix="reefvision-pose-export-") as temp:
        root = Path(temp)
        if fmt == "slp":
            path = root / f"{stem}.pose.slp"
            sio.save_slp(labels, str(path), embed="all", verbose=False)
            media_type = "application/octet-stream"
        elif fmt == "nwb":
            from reefvision.storage.pose_nwb import write_nwb

            path = root / f"{stem}.pose.nwb"
            write_nwb(sio, labels, path)
            media_type = "application/x-hdf5"
        elif fmt in {"coco", "dlc_csv", "ultralytics_pose"}:
            from reefvision.storage.pose_exchange_text import write_text

            path, media_type = write_text(sio, labels, root, fmt)
        else:
            raise ValidationError(f"Unsupported pose interoperability format: {fmt}")
        return path.name, media_type, path.read_bytes()
