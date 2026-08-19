"""Canonicalize depth-source names across image and video workflow runtimes."""

from __future__ import annotations

from reefvision.jobs import workflow_video_depth_3d_runtime

# New persisted depth maps use noun-first sensor semantics. Keep the historical aliases in
# the underlying set so saved pre-1.0 workflows remain executable while new workflows use
# the canonical names everywhere.
workflow_video_depth_3d_runtime._ALLOWED_DEPTH_SOURCES.update(  # noqa: SLF001
    {"rgbd_metric", "stereo_metric"}
)
