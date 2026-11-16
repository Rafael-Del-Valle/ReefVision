"""Regression tests for dual-model video tracking reconciliation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reefvision.ml.video_tracking import TrackObservation
from reefvision.ml.video_tracking_fusion import box_iou, fuse_tracked_models
from reefvision.schemas.videos import VideoTrackingCreateRequest, VideoTrackKeyframe


def observation(
    frame: int,
    identity: int,
    *,
    kind: str = "fish",
    x: float = 10.0,
    mask: bool = False,
) -> TrackObservation:
    return TrackObservation(
        frame=frame,
        provider_track_id=identity,
        class_name=kind,
        confidence=0.9,
        bbox=(x, 10.0, 20.0, 10.0),
        mask_polygons=((((x, 10.0), (x + 20.0, 10.0), (x + 10.0, 20.0)),) if mask else None),
    )


def test_hybrid_retains_detector_ids_and_segmentation_polygons() -> None:
    detections = [observation(0, 7), observation(1, 7, x=20)]
    segmentations = [
        observation(0, 99, x=11, mask=True),
        observation(1, 99, x=21, mask=True),
    ]
    tracks, report = fuse_tracked_models(
        detections,
        segmentations,
        detector_class_map={"fish": "class-a"},
        segmenter_class_map={"fish": "class-a"},
        minimum_iou=0.5,
    )
    assert [(t.frame, t.provider_track_id) for t in tracks] == [(0, 7), (1, 7)]
    assert all(t.mask_polygons is not None for t in tracks)
    assert report.matched_track_pairs == 1
    assert report.masked_observations == 2
    assert report.detector_observations == 2


def test_hybrid_unmatched_segmenter_identity_is_disjoint_and_class_mapped() -> None:
    tracks, report = fuse_tracked_models(
        [observation(0, 1), observation(1, 1)],
        [observation(0, 1, kind="shrimp", x=60, mask=True)],
        detector_class_map={"fish": "class-fish"},
        segmenter_class_map={"shrimp": "class-shrimp"},
    )
    assert len(tracks) == 3
    shrimp = next(item for item in tracks if item.class_name == "project:class-shrimp")
    assert shrimp.provider_track_id != 1
    assert shrimp.mask_polygons
    assert report.matched_track_pairs == 0


def test_fusion_uses_track_identity_to_fill_detector_gaps() -> None:
    tracks, report = fuse_tracked_models(
        [observation(0, 4), observation(2, 4, x=30)],
        [observation(0, 8, mask=True), observation(1, 8, x=20, mask=True)],
        detector_class_map={"fish": "same-class"},
        segmenter_class_map={"fish": "same-class"},
    )
    assert [(item.frame, item.provider_track_id) for item in tracks] == [
        (0, 4),
        (1, 4),
        (2, 4),
    ]
    assert tracks[1].class_name == "project:same-class"
    assert report.matched_track_pairs == 1


def test_fusion_does_not_overwrite_disagreeing_same_frame_geometry() -> None:
    tracks, _ = fuse_tracked_models(
        [observation(0, 4, x=10), observation(1, 4, x=10)],
        [observation(0, 8, x=11, mask=True), observation(1, 8, x=70, mask=True)],
        detector_class_map={"fish": "same-class"},
        segmenter_class_map={"fish": "same-class"},
        minimum_iou=0.5,
    )
    assert tracks[0].mask_polygons is not None
    assert tracks[1].mask_polygons is None
    assert len(tracks) == 2


def test_fusion_does_not_match_different_project_classes() -> None:
    tracks, report = fuse_tracked_models(
        [observation(0, 5)],
        [observation(0, 6, mask=True)],
        detector_class_map={"fish": "class-a"},
        segmenter_class_map={"fish": "class-b"},
    )
    assert len(tracks) == 2
    assert report.matched_track_pairs == 0


def test_fusion_leaves_exact_crossing_ambiguity_unmatched() -> None:
    tracks, report = fuse_tracked_models(
        [observation(5, 10), observation(5, 20)],
        [observation(5, 101, mask=True), observation(5, 202, mask=True)],
        detector_class_map={"fish": "same-class"},
        segmenter_class_map={"fish": "same-class"},
    )

    assert report.matched_track_pairs == 0
    assert len(tracks) == 4
    detector_tracks = [item for item in tracks if item.provider_track_id in {10, 20}]
    assert all(item.mask_polygons is None for item in detector_tracks)
    assert len({item.provider_track_id for item in tracks}) == 4


def test_reject_invalid_tracking_modes_and_secondary_pairings() -> None:
    with pytest.raises(ValidationError, match="segmentation model"):
        VideoTrackingCreateRequest(model_id="det", tracking_mode="hybrid")
    with pytest.raises(ValidationError, match="different models"):
        VideoTrackingCreateRequest(
            model_id="same", segmentation_model_id="same", tracking_mode="hybrid"
        )
    with pytest.raises(ValidationError, match="linking"):
        VideoTrackingCreateRequest(
            model_id="det",
            segmentation_model_id="seg",
            tracking_mode="hybrid",
            link_detections=False,
        )
    with pytest.raises(ValidationError, match="only valid in hybrid"):
        VideoTrackingCreateRequest(model_id="det", segmentation_model_id="seg")
    request = VideoTrackingCreateRequest(
        model_id="det",
        segmentation_model_id="seg",
        tracking_mode="hybrid",
        hybrid_match_iou=0.75,
    )
    assert request.hybrid_match_iou == pytest.approx(0.75)


def test_validate_retained_polygons_and_finite_coordinates() -> None:
    frame = VideoTrackKeyframe(
        frame=4,
        bbox=(10, 10, 20, 20),
        mask_polygons=[[(10, 10), (25, 10), (20, 20)]],
    )
    assert frame.mask_polygons is not None
    with pytest.raises(ValidationError):
        VideoTrackKeyframe(
            frame=4,
            bbox=(10, 10, 20, 20),
            mask_polygons=[[(10, 10), (20, 20)]],
        )
    with pytest.raises(ValidationError):
        VideoTrackKeyframe(
            frame=4,
            bbox=(10, 10, 20, 20),
            mask_polygons=[[(10, 10), (float("nan"), 20), (20, 20)]],
        )


def test_box_overlap_has_no_negative_area() -> None:
    assert box_iou((0, 0, 5, 5), (10, 10, 5, 5)) == 0
    assert box_iou((0, 0, 5, 5), (0, 0, 5, 5)) == 1
