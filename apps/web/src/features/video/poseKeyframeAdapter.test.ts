import { describe, expect, it } from "vitest";

import type { PoseSaveRequest } from "../pose/types";
import type {
  PoseLandmarkSchema,
  VideoTrackKeyframe,
  VideoTrackRecord,
} from "./videoApi";
import {
  correctedVideoKeyframeFromPoseSave,
  editorSchemaForVideoTrack,
  poseInstanceFromVideoKeyframe,
} from "./poseKeyframeAdapter";

const schema: PoseLandmarkSchema = {
  schema_version: "pose-landmarks-0001",
  groups: [
    { name: "bell_center", count: 1 },
    { name: "tentacle", count: 2 },
  ],
  expanded_labels: ["bell_center", "tentacle", "tentacle"],
  keypoint_count: 3,
  allows_repeated_labels: true,
};

const track: VideoTrackRecord = {
  id: "track-1",
  video_id: "video-1",
  label_class_id: "class-1",
  track_number: 1,
  geometry_kind: "bbox",
  keyframes_json: [],
  interpolation: "linear",
  status: "verified",
  source_model_id: "model-1",
  source_job_id: "job-1",
  metadata_json: { pose_landmark_schema: schema },
  revision: 4,
};

const keyframe: VideoTrackKeyframe = {
  frame: 12,
  bbox: [10, 20, 100, 120],
  confidence: 0.9,
  keypoints: [
    [50, 60, 0.95],
    [70, 80, 0.72],
    [0, 0, 0],
  ],
};

describe("poseKeyframeAdapter", () => {
  it("uses canonical pose schema identity when metadata provides it", () => {
    const canonicalSchema: PoseLandmarkSchema = {
      ...schema,
      schema_id: "schema-canonical-1",
      schema_revision: 4,
      content_hash: "a".repeat(64),
    };

    expect(editorSchemaForVideoTrack(track, canonicalSchema)).toMatchObject({
      id: "schema-canonical-1",
      revision: 4,
    });
  });

  it("converts model keypoints into editable semantic observations", () => {
    const pose = poseInstanceFromVideoKeyframe(track, keyframe, schema);

    expect(pose.observations).toEqual([
      {
        id: "track-1:12:0",
        semantic_label: "bell_center",
        occurrence_index: 0,
        x: 50,
        y: 60,
        confidence: 0.95,
        status: "visible",
        source: "model",
      },
      {
        id: "track-1:12:1",
        semantic_label: "tentacle",
        occurrence_index: 0,
        x: 70,
        y: 80,
        confidence: 0.72,
        status: "visible",
        source: "model",
      },
    ]);
    expect(pose.schema_id).toBe(editorSchemaForVideoTrack(track, schema).id);
  });

  it("prefers persisted corrected observations on subsequent review", () => {
    const corrected: VideoTrackKeyframe = {
      ...keyframe,
      pose_observations: [
        {
          id: "track-1:12:1",
          semantic_label: "tentacle",
          occurrence_index: 0,
          x: 75,
          y: 86,
          confidence: 0.72,
          status: "occluded",
          source: "corrected",
        },
      ],
    };

    const pose = poseInstanceFromVideoKeyframe(track, corrected, schema);

    expect(pose.observations).toHaveLength(1);
    expect(pose.observations[0]).toMatchObject({
      x: 75,
      y: 86,
      status: "occluded",
      source: "corrected",
    });
  });

  it("keeps out-of-frame observations in rich persistence but zeroes compatibility keypoints", () => {
    const editorSchema = editorSchemaForVideoTrack(track, schema);
    const request: PoseSaveRequest = {
      pose_id: "track-1:frame:12",
      base_revision: 4,
      schema_id: editorSchema.id,
      schema_revision: editorSchema.revision,
      observations: [
        {
          id: "track-1:12:2",
          semantic_label: "tentacle",
          occurrence_index: 1,
          x: 0,
          y: 0,
          confidence: 0.6,
          status: "out_of_frame",
          source: "corrected",
        },
      ],
    };

    const updated = correctedVideoKeyframeFromPoseSave(
      keyframe,
      schema,
      request,
    );

    expect(updated.keypoints).toEqual([
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ]);
    expect(updated.pose_observations).toEqual(request.observations);
  });

  it("writes edited observations back to compatible keypoints and rich persistence", () => {
    const editorSchema = editorSchemaForVideoTrack(track, schema);
    const request: PoseSaveRequest = {
      pose_id: "track-1:frame:12",
      base_revision: 4,
      schema_id: editorSchema.id,
      schema_revision: editorSchema.revision,
      observations: [
        {
          id: "track-1:12:0",
          semantic_label: "bell_center",
          occurrence_index: 0,
          x: 55,
          y: 65,
          confidence: 0.95,
          status: "visible",
          source: "corrected",
        },
        {
          id: "track-1:12:1",
          semantic_label: "tentacle",
          occurrence_index: 0,
          x: 75,
          y: 85,
          confidence: 0.72,
          status: "occluded",
          source: "corrected",
        },
      ],
    };

    const updated = correctedVideoKeyframeFromPoseSave(
      keyframe,
      schema,
      request,
    );

    expect(updated.keypoints).toEqual([
      [55, 65, 0.95],
      [75, 85, 0.72],
      [0, 0, 0],
    ]);
    expect(updated.pose_observations).toEqual(request.observations);
  });
});
