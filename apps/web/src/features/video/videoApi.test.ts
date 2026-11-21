import { describe, expect, it } from "vitest";

import { poseLandmarkSchemaFromMetadata } from "./videoApi";

const canonicalAnatomy = {
  schema_version: "pose-anatomy-0002",
  schema_id: "905cc36e-6110-4862-b65d-67eec6a177f1",
  schema_revision: 3,
  content_hash: "b".repeat(64),
  groups: [{ name: "tentacle", count: 2 }],
  expanded_labels: ["tentacle", "tentacle"],
  keypoint_count: 2,
  allows_repeated_labels: true,
  landmarks: [
    { id: "left", name: "Tentacle", repeat_group: "tentacle", repeat_index: 0 },
    {
      id: "right",
      name: "Tentacle",
      repeat_group: "tentacle",
      repeat_index: 1,
    },
  ],
  edges: [{ from_id: "left", to_id: "right" }],
};

describe("poseLandmarkSchemaFromMetadata", () => {
  it("preserves repeated semantic landmark labels", () => {
    const schema = poseLandmarkSchemaFromMetadata({
      pose_landmark_schema: {
        schema_version: "pose-landmarks-0001",
        groups: [
          { name: "bell_center", count: 1 },
          { name: "tentacle", count: 8 },
        ],
        expanded_labels: [
          "bell_center",
          "tentacle",
          "tentacle",
          "tentacle",
          "tentacle",
          "tentacle",
          "tentacle",
          "tentacle",
          "tentacle",
        ],
        keypoint_count: 9,
        allows_repeated_labels: true,
      },
    });

    expect(schema?.groups).toEqual([
      { name: "bell_center", count: 1 },
      { name: "tentacle", count: 8 },
    ]);
    expect(
      schema?.expanded_labels.filter((label) => label === "tentacle"),
    ).toHaveLength(8);
    expect(schema?.allows_repeated_labels).toBe(true);
  });

  it("reads the exact frozen anatomy binding emitted by native ReefPose", () => {
    expect(
      poseLandmarkSchemaFromMetadata({
        pose_landmark_schema: canonicalAnatomy,
      }),
    ).toEqual(canonicalAnatomy);
  });

  it("does not infer a native binding from partial or unknown metadata", () => {
    for (const overrides of [
      { schema_version: "pose-anatomy-9999" },
      { schema_id: "" },
      { schema_revision: 0 },
      { content_hash: "missing" },
      { landmarks: [] },
    ]) {
      expect(
        poseLandmarkSchemaFromMetadata({
          pose_landmark_schema: { ...canonicalAnatomy, ...overrides },
        }),
      ).toBeNull();
    }
  });
});
