"""Bounded PCM WAV inspection, immutable byte storage and channel waveform reads."""

from __future__ import annotations

import struct
from array import array
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from sys import byteorder
from tempfile import TemporaryDirectory
from typing import IO, Literal

from reefvision.config import Settings
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.bioacoustics import MAX_AUDIO_BYTES, WaveformPeak
from reefvision.storage.images import (
    commit_staged_image,
    original_bytes_match,
    safe_original_name,
    stream_to_staging,
)
from reefvision.storage.projects import resolve_managed_project_path

_PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")


@dataclass(frozen=True)
class PCM:
    channel_count: int
    sample_rate_hz: int
    bits_per_sample: int
    sample_count: int
    data_offset: int

    @property
    def width(self) -> int:
        return self.bits_per_sample // 8

    @property
    def frame_bytes(self) -> int:
        return self.channel_count * self.width


def audio_filename(filename: str | None) -> str:
    name = safe_original_name(filename)
    if Path(name).suffix.casefold() != ".wav":
        raise ValidationError("Choose an uncompressed little-endian PCM WAV file (.wav)")
    if len(name) > 255 or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name):
        raise ValidationError("The WAV original filename is invalid")
    return name


def _decode_format(data: bytes) -> tuple[int, int, int]:
    if len(data) < 16:
        raise ValidationError("The WAV format chunk is truncated")
    code, channels, rate, byte_rate, stride, bits = struct.unpack_from("<HHIIHH", data)
    if code == 0xFFFE:
        if (
            len(data) < 40
            or data[24:40] != _PCM_GUID
            or struct.unpack_from("<HH", data, 16) != (22, bits)
        ):
            raise ValidationError(
                "Extended WAV must declare an integer PCM subtype and full sample width"
            )
    elif code != 1:
        raise ValidationError(
            "Compressed or floating-point WAV is unsupported. Export integer PCM WAV"
        )
    if channels not in (1, 2) or not 8_000 <= rate <= 96_000 or bits not in (8, 16, 24, 32):
        raise ValidationError(
            "WAV support is mono or stereo integer PCM at 8 to 96 kHz and 8, 16, 24 or 32 bits"
        )
    if stride != channels * bits // 8 or byte_rate != rate * stride:
        raise ValidationError("WAV byte rate and sample alignment do not match its PCM format")
    return channels, rate, bits


def inspect_wav(path: Path, size: int) -> PCM:
    with path.open("rb") as stream:
        return inspect_wav_stream(stream, size)


def inspect_wav_stream(stream: IO[bytes], size: int) -> PCM:
    if size < 44 or size > MAX_AUDIO_BYTES:
        raise ValidationError("WAV original is truncated or exceeds 256 MiB")
    header = stream.read(12)
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
        raise ValidationError("A little-endian RIFF WAV header is required")
    declared_size = int.from_bytes(header[4:8], "little") + 8
    if declared_size != size:
        raise ValidationError("The WAV bytes are truncated or do not match the RIFF length")
    format_fields: tuple[int, int, int] | None = None
    frames: tuple[int, int] | None = None
    chunks = 0
    while stream.tell() < size:
        chunks += 1
        if chunks > 1024:
            raise ValidationError("The WAV contains more than 1024 chunks")
        chunk_header = stream.read(8)
        if len(chunk_header) != 8:
            raise ValidationError("The WAV chunk header is truncated")
        chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)
        body = stream.tell()
        end = body + chunk_size
        if end > size:
            raise ValidationError("A declared WAV chunk is truncated")
        if chunk_id == b"fmt ":
            if format_fields is not None or chunk_size > 128:
                raise ValidationError("The WAV format chunk is repeated or unsupported")
            format_fields = _decode_format(stream.read(chunk_size))
        elif chunk_id == b"data":
            if frames is not None or format_fields is None:
                raise ValidationError("A WAV needs one data chunk after its PCM format chunk")
            frames = (body, chunk_size)
        # Common writers omit the final byte of padding when odd data ends at EOF.
        stream.seek(end + (chunk_size % 2 if end < size else 0))
    if format_fields is None or frames is None:
        raise ValidationError("The WAV needs a PCM format and a complete data chunk")
    channels, rate, bits = format_fields
    offset, sample_bytes = frames
    stride = channels * bits // 8
    if not sample_bytes or sample_bytes % stride:
        raise ValidationError("The WAV contains an empty or truncated PCM sample frame")
    return PCM(channels, rate, bits, sample_bytes // stride, offset)


def audio_managed_path(project_root: str, sha256: str) -> str:
    return f"{project_root}/bioacoustics/originals/{sha256}.wav"


class AudioStorage:
    def __init__(self, settings: Settings, project_root: str) -> None:
        self.settings = settings
        self.project_root = project_root

    def _resolve(self, rel: str) -> Path:
        path = resolve_managed_project_path(self.settings, rel)
        if not path.is_relative_to(resolve_managed_project_path(self.settings, self.project_root)):
            raise ValidationError("The original must remain inside its owning project")
        return path

    @contextmanager
    def stage(self, source: IO[bytes]) -> Iterator[tuple[Path, str, int, PCM]]:
        staging = self._resolve(f"{self.project_root}/bioacoustics/staging")
        staging.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=staging) as folder:
            path = Path(folder) / "original.wav"
            digest, size = stream_to_staging(source, path, max_bytes=MAX_AUDIO_BYTES)
            yield path, digest, size, inspect_wav(path, size)

    def verify(self, relative: str, digest: str, size: int | None = None) -> Path:
        path = self._resolve(relative)
        try:
            if not original_bytes_match(
                path, path.stat().st_size if size is None else size, digest
            ):
                raise ConflictError("Managed original does not match its recorded SHA-256 and size")
        except OSError as exc:
            raise ConflictError("Managed original is unavailable") from exc
        return path

    def publish(self, staged: Path, digest: str, size: int) -> str:
        rel = audio_managed_path(self.project_root, digest)
        target = self._resolve(rel)
        try:
            if not target.exists():
                commit_staged_image(staged, target)
            self.verify(rel, digest, size)
        except ValidationError:
            # Concurrent publication never overwrites the winning original.
            self.verify(rel, digest, size)
        return rel


def _channel_limits(raw: bytes, pcm: PCM, channel: int) -> tuple[float, float]:
    if pcm.width == 1:
        values_8 = raw[channel :: pcm.channel_count]
        return (min(values_8) - 128) / 128, (max(values_8) - 128) / 128
    code: Literal["h", "i"] = "h" if pcm.width == 2 else "i"
    values = array(code)
    if pcm.width == 3:
        # Shift packed signed-24 PCM into signed-32 while keeping the normalized magnitude.
        start = channel * pcm.width
        frames = len(raw) // pcm.frame_bytes
        aligned = bytearray(frames * 4)
        for offset in range(3):
            aligned[offset + 1 :: 4] = raw[start + offset :: pcm.frame_bytes]
        values.frombytes(aligned)
    else:
        values.frombytes(raw)
        values = values[channel :: pcm.channel_count]
    if byteorder == "big":
        values.byteswap()
    scale = 2 ** (8 * values.itemsize - 1)
    return min(values) / scale, max(values) / scale


def read_waveform(path: Path, pcm: PCM, channel: int, bins: int) -> list[WaveformPeak]:
    if not 0 <= channel < pcm.channel_count:
        raise ValidationError("Choose an existing zero-based recording channel")
    count = min(bins, pcm.sample_count)
    result = []
    with path.open("rb") as stream:
        stream.seek(pcm.data_offset)
        for index in range(count):
            start = index * pcm.sample_count // count
            end = (index + 1) * pcm.sample_count // count
            remaining = end - start
            minimum, maximum = 1.0, -1.0
            while remaining:
                frames = min(remaining, 65_536)
                length = frames * pcm.frame_bytes
                raw = stream.read(length)
                if len(raw) != length:
                    raise ConflictError("Managed PCM samples became unavailable")
                low, high = _channel_limits(raw, pcm, channel)
                minimum, maximum = min(minimum, low), max(maximum, high)
                remaining -= frames
            result.append(
                WaveformPeak(start_sample=start, end_sample=end, minimum=minimum, maximum=maximum)
            )
    return result
