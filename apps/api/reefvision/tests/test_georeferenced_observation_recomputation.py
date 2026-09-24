"""Task 19F atomic stale-observation recomputation."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.georeferenced_observation_recomputation import (
    GeoreferencedObservationRecomputationService,
)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.deleted: list[object] = []

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def delete(self, record: object) -> None:
        self.deleted.append(record)


class FakePersistence:
    def __init__(
        self,
        records: list[SimpleNamespace],
    ) -> None:
        self.records = records
        self.persisted: list[tuple[object, str | None]] = []

    def list_for_video(
        self,
        _video_id: str,
    ) -> list[SimpleNamespace]:
        return list(self.records)

    def persist(
        self,
        observation: object,
        *,
        configuration_hash: str | None = None,
    ) -> SimpleNamespace:
        self.persisted.append((observation, configuration_hash))

        return SimpleNamespace(id=str(uuid4()))


class FakeInvalidation:
    def __init__(
        self,
        records: list[SimpleNamespace],
    ) -> None:
        self.records = records
        self.calls: list[tuple[str, str]] = []

    def mark_hash_mismatch_stale(
        self,
        video_id: str,
        *,
        current_configuration_hash: str,
    ) -> int:
        self.calls.append(
            (
                video_id,
                current_configuration_hash,
            )
        )

        count = 0

        for record in self.records:
            if not record.is_stale and record.configuration_hash != current_configuration_hash:
                record.is_stale = True
                record.stale_reason = "configuration_hash_mismatch"
                count += 1

        return count


class FakeGeoreferencing:
    def __init__(
        self,
        *,
        fail: bool = False,
    ) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []
        self.hash_calls = 0

    def configuration_hash(
        self,
        _video_id: str,
    ) -> str:
        self.hash_calls += 1
        return "a" * 64

    def georeference_detection(
        self,
        video_id: str,
        **kwargs: object,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "video_id": video_id,
                **kwargs,
            }
        )

        if self.fail:
            raise ValidationError("synthetic projection failure")

        return SimpleNamespace(id=uuid4())


def record(
    *,
    stale: bool,
    configuration_hash: str = "a" * 64,
    method: str = "bbox_center",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid4()),
        frame_index=12,
        track_id=str(uuid4()),
        detection_id=str(uuid4()),
        bbox_x_min=10.0,
        bbox_y_min=20.0,
        bbox_x_max=30.0,
        bbox_y_max=40.0,
        representative_pixel_x=22.0,
        representative_pixel_y=31.0,
        representative_pixel_method=method,
        configuration_hash=configuration_hash,
        is_stale=stale,
        stale_reason=("synthetic_stale" if stale else None),
    )


def service(
    records: list[SimpleNamespace],
    *,
    fail: bool = False,
) -> tuple[
    GeoreferencedObservationRecomputationService,
    FakeSession,
    FakePersistence,
    FakeGeoreferencing,
]:
    session = FakeSession()
    persistence = FakePersistence(records)
    georeferencing = FakeGeoreferencing(fail=fail)

    instance = object.__new__(GeoreferencedObservationRecomputationService)

    instance.session = session  # type: ignore[assignment]
    instance.persistence = persistence  # type: ignore[assignment]
    instance.georeferencing = georeferencing  # type: ignore[assignment]
    instance.invalidation = FakeInvalidation(  # type: ignore[assignment]
        records
    )

    return (
        instance,
        session,
        persistence,
        georeferencing,
    )


def test_recomputes_stale_explicit_observation_atomically() -> None:
    stale = record(
        stale=True,
        method="explicit",
    )
    fresh = record(stale=False)

    (
        instance,
        session,
        persistence,
        georeferencing,
    ) = service([stale, fresh])

    response = instance.recompute_video(str(uuid4()))

    assert response.invalidated_count == 0
    assert response.stale_count == 1
    assert response.recomputed_count == 1
    assert response.unchanged_count == 1

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.deleted == [stale]

    assert len(persistence.persisted) == 1
    assert persistence.persisted[0][1] == "a" * 64

    assert len(georeferencing.calls) == 1

    call = georeferencing.calls[0]

    assert call["frame_index"] == 12
    assert call["representative_pixel"] == (
        22.0,
        31.0,
    )
    assert call["track_id"] == stale.track_id
    assert call["detection_id"] == stale.detection_id


def test_hash_mismatch_is_invalidated_then_recomputed() -> None:
    mismatched = record(
        stale=False,
        configuration_hash="b" * 64,
        method="bbox_center",
    )

    (
        instance,
        session,
        _persistence,
        georeferencing,
    ) = service([mismatched])

    response = instance.recompute_video(str(uuid4()))

    assert response.invalidated_count == 1
    assert response.stale_count == 1
    assert response.recomputed_count == 1
    assert response.unchanged_count == 0

    assert georeferencing.calls[0]["representative_pixel"] is None

    assert session.deleted == [mismatched]


def test_failure_rolls_back_without_deleting_stale_row() -> None:
    stale = record(stale=True)

    (
        instance,
        session,
        persistence,
        _,
    ) = service(
        [stale],
        fail=True,
    )

    with pytest.raises(
        ValidationError,
        match="synthetic projection failure",
    ):
        instance.recompute_video(str(uuid4()))

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.deleted == []
    assert persistence.persisted == []


def test_video_without_derived_observations_is_noop() -> None:
    (
        instance,
        session,
        _,
        georeferencing,
    ) = service([])

    video_id = str(uuid4())

    response = instance.recompute_video(video_id)

    assert str(response.video_id) == video_id
    assert response.configuration_hash is None
    assert response.stale_count == 0
    assert response.recomputed_count == 0
    assert response.unchanged_count == 0

    assert georeferencing.hash_calls == 0
    assert session.commits == 0
    assert session.rollbacks == 0


def test_unknown_representative_pixel_policy_rolls_back() -> None:
    stale = record(stale=True)
    stale.representative_pixel_method = "legacy_unknown"

    (
        instance,
        session,
        _,
        georeferencing,
    ) = service([stale])

    with pytest.raises(
        ValidationError,
        match="representative-pixel method",
    ):
        instance.recompute_video(str(uuid4()))

    assert georeferencing.calls == []
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.deleted == []
