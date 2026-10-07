"""Offline tests for scientific NWB storage using the optional pinned runtime."""

from importlib.metadata import version
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_runtime(request):
    if not request.config.getoption("--pose-interop-integration"):
        pytest.skip("opt in with --pose-interop-integration")
    assert version("sleap-io") == "0.9.2"


@pytest.fixture
def pose_labels(tmp_path: Path):
    import imageio.v3 as iio
    import sleap_io as sio

    source = tmp_path / "synthetic.mp4"
    images = np.zeros((6, 32, 48, 3), dtype=np.uint8)
    images[4, :, :, 0] = 120
    iio.imwrite(source, images, fps=10, codec="libx264", macro_block_size=1)
    video = sio.Video.from_filename(str(source), keep_open=False, grayscale=False)
    skeleton = sio.Skeleton(nodes=["center", "arm__1", "arm__2"], name="polyp")
    track = sio.Track(name="reefvision-track-original")
    instance = sio.PredictedInstance.from_numpy(
        np.array([[15.25, 16.5], [17.75, 18.125], [np.nan, np.nan]]),
        skeleton=skeleton,
        point_scores=np.array([0.9, 0.7, np.nan]),
        score=0.8,
        track=track,
    )
    instance.points["visible"][1] = False
    labels = sio.Labels(
        [sio.LabeledFrame(video, 4, [instance])],
        provenance={
            "reefvision_pose_interoperability": {
                "source_video_sha256": "a" * 64,
                "node_mapping": [
                    {"semantic_label": "center"},
                    {"semantic_label": "arm"},
                    {"semantic_label": "arm"},
                ],
            }
        },
    )
    return labels, source, np.array(video[4])


def test_nwb_external_pose_and_embedded_media_are_valid(pose_labels, tmp_path: Path) -> None:
    import pynwb
    import sleap_io as sio

    from reefvision.storage.pose_nwb import read_nwb, write_nwb

    labels, source, original_image = pose_labels
    output = tmp_path / "pose.nwb"
    write_nwb(sio, labels, output)
    # The public third-party reader must find actual pose series independently.
    external = sio.load_nwb(str(output))
    assert external.skeletons[0].node_names == ["center", "arm__1", "arm__2"]
    np.testing.assert_allclose(
        external[0].instances[0].points["xy"][:2], [[15.25, 16.5], [17.75, 18.125]]
    )
    np.testing.assert_allclose(external[0].instances[0].points["score"][:2], [0.9, 0.7])
    assert pynwb.validate(path=str(output)) == []
    source.unlink()
    with pynwb.NWBHDF5IO(str(output), "r", load_namespaces=True) as io:
        nwb = io.read()
        images = nwb.acquisition["reefvision_labeled_frames"]
        np.testing.assert_array_equal(images.data[0], original_image)
        assert images.timestamps[0] == pytest.approx(0.4)
        module = next(
            value for key, value in nwb.processing.items() if key.startswith("SLEAP_VIDEO")
        )
        assert module["track=reefvision-track-original"]["center"].timestamps[0] == pytest.approx(
            0.4
        )
    restored = read_nwb(sio, output)
    assert restored[0].frame_idx == 4
    instance = restored[0].instances[0]
    assert instance.track.name == "reefvision-track-original"
    assert instance.points["visible"].tolist() == [True, False, False]
    np.testing.assert_allclose(instance.points["xy"][:2], [[15.25, 16.5], [17.75, 18.125]])
    np.testing.assert_allclose(instance.points["score"][:2], [0.9, 0.7])
    assert (
        restored.provenance["reefvision_pose_interoperability"]
        == labels.provenance["reefvision_pose_interoperability"]
    )
    np.testing.assert_array_equal(restored.videos[0][4], original_image)
    assert labels[0].frame_idx == 4  # export must not mutate observations


def test_nwb_changed_pose_cannot_be_overwritten_by_stale_metadata(
    pose_labels, tmp_path: Path
) -> None:
    import h5py
    import sleap_io as sio

    from reefvision.storage.pose_nwb import read_nwb, write_nwb

    labels, _, _ = pose_labels
    output = tmp_path / "changed.nwb"
    write_nwb(sio, labels, output)
    with h5py.File(output, "r+") as handle:
        module = next(key for key in handle["processing"] if key.startswith("SLEAP_VIDEO"))
        handle[f"processing/{module}/track=reefvision-track-original/center/data"][0, 0] = 29
    with pytest.raises(ValueError, match="checksum"):
        read_nwb(sio, output)


def test_nwb_multiple_sparse_frames_tracks_and_unknown_confidence(
    pose_labels, tmp_path: Path
) -> None:
    import pynwb
    import sleap_io as sio

    from reefvision.storage.pose_nwb import read_nwb, write_nwb

    labels, _, _ = pose_labels
    other = sio.PredictedInstance.from_numpy(
        np.array([[5.125, 6.25], [7.5, 8.75], [np.nan, np.nan]]),
        skeleton=labels.skeletons[0],
        point_scores=np.array([np.nan, 0.2, np.nan]),
        score=0.31,
        track=sio.Track(name="second-track"),
    )
    labels.append(sio.LabeledFrame(labels.videos[0], 1, [other]))
    output = tmp_path / "sparse.nwb"
    write_nwb(sio, labels, output)
    assert pynwb.validate(path=str(output)) == []
    restored = read_nwb(sio, output)
    assert [frame.frame_idx for frame in restored] == [1, 4]
    assert restored[0].instances[0].track.name == "second-track"
    assert restored[0].instances[0].score == pytest.approx(0.31)
    assert np.isnan(restored[0].instances[0].points["score"][0])
    # A native reader must retain coordinates even when confidence is unknown.
    external = sio.load_nwb(str(output))
    coordinates = [
        instance.points["xy"][0].tolist() for frame in external for instance in frame.instances
    ]
    assert [5.125, 6.25] in coordinates
    assert [15.25, 16.5] in coordinates
    assert restored.provenance["reefvision_warnings"]


def test_nwb_modified_embedded_media_rejects_metadata(pose_labels, tmp_path: Path) -> None:
    import h5py
    import sleap_io as sio

    from reefvision.storage.pose_nwb import read_nwb, write_nwb

    labels, _, _ = pose_labels
    output = tmp_path / "changed-image.nwb"
    write_nwb(sio, labels, output)
    with h5py.File(output, "r+") as handle:
        handle["acquisition/reefvision_labeled_frames/data"][0, 0, 0, 0] = 255
    with pytest.raises(ValueError, match="checksum"):
        read_nwb(sio, output)


def test_nwb_without_frame_mapping_is_rejected_before_silent_reindexing(
    pose_labels, tmp_path: Path
) -> None:
    import h5py
    import sleap_io as sio

    from reefvision.storage.pose_nwb import read_nwb, write_nwb

    labels, _, _ = pose_labels
    output = tmp_path / "external.nwb"
    write_nwb(sio, labels, output)
    with h5py.File(output, "r+") as handle:
        del handle["scratch/reefvision_pose_interoperability"]
    # It is still readable NWB, but 0.9.2 silently compresses sparse frame indices.
    assert sio.load_nwb(str(output)).labeled_frames
    with pytest.raises(ValueError, match="frame mapping"):
        read_nwb(sio, output)
