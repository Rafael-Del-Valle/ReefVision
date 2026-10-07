"""Explicit read-only validation against an optional external research dataset."""

import pytest

from reefvision.services.video_assets import _inspect_video
from reefvision.storage.telemetry import load_dji_srt
from reefvision.tests.whaledrone import find_whaledrone_srt, get_whaledrone_root


@pytest.mark.integration
def test_external_whaledrone_pair(request) -> None:
    if not request.config.getoption("--whaledrone-integration"):
        pytest.skip("Explicit --whaledrone-integration opt-in required")
    root = get_whaledrone_root()
    if root is None:
        pytest.skip("REEFVISION_WHALEDRONE_ROOT is unset, unavailable, or inside the repository")
    for video in root.rglob("*"):
        if not video.is_file() or video.suffix.casefold() != ".mp4":
            continue
        sidecar = find_whaledrone_srt(root, video)
        if sidecar is None:
            continue
        source = load_dji_srt(sidecar)
        assert any(
            sample.latitude is not None and sample.longitude is not None
            for sample in source.samples
        )
        metadata = _inspect_video(video)
        match = source.sample_for_frame(0, float(metadata["fps"]))
        assert match is not None and match.error_s >= 0
        return
    pytest.skip("No matching external MP4/SRT pair found")
