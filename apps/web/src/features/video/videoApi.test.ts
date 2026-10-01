import { describe, expect, it } from "vitest";

import { poseLandmarkSchemaFromMetadata } from "./videoApi";

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
});
