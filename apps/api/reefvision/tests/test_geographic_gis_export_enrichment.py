"""Task 18E authoritative GIS metadata enrichment tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from reefvision.services.geographic_gis_export_enrichment import (
    build_geographic_export_enrichments,
)


class FakeSession:
    def __init__(
        self,
        *,
        track: object | None,
        label_class: object | None,
    ) -> None:
        self.track = track
        self.label_class = label_class

    def get(
        self,
        model: type[object],
        _identifier: str,
    ) -> object | None:
        if model.__name__ == "VideoTrack":
            return self.track

        if model.__name__ == "LabelClass":
            return self.label_class

        return None


def observation(
    frame_index: int,
    track_id: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid4()),
        track_id=track_id,
        frame_index=frame_index,
    )


def test_exact_keyframe_exports_authoritative_class_and_confidence() -> None:
    track_id = str(uuid4())
    class_id = str(uuid4())
    item = observation(10, track_id)

    track = SimpleNamespace(
        label_class_id=class_id,
        keyframes_json=[
            {
                "frame": 10,
                "bbox": [1, 1, 10, 10],
                "confidence": 0.91,
            }
        ],
    )

    result = build_geographic_export_enrichments(
        FakeSession(
            track=track,
            label_class=SimpleNamespace(name="Fish"),
        ),
        [item],
    )[str(item.id)]

    assert result.label_class_id == class_id
    assert result.class_name == "Fish"
    assert result.confidence == 0.91
    assert result.confidence_status == "exact_keyframe"


def test_interpolated_frame_does_not_inherit_confidence() -> None:
    track_id = str(uuid4())
    item = observation(15, track_id)

    track = SimpleNamespace(
        label_class_id=str(uuid4()),
        keyframes_json=[
            {"frame": 10, "confidence": 0.9},
            {"frame": 20, "confidence": 0.8},
        ],
        metadata_json={"mean_confidence": 0.85},
    )

    result = build_geographic_export_enrichments(
        FakeSession(
            track=track,
            label_class=SimpleNamespace(name="Fish"),
        ),
        [item],
    )[str(item.id)]

    assert result.class_name == "Fish"
    assert result.confidence is None
    assert result.confidence_status == "not_persisted_for_frame"


def test_exact_keyframe_without_confidence_remains_missing() -> None:
    track_id = str(uuid4())
    item = observation(10, track_id)

    track = SimpleNamespace(
        label_class_id=str(uuid4()),
        keyframes_json=[
            {
                "frame": 10,
                "confidence": None,
            }
        ],
    )

    result = build_geographic_export_enrichments(
        FakeSession(
            track=track,
            label_class=SimpleNamespace(name="Fish"),
        ),
        [item],
    )[str(item.id)]

    assert result.confidence is None
    assert result.confidence_status == ("exact_keyframe_without_confidence")


def test_duplicate_keyframes_do_not_produce_ambiguous_confidence() -> None:
    track_id = str(uuid4())
    item = observation(10, track_id)

    track = SimpleNamespace(
        label_class_id=str(uuid4()),
        keyframes_json=[
            {"frame": 10, "confidence": 0.9},
            {"frame": 10, "confidence": 0.8},
        ],
    )

    result = build_geographic_export_enrichments(
        FakeSession(
            track=track,
            label_class=SimpleNamespace(name="Fish"),
        ),
        [item],
    )[str(item.id)]

    assert result.confidence is None
    assert result.confidence_status == ("ambiguous_duplicate_keyframe")


def test_missing_track_does_not_invent_metadata() -> None:
    item = observation(10, str(uuid4()))

    result = build_geographic_export_enrichments(
        FakeSession(track=None, label_class=None),
        [item],
    )[str(item.id)]

    assert result.label_class_id is None
    assert result.class_name is None
    assert result.confidence is None
    assert result.confidence_status == "track_not_found"


def test_missing_label_class_preserves_id_but_not_name() -> None:
    class_id = str(uuid4())
    item = observation(10, str(uuid4()))

    track = SimpleNamespace(
        label_class_id=class_id,
        keyframes_json=[
            {
                "frame": 10,
                "confidence": 0.72,
            }
        ],
    )

    result = build_geographic_export_enrichments(
        FakeSession(track=track, label_class=None),
        [item],
    )[str(item.id)]

    assert result.label_class_id == class_id
    assert result.class_name is None
    assert result.confidence == 0.72
    assert result.confidence_status == "exact_keyframe"


def test_untracked_observation_is_explicit() -> None:
    item = observation(10, None)

    result = build_geographic_export_enrichments(
        FakeSession(track=None, label_class=None),
        [item],
    )[str(item.id)]

    assert result.label_class_id is None
    assert result.class_name is None
    assert result.confidence is None
    assert result.confidence_status == "untracked_observation"
