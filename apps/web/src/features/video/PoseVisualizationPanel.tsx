import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  getPoseVisualization,
  poseVisualizationExportUrl,
  type PoseVisualizationCell,
  type PoseVisualizationMode,
  type PoseVisualizationRequest,
  type PoseVisualizationResponse,
} from "./poseVisualizationApi";

interface PoseVisualizationPanelProps {
  trackId: string;
  frameIndex: number;
}

function shortIdentity(value: string): string {
  return value.length > 12 ? value.slice(0, 8) : value;
}

function cellMetric(
  cell: PoseVisualizationCell,
  mode: PoseVisualizationMode,
): number | null {
  if (mode === "confidence") return cell.mean_landmark_confidence;
  if (mode === "occupancy") return cell.occupied_sampled_frame_fraction;
  if (mode === "activity") return cell.mean_speed_pixels_per_second;
  return null;
}

function metricLabel(
  mode: PoseVisualizationMode,
  maximumActivity: number,
): string {
  if (mode === "confidence") {
    return "Mean landmark confidence (0–1)";
  }
  if (mode === "occupancy") {
    return "Occupied sampled-frame fraction (0–100%)";
  }
  if (mode === "activity") {
    return `Mean landmark speed (0–${maximumActivity.toFixed(2)} px/s)`;
  }
  return "Persistent landmark trajectories (source pixels)";
}

function metricExplanation(mode: PoseVisualizationMode): string {
  if (mode === "confidence") {
    return "Each cell is the mean confidence of included landmark observations with a recorded confidence.";
  }
  if (mode === "occupancy") {
    return "Each cell is the fraction of sampled pose frames containing at least one included landmark observation.";
  }
  if (mode === "activity") {
    return "Each cell is the mean speed of resolved persistent-landmark movement segments whose midpoint falls inside the cell.";
  }
  return "Lines connect consecutive observations assigned to the same persistent landmark_track_id. Explicit identity breaks are never bridged.";
}

function normalizedMetric(
  value: number | null,
  mode: PoseVisualizationMode,
  maximumActivity: number,
): number {
  if (value === null || value <= 0) return 0;
  if (mode === "activity") {
    return maximumActivity > 0 ? Math.min(1, value / maximumActivity) : 0;
  }
  return Math.min(1, value);
}

function cellTitle(
  cell: PoseVisualizationCell,
  mode: PoseVisualizationMode,
): string {
  const prefix = `row ${cell.row + 1}, column ${cell.column + 1}`;
  if (mode === "confidence") {
    return (
      prefix +
      " · mean confidence " +
      (cell.mean_landmark_confidence === null
        ? "n/a"
        : cell.mean_landmark_confidence.toFixed(3)) +
      ` · ${cell.confidence_sample_count} confidence samples`
    );
  }
  if (mode === "occupancy") {
    return (
      prefix +
      ` · occupied ${(cell.occupied_sampled_frame_fraction * 100).toFixed(1)}%` +
      ` · ${cell.sample_count} landmark samples`
    );
  }
  return (
    prefix +
    " · mean speed " +
    (cell.mean_speed_pixels_per_second === null
      ? "n/a"
      : `${cell.mean_speed_pixels_per_second.toFixed(2)} px/s`) +
    ` · ${cell.movement_segment_count} movement segments`
  );
}

function parseOptionalNumber(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function PoseVisualizationPanel({
  trackId,
  frameIndex,
}: PoseVisualizationPanelProps) {
  const [mode, setMode] = useState<PoseVisualizationMode>("confidence");
  const [gridRows, setGridRows] = useState(24);
  const [gridColumns, setGridColumns] = useState(24);
  const [startFrame, setStartFrame] = useState("");
  const [endFrame, setEndFrame] = useState("");
  const [minimumConfidence, setMinimumConfidence] = useState("");
  const [includePredicted, setIncludePredicted] = useState(false);
  const [includeUncertain, setIncludeUncertain] = useState(true);
  const [generatedRequest, setGeneratedRequest] =
    useState<PoseVisualizationRequest | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const buildRequest = (): PoseVisualizationRequest => {
    const parsedStart = parseOptionalNumber(startFrame);
    const parsedEnd = parseOptionalNumber(endFrame);
    const parsedConfidence = parseOptionalNumber(minimumConfidence);
    if (
      gridRows < 1 ||
      gridRows > 100 ||
      gridColumns < 1 ||
      gridColumns > 100
    ) {
      throw new Error(
        "Pose visualization grid dimensions must be between 1 and 100",
      );
    }
    if (
      parsedStart !== undefined &&
      parsedEnd !== undefined &&
      parsedEnd < parsedStart
    ) {
      throw new Error(
        "Pose visualization end frame must be at or after the start frame",
      );
    }
    if (
      parsedConfidence !== undefined &&
      (parsedConfidence < 0 || parsedConfidence > 1)
    ) {
      throw new Error("Minimum landmark confidence must be between 0 and 1");
    }
    const payload: PoseVisualizationRequest = {
      grid_rows: gridRows,
      grid_columns: gridColumns,
      include_predicted: includePredicted,
      include_uncertain: includeUncertain,
    };
    if (parsedStart !== undefined) payload.start_frame = parsedStart;
    if (parsedEnd !== undefined) payload.end_frame = parsedEnd;
    if (parsedConfidence !== undefined) {
      payload.minimum_landmark_confidence = parsedConfidence;
    }
    return payload;
  };

  const visualizationMutation = useMutation({
    mutationFn: (payload: PoseVisualizationRequest) =>
      getPoseVisualization(trackId, payload),
    onSuccess: (_data, payload) => setGeneratedRequest(payload),
  });

  const data = visualizationMutation.data;
  const maximumActivity = useMemo(
    () =>
      Math.max(
        0,
        ...(data?.cells.map(
          (cell) => cell.mean_speed_pixels_per_second ?? 0,
        ) ?? [0]),
      ),
    [data?.cells],
  );
  const currentFramePoints = useMemo(
    () =>
      data?.trajectories.flatMap((trajectory) =>
        trajectory.points
          .filter((point) => point.frame_index === frameIndex)
          .map((point) => ({
            ...point,
            landmark_track_id: trajectory.landmark_track_id,
          })),
      ) ?? [],
    [data?.trajectories, frameIndex],
  );

  return (
    <section className="management-card" aria-label="Pose visualization">
      <p className="eyebrow">Pose visualization</p>
      <h3>Scientific pose visualization</h3>
      <p className="annotation-helper">
        Visualizations are derived from persisted canonical pose keyframes in
        source-image pixels. Confidence, occupancy, activity, and temporal
        trajectories use separate definitions and legends.
      </p>

      <label>
        Visualization
        <select
          aria-label="Pose visualization mode"
          value={mode}
          onChange={(event) =>
            setMode(event.target.value as PoseVisualizationMode)
          }
        >
          <option value="confidence">Keypoint confidence heatmap</option>
          <option value="occupancy">Landmark occupancy heatmap</option>
          <option value="activity">Landmark activity / speed heatmap</option>
          <option value="trajectory">Persistent landmark trajectories</option>
        </select>
      </label>

      <div className="annotation-selection-list">
        <label className="annotation-selection-row">
          Grid rows
          <input
            aria-label="Pose visualization grid rows"
            type="number"
            min={1}
            max={100}
            value={gridRows}
            onChange={(event) => setGridRows(Number(event.target.value))}
          />
        </label>
        <label className="annotation-selection-row">
          Grid columns
          <input
            aria-label="Pose visualization grid columns"
            type="number"
            min={1}
            max={100}
            value={gridColumns}
            onChange={(event) => setGridColumns(Number(event.target.value))}
          />
        </label>
        <label className="annotation-selection-row">
          Start frame
          <input
            aria-label="Pose visualization start frame"
            type="number"
            min={0}
            value={startFrame}
            placeholder="all"
            onChange={(event) => setStartFrame(event.target.value)}
          />
        </label>
        <label className="annotation-selection-row">
          End frame
          <input
            aria-label="Pose visualization end frame"
            type="number"
            min={0}
            value={endFrame}
            placeholder="all"
            onChange={(event) => setEndFrame(event.target.value)}
          />
        </label>
        <label className="annotation-selection-row">
          Minimum confidence
          <input
            aria-label="Pose visualization minimum confidence"
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={minimumConfidence}
            placeholder="none"
            onChange={(event) => setMinimumConfidence(event.target.value)}
          />
        </label>
      </div>

      <label className="annotation-selection-row">
        <input
          type="checkbox"
          checked={includeUncertain}
          onChange={(event) => setIncludeUncertain(event.target.checked)}
        />
        <span>Include uncertain observed landmarks</span>
      </label>
      <label className="annotation-selection-row">
        <input
          type="checkbox"
          checked={includePredicted}
          onChange={(event) => setIncludePredicted(event.target.checked)}
        />
        <span>Include occlusion-predicted coordinates</span>
      </label>
      <p className="annotation-helper">
        Predicted occlusion coordinates are excluded by default and are counted
        separately from observed coordinates when included.
      </p>

      <button
        type="button"
        disabled={visualizationMutation.isPending}
        onClick={() => {
          try {
            setValidationError(null);
            visualizationMutation.mutate(buildRequest());
          } catch (error) {
            setValidationError(
              error instanceof Error
                ? error.message
                : "Pose visualization settings are invalid",
            );
          }
        }}
      >
        {visualizationMutation.isPending
          ? "Generating visualization..."
          : "Generate pose visualization"}
      </button>

      {validationError && <p className="form-error">{validationError}</p>}
      {visualizationMutation.error instanceof Error && (
        <p className="form-error">{visualizationMutation.error.message}</p>
      )}

      {data && (
        <>
          <div className="workspace-guide compact">
            <div>
              <strong>{metricLabel(mode, maximumActivity)}</strong>
              <p className="annotation-helper">{metricExplanation(mode)}</p>
              <p className="annotation-helper">
                Frames {data.start_frame}–{data.end_frame} ·{" "}
                {data.sampled_frame_count} sampled pose frames ·{" "}
                {data.spatial_sample_count} included landmark samples.
              </p>
              <p className="annotation-helper">
                Observed {data.observed_sample_count} · predicted{" "}
                {data.predicted_sample_count} · excluded missing{" "}
                {data.excluded_missing_coordinate_count} · excluded by filters{" "}
                {data.excluded_filter_count}.
              </p>
              <p className="annotation-helper">
                Coordinate space: source pixels · sampling: persisted canonical
                pose keyframes · track revision {data.source_track_revision}.
              </p>
            </div>
          </div>

          {data.identity_status !== "current" && data.identity_warning && (
            <p role="alert" className="form-error">
              {data.identity_warning}
            </p>
          )}

          <div
            style={{
              width: "100%",
              aspectRatio: `${data.video_width_pixels} / ${data.video_height_pixels}`,
              border: "1px solid var(--border-color, currentColor)",
              borderRadius: 8,
              overflow: "hidden",
            }}
          >
            <svg
              role="img"
              aria-label={`${mode} pose visualization`}
              data-testid="pose-visualization-canvas"
              viewBox={`0 0 ${data.video_width_pixels} ${data.video_height_pixels}`}
              preserveAspectRatio="xMidYMid meet"
              style={{ display: "block", width: "100%", height: "100%" }}
            >
              {mode !== "trajectory" &&
                data.cells.map((cell) => {
                  const value = cellMetric(cell, mode);
                  const normalized = normalizedMetric(
                    value,
                    mode,
                    maximumActivity,
                  );
                  return (
                    <rect
                      key={`${cell.row}-${cell.column}`}
                      data-testid="pose-heatmap-cell"
                      x={cell.x_min_pixels}
                      y={cell.y_min_pixels}
                      width={cell.x_max_pixels - cell.x_min_pixels}
                      height={cell.y_max_pixels - cell.y_min_pixels}
                      fill="var(--accent-color, #2563eb)"
                      fillOpacity={
                        normalized === 0 ? 0 : Math.max(0.08, normalized)
                      }
                      stroke="var(--border-color, currentColor)"
                      strokeOpacity={0.15}
                      strokeWidth={0.5}
                    >
                      <title>{cellTitle(cell, mode)}</title>
                    </rect>
                  );
                })}

              {mode === "trajectory" &&
                data.trajectories.flatMap((trajectory) =>
                  trajectory.segments
                    .filter((segment) => segment.points.length > 1)
                    .map((segment) => (
                      <polyline
                        key={`${trajectory.landmark_track_id}-${segment.segment_index}`}
                        data-testid="pose-trajectory"
                        points={segment.points
                          .map((point) => `${point.x_px},${point.y_px}`)
                          .join(" ")}
                        fill="none"
                        stroke="var(--accent-color, #2563eb)"
                        strokeWidth={2}
                        strokeOpacity={0.85}
                        vectorEffect="non-scaling-stroke"
                      >
                        <title>
                          {trajectory.semantic_label} ·{" "}
                          {shortIdentity(trajectory.landmark_track_id)} ·
                          segment {segment.segment_index + 1} · path{" "}
                          {segment.path_length_pixels.toFixed(1)} px ·{" "}
                          {segment.movement_segment_count} movement segments
                        </title>
                      </polyline>
                    )),
                )}

              {mode === "trajectory" &&
                currentFramePoints.map((point) => (
                  <circle
                    key={`${point.landmark_track_id}-${point.frame_index}-${point.occurrence_index}`}
                    data-testid="pose-current-frame-point"
                    cx={point.x_px}
                    cy={point.y_px}
                    r={4}
                    fill="var(--accent-color, #2563eb)"
                    stroke="white"
                    strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke"
                  >
                    <title>
                      frame {point.frame_index} · {point.semantic_label} ·{" "}
                      {shortIdentity(point.landmark_track_id)}
                    </title>
                  </circle>
                ))}
            </svg>
          </div>

          {mode === "trajectory" && data.identity_status === "current" && (
            <div className="annotation-selection-list">
              {data.trajectories.map((trajectory) => (
                <div
                  className="annotation-selection-row"
                  key={trajectory.landmark_track_id}
                >
                  <strong>
                    {trajectory.semantic_label} ·{" "}
                    {shortIdentity(trajectory.landmark_track_id)}
                  </strong>
                  <span className="annotation-helper">
                    {trajectory.points.length} points ·{" "}
                    {trajectory.segments.length} continuity segments ·{" "}
                    {trajectory.path_length_pixels.toFixed(1)} px path ·{" "}
                    {trajectory.movement_segment_count} movement segments
                  </span>
                </div>
              ))}
            </div>
          )}

          {generatedRequest && (
            <div className="workspace-actions">
              <a
                href={poseVisualizationExportUrl(
                  trackId,
                  generatedRequest,
                  "json",
                )}
              >
                Export visualization JSON
              </a>
              <a
                href={poseVisualizationExportUrl(
                  trackId,
                  generatedRequest,
                  "cells_csv",
                )}
              >
                Export heatmap cells CSV
              </a>
              {data.identity_status === "current" &&
                data.trajectories.length > 0 && (
                  <a
                    href={poseVisualizationExportUrl(
                      trackId,
                      generatedRequest,
                      "trajectories_csv",
                    )}
                  >
                    Export trajectories CSV
                  </a>
                )}
            </div>
          )}

          <div className="workspace-guide compact">
            <div>
              <strong>Provider visualization capability</strong>
              <p className="annotation-helper">
                Provider: {data.provider_capabilities.provider_name ?? "none"} ·
                canonical keypoint scores:{" "}
                {data.provider_capabilities.keypoint_scores_persisted
                  ? "persisted"
                  : "not persisted"}
                {" · "}native confidence maps:{" "}
                {data.provider_capabilities.native_confidence_maps_persisted
                  ? "persisted"
                  : "not persisted"}
                {" · "}raw tensor export:{" "}
                {data.provider_capabilities.raw_tensor_export_available
                  ? "available"
                  : "unavailable"}
                .
              </p>
              <p className="annotation-helper">
                {data.provider_capabilities.reason}
              </p>
            </div>
          </div>

          <div className="workspace-guide compact">
            <div>
              <strong>Part-affinity fields (PAF)</strong>
              <p className="annotation-helper">
                {data.paf.available
                  ? `Raw PAF data reported by ${data.paf.provider_name ?? "the pose provider"}.`
                  : data.paf.reason}
              </p>
              {!data.paf.available && (
                <p className="annotation-helper">
                  ReefVision does not synthesize PAFs from keypoints.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export function poseVisualizationSummaryForTesting(
  data: PoseVisualizationResponse,
  mode: PoseVisualizationMode,
): string {
  const maximumActivity = Math.max(
    0,
    ...data.cells.map((cell) => cell.mean_speed_pixels_per_second ?? 0),
  );
  return metricLabel(mode, maximumActivity);
}
