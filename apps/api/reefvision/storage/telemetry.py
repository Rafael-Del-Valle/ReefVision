"""Telemetry file discovery/read/write boundaries; no dataset-specific behavior."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.airdata import parse_airdata_csv
from reefvision.geospatial.dji_srt import parse_dji_srt
from reefvision.geospatial.synchronization import IndexedTelemetrySource

MAX_SRT_BYTES = 32 * 1024 * 1024
MAX_AIRDATA_BYTES = 64 * 1024 * 1024


def matching_srt_name(video_name: str, telemetry_name: str) -> bool:
    video, telemetry = Path(video_name), Path(telemetry_name)
    return (
        telemetry.suffix.casefold() == ".srt" and telemetry.stem.casefold() == video.stem.casefold()
    )


def find_paired_srt(video_path: Path) -> Path | None:
    try:
        matches = sorted(
            (
                path
                for path in video_path.parent.iterdir()
                if path.is_file() and matching_srt_name(video_path.name, path.name)
            ),
            key=lambda path: path.name,
        )
    except OSError as exc:
        raise ValidationError("Cannot inspect video directory for telemetry") from exc
    if len(matches) > 1:
        raise ValidationError("Multiple matching SRT telemetry files; choose an unambiguous pair")
    return matches[0] if matches else None


def read_srt_stream(stream: BinaryIO) -> tuple[bytes, IndexedTelemetrySource]:
    data = stream.read(MAX_SRT_BYTES + 1)
    if len(data) > MAX_SRT_BYTES:
        raise ValidationError("SRT telemetry exceeds the 32 MiB limit")
    try:
        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = data.decode(encoding)
    except UnicodeError as exc:
        raise ValidationError("SRT telemetry must use UTF-8 or BOM-marked UTF-16") from exc
    return data, IndexedTelemetrySource(parse_dji_srt(text))


def load_dji_srt(path: Path) -> IndexedTelemetrySource:
    try:
        with path.open("rb") as stream:
            return read_srt_stream(stream)[1]
    except OSError as exc:
        raise ValidationError("SRT telemetry source is missing or unreadable") from exc


def read_airdata_stream(stream: BinaryIO) -> tuple[bytes, IndexedTelemetrySource]:
    data = stream.read(MAX_AIRDATA_BYTES + 1)
    if len(data) > MAX_AIRDATA_BYTES:
        raise ValidationError("AirData telemetry exceeds the 64 MiB limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValidationError("AirData telemetry must use UTF-8") from exc
    return data, IndexedTelemetrySource(parse_airdata_csv(text))


def load_airdata_csv(path: Path) -> IndexedTelemetrySource:
    try:
        with path.open("rb") as stream:
            return read_airdata_stream(stream)[1]
    except OSError as exc:
        raise ValidationError("AirData telemetry source is missing or unreadable") from exc


def write_airdata(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def remove_airdata(path: Path) -> None:
    path.unlink(missing_ok=True)


def write_srt(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def remove_srt(path: Path) -> None:
    path.unlink(missing_ok=True)


@contextmanager
def open_video_source(path: Path) -> Iterator[BinaryIO]:
    try:
        stream = path.open("rb")
    except OSError as exc:
        raise ValidationError("Video source is missing or unreadable") from exc
    with stream:
        yield stream
