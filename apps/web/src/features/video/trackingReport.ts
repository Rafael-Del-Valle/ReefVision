import type { VideoTrackingBenchmark } from "./videoApi";

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  if (!/[",\n\r]/.test(text)) return text;
  return `"${text.replaceAll('"', '""')}"`;
}

export function trackingBenchmarkCsv(
  benchmark: VideoTrackingBenchmark,
): string {
  const headers = [
    "rank",
    "name",
    "source_job_id",
    "tracker",
    "model_id",
    "job_status",
    "mota",
    "recall",
    "precision",
    "matched_observations",
    "missed_observations",
    "false_positive_observations",
    "missed_tracks",
    "false_positive_tracks",
    "id_switches",
    "fragmentations",
    "mean_iou",
    "mean_center_error_pixels",
    "ground_truth_track_count",
    "prediction_track_count",
    "start_frame",
    "end_frame",
    "evaluation_iou_threshold",
    "class_aware",
    "matching_policy",
    "tracking_settings_json",
  ];

  const rows = benchmark.results.map((result) => {
    const evaluation = result.evaluation;
    return [
      result.rank,
      result.name,
      result.source_job_id,
      result.tracker,
      result.model_id,
      result.job_status,
      evaluation.mota,
      evaluation.recall,
      evaluation.precision,
      evaluation.matched_observations,
      evaluation.missed_observations,
      evaluation.false_positive_observations,
      evaluation.missed_tracks,
      evaluation.false_positive_tracks,
      evaluation.id_switches,
      evaluation.fragmentations,
      evaluation.mean_iou,
      evaluation.mean_center_error_pixels,
      evaluation.ground_truth_track_count,
      evaluation.prediction_track_count,
      evaluation.start_frame,
      evaluation.end_frame,
      evaluation.iou_threshold,
      evaluation.class_aware,
      evaluation.matching_policy,
      JSON.stringify(result.tracking_settings),
    ];
  });

  return [headers, ...rows]
    .map((row) => row.map((value) => csvCell(value)).join(","))
    .join("\n");
}

export function trackingBenchmarkJson(
  benchmark: VideoTrackingBenchmark,
): string {
  return `${JSON.stringify(benchmark, null, 2)}\n`;
}
