import { describe, expect, it } from "vitest";

import type { VideoTrackingBenchmark } from "./videoApi";
import { trackingBenchmarkCsv, trackingBenchmarkJson } from "./trackingReport";

const benchmark: VideoTrackingBenchmark = {
  schema_version: "video-tracking-benchmark-0001",
  video_id: "video-1",
  winner: "ByteTrack, tuned",
  ground_truth_track_ids: ["truth-1"],
  start_frame: 10,
  end_frame: 20,
  iou_threshold: 0.5,
  class_aware: true,
  results: [
    {
      rank: 1,
      name: "ByteTrack, tuned",
      source_job_id: "job-1",
      prediction_track_ids: ["prediction-1"],
      tracker: "bytetrack.yaml",
      model_id: "model-1",
      job_status: "succeeded",
      tracking_settings: {
        tracker: "bytetrack.yaml",
        confidence: 0.25,
        iou: 0.5,
      },
      evaluation: {
        schema_version: "video-tracking-evaluation-0001",
        video_id: "video-1",
        start_frame: 10,
        end_frame: 20,
        iou_threshold: 0.5,
        class_aware: true,
        matching_policy: "temporal-continuity-then-greedy-iou",
        ground_truth_track_ids: ["truth-1"],
        prediction_track_ids: ["prediction-1"],
        ground_truth_track_count: 1,
        prediction_track_count: 1,
        ground_truth_observations: 11,
        prediction_observations: 11,
        matched_observations: 10,
        missed_observations: 1,
        false_positive_observations: 1,
        recall: 10 / 11,
        precision: 10 / 11,
        missed_tracks: 0,
        false_positive_tracks: 0,
        false_positive_prediction_track_ids: [],
        id_switches: 0,
        fragmentations: 1,
        mean_iou: 0.9,
        mean_center_error_pixels: 1.5,
        mota: 9 / 11,
        per_track: [],
      },
    },
  ],
};

describe("tracking benchmark report serialization", () => {
  it("serializes deterministic scientific CSV with escaped candidate names", () => {
    const csv = trackingBenchmarkCsv(benchmark);
    const lines = csv.split("\n");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toBe(
      "rank,name,source_job_id,tracker,model_id,job_status,mota,recall,precision,matched_observations,missed_observations,false_positive_observations,missed_tracks,false_positive_tracks,id_switches,fragmentations,mean_iou,mean_center_error_pixels,ground_truth_track_count,prediction_track_count,start_frame,end_frame,evaluation_iou_threshold,class_aware,matching_policy,tracking_settings_json",
    );
    expect(lines[1]).toContain('1,"ByteTrack, tuned",job-1,bytetrack.yaml');
    expect(lines[1]).toContain("temporal-continuity-then-greedy-iou");
    expect(lines[1]).toContain('"{""tracker"":""bytetrack.yaml""');
  });

  it("serializes the exact benchmark schema as reproducibility JSON", () => {
    const json = trackingBenchmarkJson(benchmark);
    expect(json.endsWith("\n")).toBe(true);
    expect(JSON.parse(json)).toEqual(benchmark);
  });
});
