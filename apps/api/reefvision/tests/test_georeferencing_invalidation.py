"""Task 19E stale-result invalidation lifecycle."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.georeferencing_invalidation import (
    STALE_REASON_CALIBRATION_CHANGED,
    STALE_REASON_CONFIGURATION_HASH_MISMATCH,
    STALE_REASON_PROJECT_SURFACE_REFERENCE_CHANGED,
    GeoreferencingInvalidationService,
)


class FakeSession:
    def __init__(self, *, rowcount: int = 3) -> None:
        self.rowcount = rowcount
        self.statements: list[object] = []

    def execute(self, statement: object) -> object:
        self.statements.append(statement)

        return SimpleNamespace(
            rowcount=self.rowcount,
        )


def compiled_parameters(
    statement: object,
) -> dict[str, object]:
    return statement.compile().params  # type: ignore[attr-defined]


def test_mark_video_stale_updates_fresh_video_rows() -> None:
    session = FakeSession(rowcount=4)

    count = GeoreferencingInvalidationService(
        session  # type: ignore[arg-type]
    ).mark_video_stale(
        "video-1",
        reason=STALE_REASON_CALIBRATION_CHANGED,
    )

    assert count == 4
    assert len(session.statements) == 1

    parameters = compiled_parameters(session.statements[0])

    assert "video-1" in parameters.values()
    assert STALE_REASON_CALIBRATION_CHANGED in parameters.values()


def test_mark_project_stale_updates_project_rows() -> None:
    session = FakeSession(rowcount=7)

    count = GeoreferencingInvalidationService(
        session  # type: ignore[arg-type]
    ).mark_project_stale(
        "project-1",
        reason=(STALE_REASON_PROJECT_SURFACE_REFERENCE_CHANGED),
    )

    assert count == 7

    parameters = compiled_parameters(session.statements[0])

    assert "project-1" in parameters.values()


def test_hash_mismatch_marks_mismatched_configuration() -> None:
    session = FakeSession(rowcount=2)

    count = GeoreferencingInvalidationService(
        session  # type: ignore[arg-type]
    ).mark_hash_mismatch_stale(
        "video-1",
        current_configuration_hash="A" * 64,
    )

    assert count == 2

    parameters = compiled_parameters(session.statements[0])

    assert "video-1" in parameters.values()
    assert "a" * 64 in parameters.values()
    assert STALE_REASON_CONFIGURATION_HASH_MISMATCH in parameters.values()


def test_invalid_configuration_hash_is_rejected() -> None:
    service = GeoreferencingInvalidationService(
        FakeSession()  # type: ignore[arg-type]
    )

    with pytest.raises(
        ValidationError,
        match="64-character SHA-256",
    ):
        service.mark_hash_mismatch_stale(
            "video-1",
            current_configuration_hash="invalid",
        )


def test_blank_reason_is_rejected() -> None:
    service = GeoreferencingInvalidationService(
        FakeSession()  # type: ignore[arg-type]
    )

    with pytest.raises(
        ValidationError,
        match="cannot be blank",
    ):
        service.mark_video_stale(
            "video-1",
            reason="   ",
        )
