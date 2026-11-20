"""Offline validation of native pose text exchange and independent parsers."""

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from reefvision.domain.errors import ValidationError
from reefvision.storage import pose_text_records as records


@pytest.fixture
def require_ultralytics(request, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    if not request.config.getoption("--pose-interop-integration"):
        pytest.skip("opt in with --pose-interop-integration")
    config_dir = tmp_path / "ultralytics-config"
    config_dir.mkdir()
    monkeypatch.setenv("YOLO_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("YOLO_AUTOINSTALL", "false")
    monkeypatch.setenv("YOLO_OFFLINE", "true")
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib-config"))


@pytest.fixture
def pose(tmp_path: Path):
    import cv2

    path = tmp_path / "source.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (60, 40))
    assert writer.isOpened()
    try:
        for idx in range(5):
            writer.write(np.full((40, 60, 3), idx * 30, dtype=np.uint8))
    finally:
        writer.release()
    video = records.Video(str(path), (5, 40, 60, 3))
    skeleton = records.Skeleton(["center", "arm__1", "arm__2"])
    inst = records.Instance.from_arrays(
        np.array([[15, 16], [17, 18], [np.nan, np.nan]]),
        skeleton=skeleton,
        visible=np.array([True, False, False]),
        scores=np.array([0.9, 0.8, 0.0]),
        score=0.9,
        track=records.Track("animal-1"),
        category=records.Category("coral"),
    )
    return records.Labels(
        [records.LabeledFrame(video, 4, [inst])],
        [video],
        [skeleton],
        provenance={
            "reefvision_pose_interoperability": {
                "source_video_sha256": "a" * 64,
                "node_mapping": [{"external_node_name": n} for n in skeleton.node_names],
                "pose_schema": {"expanded_labels": ["center", "arm", "arm"]},
            }
        },
    )


@pytest.mark.parametrize("fmt", ["coco", "dlc_csv", "ultralytics_pose"])
def test_text_roundtrip_preserves_occlusion_and_frame(pose, tmp_path: Path, fmt) -> None:
    from reefvision.storage.pose_exchange_text import read_text, write_text

    path, _ = write_text(pose, tmp_path, fmt)
    restored = read_text(path, fmt)
    assert restored.labeled_frames[0].frame_idx == 4
    instance = restored.labeled_frames[0].instances[0]
    np.testing.assert_allclose(instance.points["xy"][:2], [[15, 16], [17, 18]])
    assert not instance.points["visible"][1]
    assert instance.track.name == "animal-1"
    assert (
        restored.provenance["reefvision_pose_interoperability"]["pose_schema"]
        == (pose.provenance["reefvision_pose_interoperability"]["pose_schema"])
    )


def test_yolo_assets_are_original_decoded_pixels(pose, tmp_path: Path) -> None:
    from io import BytesIO

    import yaml
    from PIL import Image

    from reefvision.storage.pose_exchange_text import write_text

    path, _ = write_text(pose, tmp_path, "ultralytics_pose")
    with zipfile.ZipFile(path) as archive:
        config = yaml.safe_load(archive.read("data.yaml"))
        assert config["kpt_shape"] == [3, 3]
        assert config["names"] == {0: "coral"}
        image_name = next(n for n in archive.namelist() if n.endswith(".png"))
        pixels = np.array(Image.open(BytesIO(archive.read(image_name))))
        np.testing.assert_array_equal(pixels, pose.videos[0][4])
        label_name = image_name.replace("images/", "labels/").replace(".png", ".txt")
        values = [float(v) for v in archive.read(label_name).decode().split()]
        np.testing.assert_allclose(values[8:11], [17 / 60, 18 / 40, 1])


def test_coco_external_edits_cannot_be_overridden_by_sidecar(pose, tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import read_text, write_text

    path, _ = write_text(pose, tmp_path, "coco")
    content = json.loads(path.read_text())
    content["annotations"][0]["keypoints"][0] = 22
    path.write_text(json.dumps(content))
    with pytest.raises(ValidationError, match=r"digest|modified"):
        read_text(path, "coco")


def test_historical_coco_track_survives_without_a_reefvision_manifest(pose, tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import read_text, write_text

    path, _ = write_text(pose, tmp_path, "coco")
    content = json.loads(path.read_bytes())
    content.pop("reefvision")
    image, annotation = content["images"][0], content["annotations"][0]
    assert annotation["attributes"] == {"object_id": 1}
    annotation["attributes"] = {"object_id": 7}
    content["images"].append(
        image | {"id": 100, "file_name": "references/next.png", "reefvision_source_frame": 5}
    )
    content["annotations"].append(annotation | {"id": 100, "image_id": 100})
    path.write_text(json.dumps(content), encoding="utf-8")

    labels = read_text(path, "coco")
    first, second = [frame.instances[0] for frame in labels.labeled_frames]
    assert first.track == records.Track("track_7")
    assert first.track is second.track
    assert first.points.dtype.names == ("xy", "visible")


@pytest.mark.parametrize("fmt", ["dlc_csv", "ultralytics_pose"])
def test_corrupt_archive_is_domain_error(tmp_path: Path, fmt) -> None:
    from reefvision.storage.pose_exchange_text import read_text

    path = tmp_path / "broken.zip"
    path.write_bytes(b"not a zip")
    with pytest.raises(ValidationError, match=r"archive|ZIP"):
        read_text(path, fmt)


@pytest.mark.integration
@pytest.mark.usefixtures("require_ultralytics")
def test_ultralytics_real_parser_accepts_package(pose, tmp_path: Path) -> None:
    from ultralytics.data.utils import verify_image_label

    from reefvision.storage.pose_exchange_text import write_text

    path, _ = write_text(pose, tmp_path, "ultralytics_pose")
    # The archive here was generated by this test, and has no external members.
    with zipfile.ZipFile(path) as archive:
        archive.extractall(tmp_path / "unpacked")
    image = next((tmp_path / "unpacked" / "images").rglob("*.png"))
    label = tmp_path / "unpacked" / "labels" / "train" / (image.stem + ".txt")
    result = verify_image_label((str(image), str(label), "", True, 1, 3, 3, False))
    assert result[8] == 0, result[9]
    assert result[6] == 1
    np.testing.assert_allclose(result[4][0, 1], [17 / 60, 18 / 40, 1])


@pytest.mark.integration
@pytest.mark.usefixtures("require_ultralytics")
def test_ultralytics_dataset_resolves_from_another_directory(
    pose, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    from ultralytics.data import utils

    from reefvision.storage.pose_exchange_text import write_text

    path, _ = write_text(pose, tmp_path, "ultralytics_pose")
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(path) as archive:
        archive.extractall(extracted)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    # Dataset resolution and validation are real; only optional font download is disabled.
    monkeypatch.setattr(utils, "check_font", lambda *_args, **_kwargs: None)
    dataset = utils.check_det_dataset(str(extracted / "data.yaml"), autodownload=False)
    assert Path(dataset["train"]) == extracted / "images" / "train"
    assert Path(dataset["val"]) == extracted / "images" / "train"
    assert dataset["names"] == {0: "coral"}
    assert dataset["kpt_shape"] == [3, 3]


@pytest.mark.parametrize("failure", ["dimensions", "duplicate_nodes", "bounds", "frame"])
def test_external_coco_validation(pose, tmp_path: Path, failure) -> None:
    from reefvision.storage.pose_exchange_text import read_text, write_text

    path, _ = write_text(pose, tmp_path, "coco")
    content = json.loads(path.read_bytes())
    content.pop("reefvision")
    if failure == "dimensions":
        content["images"][0].pop("width")
    elif failure == "duplicate_nodes":
        content["categories"][0]["keypoints"] = ["a", "a", "b"]
    elif failure == "bounds":
        content["annotations"][0]["keypoints"][0] = 10000
    else:
        content["images"][0]["reefvision_source_frame"] = -1
    path.write_text(json.dumps(content))
    with pytest.raises(ValidationError):
        read_text(path, "coco")


@pytest.mark.parametrize("fmt", ["coco", "dlc_csv"])
def test_missing_image_references_are_explicit(pose, tmp_path: Path, fmt) -> None:
    from reefvision.storage.pose_exchange_text import read_text, write_text

    path, _ = write_text(pose, tmp_path, fmt)
    restored = read_text(path, fmt)
    assert any("unavailable" in warning for warning in restored.provenance["reefvision_warnings"])
    exchange = restored.provenance["reefvision_text_exchange"]
    assert exchange["source_video_sha256"] == "a" * 64
    assert exchange["frame_mapping"][0]["frame_idx"] == 4


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import read_text

    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../escape.png", b"bad")
    with pytest.raises(ValidationError, match="unsafe"):
        read_text(path, "ultralytics_pose")


def test_yolo_missing_image_is_rejected(pose, tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import read_text, write_text

    path, _ = write_text(pose, tmp_path, "ultralytics_pose")
    with zipfile.ZipFile(path) as archive:
        payloads = {n: archive.read(n) for n in archive.namelist() if not n.endswith(".png")}
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    with pytest.raises(ValidationError, match="correspondence"):
        read_text(path, "ultralytics_pose")


@pytest.mark.parametrize("fmt", ["dlc_csv", "ultralytics_pose"])
def test_modified_external_coordinates_reject_stale_sidecar(pose, tmp_path: Path, fmt) -> None:
    from reefvision.storage.pose_exchange_text import read_text, write_text

    path, _ = write_text(pose, tmp_path, fmt)
    with zipfile.ZipFile(path) as archive:
        payloads = {n: archive.read(n) for n in archive.namelist()}
    coordinate_file = next(n for n in payloads if n.endswith((".csv", ".txt")))
    payloads[coordinate_file] += b"\n"
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    with pytest.raises(ValidationError, match="digest"):
        read_text(path, fmt)


def test_duplicate_track_in_frame_is_rejected(pose, tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import write_text

    pose.labeled_frames[0].instances.append(pose.labeled_frames[0].instances[0])
    with pytest.raises(ValidationError, match="share one track"):
        write_text(pose, tmp_path, "dlc_csv")


def test_yolo_requires_source_digest(pose, tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import write_text

    pose.provenance["reefvision_pose_interoperability"].pop("source_video_sha256")
    with pytest.raises(ValidationError, match="source video SHA"):
        write_text(pose, tmp_path, "ultralytics_pose")


def test_raw_dlc_csv_requires_metadata_with_actionable_error(tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import read_text

    path = tmp_path / "CollectedData.csv"
    path.write_text("scorer,ReefVision\nbodyparts,center\ncoords,x\nframe,12\n")
    with pytest.raises(ValidationError, match="DLC ZIP containing the CSV"):
        read_text(path, "dlc_csv")


@pytest.mark.parametrize(
    ("index_header", "index_value"),
    [("", r"labeled-data\video\frame.png"), (",,", "labeled-data,video,frame.png")],
)
def test_historical_dlc_accepts_windows_paths_and_split_paths(
    tmp_path: Path, index_header: str, index_value: str
) -> None:
    from reefvision.storage.pose_exchange_text import read_legacy_dlc

    path = tmp_path / "CollectedData.csv"
    path.write_text(
        f"scorer{index_header},DLC,DLC,DLC\n"
        f"bodyparts{index_header},tip,tip,tip\n"
        f"coords{index_header},x,y,likelihood\n"
        f"{index_value},12,16,0.75\n",
        encoding="utf-8",
    )

    labels = read_legacy_dlc(path, 60, 40)
    instance = labels.labeled_frames[0].instances[0]
    assert labels.provenance["reefvision_text_exchange"]["frame_mapping"][0]["reference"] == (
        "labeled-data/video/frame.png"
    )
    np.testing.assert_allclose(instance.points["xy"], [[12, 16]])
    np.testing.assert_allclose(instance.points["score"], [0.75])


def test_source_pixel_upper_bound_is_excluded(pose, tmp_path: Path) -> None:
    from reefvision.storage.pose_exchange_text import write_text

    pose.labeled_frames[0].instances[0].points["xy"][0] = [60, 40]
    with pytest.raises(ValidationError, match="outside image bounds"):
        write_text(pose, tmp_path, "coco")
