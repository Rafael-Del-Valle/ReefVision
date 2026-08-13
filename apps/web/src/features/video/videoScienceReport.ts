import type { VideoTrackActivity } from "./videoActivityApi";
import type { SchoolingAnalytics } from "./videoScienceApi";

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "string" ? value : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function csvRow(values: unknown[]): string {
  return values.map(csvCell).join(",");
}

export function schoolingReportJson(report: SchoolingAnalytics): string {
  return `${JSON.stringify(report, null, 2)}\n`;
}

export function schoolingSummaryCsv(report: SchoolingAnalytics): string {
  const header = [
    "video_id",
    "track_ids",
    "start_frame",
    "end_frame",
    "frames_evaluated",
    "mean_group_size",
    "mean_pairwise_distance_pixels",
    "mean_nearest_neighbor_distance_pixels",
    "mean_distance_to_centroid_pixels",
    "mean_pairwise_distance",
    "mean_nearest_neighbor_distance",
    "mean_distance_to_centroid",
    "mean_speed_pixels_per_second",
    "mean_speed_per_second",
    "mean_polarization",
    "distance_unit",
    "calibration_revision",
    "calibration_updated_at",
    "calibration_method",
    "calibration_reference_distance",
    "calibration_reference_pixels",
    "calibration_pixels_per_unit",
    "trajectory_policy",
  ];
  const row = [
    report.video_id,
    report.track_ids.join(";"),
    report.start_frame,
    report.end_frame,
    report.frames_evaluated,
    report.mean_group_size,
    report.mean_pairwise_distance_pixels,
    report.mean_nearest_neighbor_distance_pixels,
    report.mean_distance_to_centroid_pixels,
    report.mean_pairwise_distance,
    report.mean_nearest_neighbor_distance,
    report.mean_distance_to_centroid,
    report.mean_speed_pixels_per_second,
    report.mean_speed_per_second,
    report.mean_polarization,
    report.distance_unit,
    report.calibration.calibration_revision,
    report.calibration.calibration_updated_at,
    report.calibration.method,
    report.calibration.reference_distance,
    report.calibration.reference_pixels,
    report.calibration.pixels_per_unit,
    report.trajectory_policy,
  ];
  return `${csvRow(header)}\n${csvRow(row)}\n`;
}

export function schoolingFramesCsv(report: SchoolingAnalytics): string {
  const header = [
    "video_id",
    "frame",
    "timestamp_seconds",
    "active_track_count",
    "mean_pairwise_distance_pixels",
    "mean_nearest_neighbor_distance_pixels",
    "mean_distance_to_centroid_pixels",
    "mean_pairwise_distance",
    "mean_nearest_neighbor_distance",
    "mean_distance_to_centroid",
    "mean_speed_pixels_per_second",
    "mean_speed_per_second",
    "polarization",
    "distance_unit",
    "calibration_revision",
  ];
  const rows = report.frames.map((frame) =>
    csvRow([
      report.video_id,
      frame.frame,
      frame.timestamp_seconds,
      frame.active_track_count,
      frame.mean_pairwise_distance_pixels,
      frame.mean_nearest_neighbor_distance_pixels,
      frame.mean_distance_to_centroid_pixels,
      frame.mean_pairwise_distance,
      frame.mean_nearest_neighbor_distance,
      frame.mean_distance_to_centroid,
      frame.mean_speed_pixels_per_second,
      frame.mean_speed_per_second,
      frame.polarization,
      report.distance_unit,
      report.calibration.calibration_revision,
    ]),
  );
  return `${csvRow(header)}\n${rows.join("\n")}${rows.length ? "\n" : ""}`;
}

export function activityReportJson(report: VideoTrackActivity): string {
  return `${JSON.stringify(report, null, 2)}\n`;
}

export function activitySummaryCsv(report: VideoTrackActivity): string {
  const header = [
    "track_id",
    "video_id",
    "track_number",
    "label_class_id",
    "start_frame",
    "end_frame",
    "evaluated_seconds",
    "active_seconds",
    "rest_seconds",
    "active_fraction",
    "active_bout_count",
    "rest_bout_count",
    "mean_active_bout_seconds",
    "maximum_active_bout_seconds",
    "mean_rest_bout_seconds",
    "mean_active_speed_per_second",
    "maximum_speed_per_second",
    "speed_threshold_per_second",
    "speed_threshold_pixels_per_second",
    "minimum_active_bout_seconds",
    "distance_unit",
    "calibration_revision",
    "calibration_updated_at",
    "calibration_method",
    "calibration_reference_distance",
    "calibration_reference_pixels",
    "calibration_pixels_per_unit",
    "trajectory_policy",
  ];
  const row = [
    report.track_id,
    report.video_id,
    report.track_number,
    report.label_class_id,
    report.start_frame,
    report.end_frame,
    report.evaluated_seconds,
    report.active_seconds,
    report.rest_seconds,
    report.active_fraction,
    report.active_bout_count,
    report.rest_bout_count,
    report.mean_active_bout_seconds,
    report.maximum_active_bout_seconds,
    report.mean_rest_bout_seconds,
    report.mean_active_speed_per_second,
    report.maximum_speed_per_second,
    report.speed_threshold_per_second,
    report.speed_threshold_pixels_per_second,
    report.minimum_active_bout_seconds,
    report.distance_unit,
    report.calibration.calibration_revision,
    report.calibration.calibration_updated_at,
    report.calibration.method,
    report.calibration.reference_distance,
    report.calibration.reference_pixels,
    report.calibration.pixels_per_unit,
    report.trajectory_policy,
  ];
  return `${csvRow(header)}\n${csvRow(row)}\n`;
}

export function activityIntervalsCsv(report: VideoTrackActivity): string {
  const header = [
    "track_id",
    "start_frame",
    "end_frame",
    "start_time_seconds",
    "end_time_seconds",
    "duration_seconds",
    "distance_pixels",
    "distance",
    "speed_pixels_per_second",
    "speed_per_second",
    "active",
    "distance_unit",
    "speed_threshold_per_second",
    "calibration_revision",
  ];
  const rows = report.intervals.map((interval) =>
    csvRow([
      report.track_id,
      interval.start_frame,
      interval.end_frame,
      interval.start_time_seconds,
      interval.end_time_seconds,
      interval.duration_seconds,
      interval.distance_pixels,
      interval.distance,
      interval.speed_pixels_per_second,
      interval.speed_per_second,
      interval.active,
      report.distance_unit,
      report.speed_threshold_per_second,
      report.calibration.calibration_revision,
    ]),
  );
  return `${csvRow(header)}\n${rows.join("\n")}${rows.length ? "\n" : ""}`;
}

export function activityBoutsCsv(report: VideoTrackActivity): string {
  const header = [
    "track_id",
    "state",
    "start_frame",
    "end_frame",
    "start_time_seconds",
    "end_time_seconds",
    "duration_seconds",
    "interval_count",
    "speed_threshold_per_second",
    "minimum_active_bout_seconds",
    "distance_unit",
    "calibration_revision",
  ];
  const rows = report.bouts.map((bout) =>
    csvRow([
      report.track_id,
      bout.state,
      bout.start_frame,
      bout.end_frame,
      bout.start_time_seconds,
      bout.end_time_seconds,
      bout.duration_seconds,
      bout.interval_count,
      report.speed_threshold_per_second,
      report.minimum_active_bout_seconds,
      report.distance_unit,
      report.calibration.calibration_revision,
    ]),
  );
  return `${csvRow(header)}\n${rows.join("\n")}${rows.length ? "\n" : ""}`;
}
