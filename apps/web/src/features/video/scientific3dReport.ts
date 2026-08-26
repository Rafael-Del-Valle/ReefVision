import type { MetricVideoDepth3DResult } from "./videoScienceApi";

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "string" ? value : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function row(values: unknown[]): string {
  return values.map(csvCell).join(",");
}

export function scientific3DReportJson(
  report: MetricVideoDepth3DResult,
): string {
  return `${JSON.stringify(report, null, 2)}\n`;
}

export function scientific3DTrajectoriesCsv(
  report: MetricVideoDepth3DResult,
): string {
  const header = [
    "video_id",
    "track_id",
    "track_number",
    "label_class_id",
    "frame",
    "timestamp_seconds",
    "center_x_px",
    "center_y_px",
    "x_m",
    "y_m",
    "z_m",
    "depth_confidence",
    "depth_tier",
    "physical_measurement_claim_allowed",
    "model_revision",
    "source_commit",
  ];
  const rows = report.analytics.tracks.flatMap((track) =>
    track.points.map((point) =>
      row([
        report.video_id,
        track.track_id,
        track.track_number,
        track.label_class_id,
        point.frame,
        point.timestamp_seconds,
        point.center_x_px,
        point.center_y_px,
        point.x,
        point.y,
        point.z,
        point.depth_confidence,
        report.depth_tier,
        report.physical_measurement_claim_allowed,
        report.model_revision,
        report.source_commit,
      ]),
    ),
  );
  return `${row(header)}\n${rows.join("\n")}${rows.length ? "\n" : ""}`;
}

export function scientific3DGroupFramesCsv(
  report: MetricVideoDepth3DResult,
): string {
  const header = [
    "video_id",
    "frame",
    "timestamp_seconds",
    "individual_count",
    "centroid_x_m",
    "centroid_y_m",
    "centroid_z_m",
    "mean_nearest_neighbor_distance_m",
    "mean_pairwise_distance_m",
    "bounding_box_volume_m3",
    "depth_tier",
    "physical_measurement_claim_allowed",
  ];
  const rows = report.group_3d_frames.map((frame) =>
    row([
      report.video_id,
      frame.frame,
      frame.timestamp_seconds,
      frame.individual_count,
      frame.centroid_x,
      frame.centroid_y,
      frame.centroid_z,
      frame.mean_nearest_neighbor_distance,
      frame.mean_pairwise_distance,
      frame.bounding_box_volume,
      report.depth_tier,
      report.physical_measurement_claim_allowed,
    ]),
  );
  return `${row(header)}\n${rows.join("\n")}${rows.length ? "\n" : ""}`;
}
