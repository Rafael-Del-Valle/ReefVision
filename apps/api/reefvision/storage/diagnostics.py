"""Managed diagnostic-bundle helpers for Milestone 8."""

from __future__ import annotations

import json
import os
import re
import zipfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path

DIAGNOSTIC_BUNDLE_VERSION = "1.0"
DIAGNOSTIC_MAX_LOG_BYTES = 32 * 1024
DIAGNOSTIC_PAYLOAD_FILENAME = "diagnostic-bundle.json"

_WINDOWS_USER_PATH_RE = re.compile(r"([A-Za-z]:\\Users\\)([^\\]+)", re.IGNORECASE)
_POSIX_USER_PATH_RE = re.compile(r"(/home/)([^/]+)")


def default_diagnostic_bundle_path(job_id: str, *, created_at_label: str) -> str:
    return f"diagnostics/reefvision-diagnostics-{created_at_label}-{job_id[:8]}.zip"


def diagnostic_bundle_path(settings: Settings, relative_path: str) -> Path:
    return resolve_managed_project_path(settings, relative_path)


def tail_text_file(path: Path, *, max_bytes: int = DIAGNOSTIC_MAX_LOG_BYTES) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(size - max_bytes, 0))
        payload = handle.read()
    return payload.decode("utf-8", errors="replace")


def redact_value(value: Any, *, settings: Settings, strict_redaction: bool) -> Any:
    if isinstance(value, str):
        return redact_text(value, settings=settings, strict_redaction=strict_redaction)
    if isinstance(value, Mapping):
        return {
            str(key): redact_value(item, settings=settings, strict_redaction=strict_redaction)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [
            redact_value(item, settings=settings, strict_redaction=strict_redaction)
            for item in value
        ]
    return value


def redact_text(value: str, *, settings: Settings, strict_redaction: bool) -> str:
    redacted = value

    for original, replacement in _path_replacements(settings).items():
        if original:
            redacted = redacted.replace(original, replacement)

    redacted = _WINDOWS_USER_PATH_RE.sub(r"\1<user>", redacted)
    redacted = _POSIX_USER_PATH_RE.sub(r"\1<user>", redacted)
    if strict_redaction:
        username = os.environ.get("USERNAME") or os.environ.get("USER")
        if username:
            redacted = redacted.replace(username, "<user>")
    return redacted


def write_diagnostic_bundle(
    path: Path,
    *,
    payload: dict[str, Any],
    log_snippets: dict[str, str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(DIAGNOSTIC_PAYLOAD_FILENAME, canonical_json_bytes(payload))
            for name, content in sorted(log_snippets.items()):
                archive.writestr(f"logs/{name}", content.encode("utf-8", errors="replace"))
        os.replace(temporary, path)
        return path.stat().st_size
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def read_diagnostic_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValidationError("Diagnostic bundle is missing")
    with (
        zipfile.ZipFile(path, mode="r") as archive,
        archive.open(DIAGNOSTIC_PAYLOAD_FILENAME, mode="r") as handle,
    ):
        return cast(dict[str, Any], json.loads(handle.read().decode("utf-8")))


def _path_replacements(settings: Settings) -> dict[str, str]:
    replacements = {
        str(settings.resolved_data_dir): "%REEFVISION_DATA_DIR%",
    }
    for key in ("USERPROFILE", "HOME", "HOMEPATH"):
        value = os.environ.get(key)
        if value:
            replacements[value] = "%USER_HOME%"
    with suppress(RuntimeError):
        replacements[str(Path.home())] = "%USER_HOME%"
    return replacements
