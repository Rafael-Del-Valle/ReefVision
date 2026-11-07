from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from reefvision.ml.reefpose.data import (
    PoseRecord,
    ReefPoseDataset,
    _validate_archive,
    group_aware_split,
    load_reefvision_pose_export,
)
from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.schema import AnatomySchema, LandmarkDefinition


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pose_export(
    path: Path,
    *,
    bad_frame_hash: bool = False,
    unsafe: bool = False,
    legacy_keypoints: bool = False,
) -> None:
    image_stream = io.BytesIO()
    Image.new("RGB", (16, 10), color=(80, 120, 160)).save(image_stream, format="PNG")
    image_bytes = image_stream.getvalue()
    groups = [
        {"name": "bell_center", "count": 1},
        {"name": "tentacle", "count": 2},
    ]
    schema_payload: dict[str, object] = {
        "schema_version": "pose-landmarks-0001",
        "groups": groups,
        "expanded_labels": ["bell_center", "tentacle", "tentacle"],
        "keypoint_count": 3,
        "allows_repeated_labels": True,
    }
    schema_hash = _canonical_hash(schema_payload)
    frame_hash = "0" * 64 if bad_frame_hash else hashlib.sha256(image_bytes).hexdigest()
    manifest = {
        "schema_version": "pose-training-external-export-0001",
        "format": "ultralytics_pose",
        "truth_policy": "scientist_verified_only",
        "dataset": {
            "dataset_id": "dataset-1",
            "dataset_manifest_sha256": "d" * 64,
            "item_count": 1,
        },
        "source_video": {
            "video_id": "video-1",
            "width_px": 16,
            "height_px": 10,
        },
        "pose_schema": {
            **schema_payload,
            "schema_id": "schema-1",
            "schema_revision": 2,
            "content_hash": schema_hash,
        },
        "frame_extraction": {
            "frames": [
                {
                    "source_frame_index": 4,
                    "path": "images/train/frame_00000004.png",
                    "sha256": frame_hash,
                    "width_px": 16,
                    "height_px": 10,
                }
            ]
        },
        "annotations": [
            {
                "item_id": "item-1",
                "source_frame_index": 4,
                "video_track_id": "track-1",
                "canonical_pose": {
                    "bbox": [2.0, 1.0, 10.0, 8.0],
                    "pose_observations": []
                    if legacy_keypoints
                    else [
                        {
                            "semantic_label": "bell_center",
                            "occurrence_index": 0,
                            "x": 8.0,
                            "y": 5.0,
                            "status": "visible",
                        },
                        {
                            "semantic_label": "tentacle",
                            "occurrence_index": 0,
                            "x": 4.0,
                            "y": 8.0,
                            "status": "occluded",
                        },
                        {
                            "semantic_label": "tentacle",
                            "occurrence_index": 1,
                            "x": 0.0,
                            "y": 0.0,
                            "status": "absent",
                        },
                    ],
                    "keypoints": (
                        [[8.0, 5.0, 1.0], [4.0, 8.0, 0.5], [0.0, 0.0, 0.0]]
                        if legacy_keypoints
                        else []
                    ),
                },
            }
        ],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "reefvision-pose-training-export-manifest.json",
            json.dumps(manifest),
        )
        archive.writestr("images/train/frame_00000004.png", image_bytes)
        if unsafe:
            archive.writestr("../escape.txt", "unsafe")


def _record(sample_id: str, group_id: str) -> PoseRecord:
    return PoseRecord(
        sample_id=sample_id,
        image_path=Path(f"{sample_id}.png"),
        group_id=group_id,
        source_width=16,
        source_height=10,
        keypoints=((1.0, 1.0),),
        visibility=(2,),
        visibility_states=("visible",),
    )


def _single_landmark_schema() -> AnatomySchema:
    return AnatomySchema(
        schema_id="schema-edge",
        name="Edge anatomy",
        revision=1,
        landmarks=(LandmarkDefinition(landmark_id="point", name="point"),),
    )


class ReefVisionPoseExportTests(unittest.TestCase):
    def test_verified_export_preserves_repeated_landmarks_and_builds_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "dataset.zip"
            destination = root / "extracted"
            _pose_export(archive)

            bundle = load_reefvision_pose_export(archive, destination)
            record = bundle.records[0]
            sample = ReefPoseDataset(
                bundle.records,
                bundle.schema,
                input_height=64,
                input_width=64,
                heatmap_sigma=1.5,
            )[0]

            self.assertEqual(
                bundle.schema.expanded_names,
                (
                    "bell_center",
                    "tentacle",
                    "tentacle",
                ),
            )
            self.assertEqual(record.group_id, "video-1")
            self.assertEqual(record.keypoints[0], (8.0, 5.0))
            self.assertEqual(record.visibility, (2, 1, 0))
            self.assertEqual(record.crop_box, (2.0, 1.0, 12.0, 9.0))
            self.assertEqual(tuple(sample["image"].shape), (3, 64, 64))
            self.assertEqual(tuple(sample["heatmaps"].shape), (3, 16, 16))
            self.assertEqual(sample["sample_id"], "item-1")
            self.assertEqual(sample["source_keypoints"].tolist()[0], [8.0, 5.0])

    def test_frame_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "dataset.zip"
            _pose_export(archive, bad_frame_hash=True)

            with self.assertRaisesRegex(ReefPoseValidationError, "checksum"):
                load_reefvision_pose_export(archive, root / "extracted")

    def test_archive_path_traversal_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "dataset.zip"
            _pose_export(archive, unsafe=True)

            with self.assertRaisesRegex(ReefPoseValidationError, "unsafe"):
                load_reefvision_pose_export(archive, root / "extracted")
            self.assertFalse((root / "escape.txt").exists())

    def test_windows_drive_archive_path_is_rejected_without_extraction(self) -> None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("reefvision-pose-training-export-manifest.json", "{}")
            archive.writestr("D:/outside.txt", "unsafe")
        stream.seek(0)

        with (
            zipfile.ZipFile(stream) as archive,
            self.assertRaisesRegex(ReefPoseValidationError, "unsafe"),
        ):
            _validate_archive(archive, 1024)

    def test_legacy_schema_ordered_keypoints_preserve_positive_supervision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "dataset.zip"
            _pose_export(archive, legacy_keypoints=True)

            record = load_reefvision_pose_export(archive, root / "extracted").records[0]

            self.assertEqual(record.keypoints, ((8.0, 5.0), (4.0, 8.0), (0.0, 0.0)))
            self.assertEqual(record.visibility, (2, 2, 0))
            self.assertEqual(record.visibility_states, ("visible", "visible", "absent"))

    def test_crop_right_bottom_boundary_generates_a_valid_heatmap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image_path = root / "frame.png"
            Image.new("RGB", (16, 10), color=(80, 120, 160)).save(image_path)
            record = PoseRecord(
                sample_id="edge",
                image_path=image_path,
                group_id="video-1",
                source_width=16,
                source_height=10,
                keypoints=((12.0, 9.0),),
                visibility=(2,),
                visibility_states=("visible",),
                crop_box=(2.0, 1.0, 12.0, 9.0),
            )

            sample = ReefPoseDataset(
                (record,),
                _single_landmark_schema(),
                input_height=64,
                input_width=64,
                heatmap_sigma=1.5,
            )[0]

            self.assertGreater(float(sample["heatmaps"].max()), 0.9)

    def test_supervised_landmark_outside_crop_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image_path = root / "frame.png"
            Image.new("RGB", (16, 10), color=(80, 120, 160)).save(image_path)
            record = PoseRecord(
                sample_id="outside",
                image_path=image_path,
                group_id="video-1",
                source_width=16,
                source_height=10,
                keypoints=((13.0, 9.0),),
                visibility=(2,),
                visibility_states=("visible",),
                crop_box=(2.0, 1.0, 12.0, 9.0),
            )

            with self.assertRaisesRegex(ReefPoseValidationError, "outside.*crop"):
                ReefPoseDataset(
                    (record,),
                    _single_landmark_schema(),
                    input_height=64,
                    input_width=64,
                    heatmap_sigma=1.5,
                )[0]


class GroupAwareSplitTests(unittest.TestCase):
    def test_related_groups_never_cross_partitions(self) -> None:
        records = (
            _record("a1", "a"),
            _record("a2", "a"),
            _record("b1", "b"),
            _record("c1", "c"),
        )

        train, validation = group_aware_split(records, validation_fraction=0.34, seed=17)

        train_groups = {record.group_id for record in train}
        validation_groups = {record.group_id for record in validation}
        self.assertFalse(train_groups & validation_groups)
        self.assertEqual(
            {record.sample_id for record in (*train, *validation)}, {"a1", "a2", "b1", "c1"}
        )

    def test_one_group_cannot_be_silently_split(self) -> None:
        with self.assertRaisesRegex(ReefPoseValidationError, "two groups"):
            group_aware_split(
                (_record("a1", "a"), _record("a2", "a")),
                validation_fraction=0.2,
                seed=1,
            )


if __name__ == "__main__":
    unittest.main()
