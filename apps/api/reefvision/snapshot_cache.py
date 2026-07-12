"""Small in-process snapshot cache for lightweight bootstrap responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class CachedSnapshot(Generic[T]):
    value: T
    checked_at: datetime
    stale: bool
    error: str | None = None


@dataclass
class _CacheEntry:
    value: object
    checked_at: datetime


_CACHE: dict[str, _CacheEntry] = {}
_LOCK = Lock()


def get_cached_snapshot(
    key: str,
    compute: Callable[[], T],
    *,
    ttl_seconds: int | None,
    refresh: bool = False,
) -> CachedSnapshot[T]:
    now = datetime.now(UTC)
    with _LOCK:
        cached = _CACHE.get(key)

    if cached is not None and not refresh and not _expired(cached.checked_at, now, ttl_seconds):
        return CachedSnapshot(
            value=cached.value,  # type: ignore[arg-type]
            checked_at=cached.checked_at,
            stale=False,
        )

    try:
        value = compute()
    except Exception as exc:
        if cached is None:
            raise
        return CachedSnapshot(
            value=cached.value,  # type: ignore[arg-type]
            checked_at=cached.checked_at,
            stale=True,
            error=str(exc),
        )

    checked_at = datetime.now(UTC)
    with _LOCK:
        _CACHE[key] = _CacheEntry(value=value, checked_at=checked_at)
    return CachedSnapshot(value=value, checked_at=checked_at, stale=False)


def clear_cached_snapshots(prefix: str | None = None) -> None:
    with _LOCK:
        if prefix is None:
            _CACHE.clear()
            return
        for key in [item for item in _CACHE if item.startswith(prefix)]:
            _CACHE.pop(key, None)


def _expired(
    checked_at: datetime,
    now: datetime,
    ttl_seconds: int | None,
) -> bool:
    if ttl_seconds is None:
        return False
    return (now - checked_at).total_seconds() > ttl_seconds
