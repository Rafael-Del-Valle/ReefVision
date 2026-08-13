import type { VideoOccupancyAnalytics } from "./videoOccupancyApi";

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "string" ? value : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function row(values: unknown[]): string {
  return values.map(csvCell).join(",");
}

export function occupancyReportJson(report: VideoOccupancyAnalytics): string {
  return `${JSON.stringify(report, null, 2)}\n`;
}

export function occupancyCellsCsv(report: VideoOccupancyAnalytics): string {
  const header = [
    "video_id",
    "start_frame",
    "end_frame",
    "grid_rows",
    "grid_columns",
    "row",
    "column",
    "x_min_pixels",
    "y_min_pixels",
    "x_max_pixels",
    "y_max_pixels",
    "observation_count",
    "observation_fraction",
    "occupied_frame_count",
    "occupied_frame_fraction",
    "unique_track_count",
    "dwell_seconds",
    "trajectory_policy",
  ];
  const rows = report.cells.map((cell) =>
    row([
      report.video_id,
      report.start_frame,
      report.end_frame,
      report.grid_rows,
      report.grid_columns,
      cell.row,
      cell.column,
      cell.x_min_pixels,
      cell.y_min_pixels,
      cell.x_max_pixels,
      cell.y_max_pixels,
      cell.observation_count,
      cell.observation_fraction,
      cell.occupied_frame_count,
      cell.occupied_frame_fraction,
      cell.unique_track_count,
      cell.dwell_seconds,
      report.trajectory_policy,
    ]),
  );
  return `${row(header)}\n${rows.join("\n")}${rows.length ? "\n" : ""}`;
}

export function occupancyTracksCsv(report: VideoOccupancyAnalytics): string {
  const header = [
    "video_id",
    "track_id",
    "track_number",
    "label_class_id",
    "observation_count",
    "dwell_seconds",
    "occupied_cell_count",
    "most_occupied_row",
    "most_occupied_column",
    "most_occupied_fraction",
    "grid_rows",
    "grid_columns",
    "start_frame",
    "end_frame",
    "trajectory_policy",
  ];
  const rows = report.per_track.map((track) =>
    row([
      report.video_id,
      track.track_id,
      track.track_number,
      track.label_class_id,
      track.observation_count,
      track.dwell_seconds,
      track.occupied_cell_count,
      track.most_occupied_row,
      track.most_occupied_column,
      track.most_occupied_fraction,
      report.grid_rows,
      report.grid_columns,
      report.start_frame,
      report.end_frame,
      report.trajectory_policy,
    ]),
  );
  return `${row(header)}\n${rows.join("\n")}${rows.length ? "\n" : ""}`;
}
