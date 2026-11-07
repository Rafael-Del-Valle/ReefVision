from __future__ import annotations

import unittest

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.schema import (
    AnatomySchema,
    LandmarkDefinition,
    SkeletonEdge,
)


class AnatomySchemaTests(unittest.TestCase):
    def test_repeated_reefvision_groups_get_distinct_stable_ids(self) -> None:
        groups = [
            {"name": "bell_center", "count": 1, "description": "Bell center"},
            {"name": "tentacle", "count": 2, "group": "appendages"},
        ]

        first = AnatomySchema.from_reefvision_groups(
            name="Jellyfish",
            revision=3,
            groups=groups,
            schema_id="schema-1",
        )
        repeated = AnatomySchema.from_reefvision_groups(
            name="Jellyfish",
            revision=3,
            groups=groups,
            schema_id="schema-1",
        )

        self.assertEqual(first.integrity_hash, repeated.integrity_hash)
        self.assertEqual(first.keypoint_count, 3)
        self.assertEqual(first.expanded_names, ("bell_center", "tentacle", "tentacle"))
        self.assertEqual(first.landmarks[1].occurrence_index, 0)
        self.assertEqual(first.landmarks[2].occurrence_index, 1)
        self.assertNotEqual(first.landmarks[1].landmark_id, first.landmarks[2].landmark_id)
        self.assertEqual(first.landmarks[1].group, "appendages")
        self.assertEqual(first.landmarks[0].description, "Bell center")

    def test_hash_covers_revision_landmarks_visibility_and_skeleton(self) -> None:
        landmarks = (
            LandmarkDefinition(
                landmark_id="head",
                name="head",
                description="Anterior point",
                group="axis",
                occurrence_index=0,
                allowed_visibility=("absent", "occluded", "visible"),
                default_visibility="visible",
            ),
            LandmarkDefinition(
                landmark_id="tail",
                name="tail",
                group="axis",
                occurrence_index=0,
            ),
        )
        base = AnatomySchema(
            schema_id="fish-axis",
            name="Fish axis",
            revision=1,
            landmarks=landmarks,
            skeleton=(SkeletonEdge(source_id="head", target_id="tail"),),
        )
        restored = AnatomySchema.from_dict(base.to_dict())

        self.assertEqual(restored, base)
        self.assertEqual(restored.integrity_hash, base.integrity_hash)
        self.assertEqual(len(base.integrity_hash), 64)

        changed = AnatomySchema(
            schema_id="fish-axis",
            name="Fish axis",
            revision=2,
            landmarks=landmarks,
            skeleton=(SkeletonEdge(source_id="head", target_id="tail"),),
        )
        self.assertNotEqual(changed.integrity_hash, base.integrity_hash)

    def test_invalid_skeleton_and_visibility_fail_closed(self) -> None:
        with self.assertRaisesRegex(ReefPoseValidationError, "unknown landmark"):
            AnatomySchema(
                schema_id="invalid",
                name="Invalid",
                revision=1,
                landmarks=(LandmarkDefinition(landmark_id="head", name="head"),),
                skeleton=(SkeletonEdge(source_id="head", target_id="missing"),),
            )

        with self.assertRaisesRegex(ReefPoseValidationError, "default visibility"):
            LandmarkDefinition(
                landmark_id="head",
                name="head",
                allowed_visibility=("absent",),
                default_visibility="visible",
            )

    def test_duplicate_ids_and_duplicate_occurrences_are_rejected(self) -> None:
        duplicate = LandmarkDefinition(landmark_id="same", name="fin", occurrence_index=0)
        with self.assertRaisesRegex(ReefPoseValidationError, "landmark IDs"):
            AnatomySchema(
                schema_id="invalid",
                name="Invalid",
                revision=1,
                landmarks=(duplicate, duplicate),
            )

        with self.assertRaisesRegex(ReefPoseValidationError, "occurrence"):
            AnatomySchema(
                schema_id="invalid",
                name="Invalid",
                revision=1,
                landmarks=(
                    LandmarkDefinition(landmark_id="left-a", name="fin", occurrence_index=0),
                    LandmarkDefinition(landmark_id="left-b", name="fin", occurrence_index=0),
                ),
            )


if __name__ == "__main__":
    unittest.main()
