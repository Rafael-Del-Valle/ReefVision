"""Managed diagnostic-bundle helpers with recursive privacy redaction."""

from __future__ import annotations

import json
import os
import platform
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

DIAGNOSTIC_BUNDLE_VERSION = "2.0"
DIAGNOSTIC_MAX_LOG_BYTES = 32 * 1024
DIAGNOSTIC_PAYLOAD_FILENAME = "diagnostic-bundle.json"

_WINDOWS_USER_PATH_RE = re.compile(r"([A-Za-z]:\\Users\\)([^\\]+)", re.IGNORECASE)
_POSIX_USER_PATH_RE = re.compile(r"(/(?:home|Users)/)([^/]+)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_IPV4_RE = re.compile(
    r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_URL_CREDENTIAL_RE = re.compile(r"(://)([^/@\s:]+):([^/@\s]+)@")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access[_-]?token|token|api[_-]?key|key|secret|password|signature)=)[^&#\s]+"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|secret|password|passwd|authorization|private[_-]?key|credential)\b\s*[:=]\s*)([^\s,;\}\]]+)"
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:token|secret|password|passwd|api[_-]?key|authorization|cookie|private[_-]?key|credential)"
)


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
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                redacted[key_text] = "<redacted>" if item not in {None, ""} else item
            else:
                redacted[key_text] = redact_value(
                    item,
                    settings=settings,
                    strict_redaction=strict_redaction,
                )
        return redacted
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [
            redact_value(item, settings=settings, strict_redaction=strict_redaction)
            for item in value
        ]
    return value


def redact_text(value: str, *, settings: Settings, strict_redaction: bool) -> str:
    redacted = value
    for original, replacement in sorted(
        _path_replacements(settings).items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if original:
            redacted = redacted.replace(original, replacement)
            redacted = redacted.replace(original.replace("\\", "/"), replacement)

    redacted = _WINDOWS_USER_PATH_RE.sub(r"\1<user>", redacted)
    redacted = _POSIX_USER_PATH_RE.sub(r"\1<user>", redacted)
    redacted = _URL_CREDENTIAL_RE.sub(r"\1<redacted>:<redacted>@", redacted)
    redacted = _QUERY_SECRET_RE.sub(r"\1<redacted>", redacted)
    redacted = _BEARER_RE.sub("Bearer <redacted>", redacted)
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1<redacted>", redacted)
    if strict_redaction:
        redacted = _EMAIL_RE.sub("<redacted-email>", redacted)
        redacted = _PHONE_RE.sub("<redacted-phone>", redacted)
        redacted = _IPV4_RE.sub("<redacted-ip>", redacted)
        username = os.environ.get("USERNAME") or os.environ.get("USER")
        if username:
            redacted = redacted.replace(username, "<user>")
        hostname = platform.node()
        if hostname:
            redacted = redacted.replace(hostname, "<host>")
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
                safe_name = Path(name).name
                archive.writestr(
                    f"logs/{safe_name}",
                    content.encode("utf-8", errors="replace"),
                )
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
