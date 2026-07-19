"""Back-project depth samples into calibrated 3D fish trajectories."""

from __future__ import annotations

from collections import defaultdict
from math import dist

from reefvision.schemas.depth import (
    DepthTrack3DAnalytics,
    DepthTrackAnalyticsRequest,
    DepthTrackAnalyticsResponse,
    DepthTrackPoint3D,
)


def analyze_depth_tracks(
    request: DepthTrackAnalyticsRequest,
) -> DepthTrackAnalyticsResponse:
    intrinsics = request.camera_intrinsics
    by_track: dict[str, list] = defaultdict(list)
    for sample in request.samples:
        by_track[sample.track_id].append(sample)

    tracks: list[DepthTrack3DAnalytics] = []
    warnings: list[str] = []
    for track_id, samples in sorted(by_track.items()):
        samples.sort(key=lambda item: item.frame_index)
        unique_frames = {sample.frame_index for sample in samples}
        if len(unique_frames) != len(samples):
            warnings.append(
                f"Track {track_id} contains duplicate frame samples; duplicates were retained."
            )
        points = [
            DepthTrackPoint3D(
                frame_index=sample.frame_index,
                x=(sample.center_x_px - intrinsics.cx_px)
                * sample.depth
                / intrinsics.fx_px,
                y=(sample.center_y_px - intrinsics.cy_px)
                * sample.depth
                / intrinsics.fy_px,
                z=sample.depth,
            )
            for sample in samples
        ]
        distance_3d = 0.0
        maximum_speed = 0.0
        valid_duration = 0.0
        skipped_gap_count = 0
        for first, second in zip(points, points[1:], strict=False):
            frame_gap = second.frame_index - first.frame_index
            if frame_gap <= 0:
                continue
            if request.maximum_frame_gap is not None and frame_gap > request.maximum_frame_gap:
                skipped_gap_count += 1
                continue
            segment = dist((first.x, first.y, first.z), (second.x, second.y, second.z))
            seconds = frame_gap / request.fps
            distance_3d += segment
            valid_duration += seconds
            maximum_speed = max(maximum_speed, segment / seconds)
        first_point, last_point = points[0], points[-1]
        total_duration = (last_point.frame_index - first_point.frame_index) / request.fps
        net_displacement = dist(
            (first_point.x, first_point.y, first_point.z),
            (last_point.x, last_point.y, last_point.z),
        )
        depths = [point.z for point in points]
        tracks.append(
            DepthTrack3DAnalytics(
                track_id=track_id,
                observed_frame_count=len(points),
                first_frame=first_point.frame_index,
                last_frame=last_point.frame_index,
                duration_seconds=total_duration,
                distance_3d=distance_3d,
                net_displacement_3d=net_displacement,
                mean_speed_3d_per_second=(
                    distance_3d / valid_duration if valid_duration > 0 else 0.0
                ),
                maximum_speed_3d_per_second=maximum_speed,
                mean_depth=sum(depths) / len(depths),
                minimum_depth=min(depths),
                maximum_depth=max(depths),
                points=points,
                skipped_gap_count=skipped_gap_count,
            )
        )
    if not tracks:
        warnings.append("No valid tracks were available for 3D analysis")
    return DepthTrackAnalyticsResponse(
        fps=float(request.fps),
        unit=request.unit,
        tracks=tracks,
        warnings=warnings,
    )
