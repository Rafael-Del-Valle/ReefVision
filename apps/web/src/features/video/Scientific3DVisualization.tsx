import { useMemo, useState } from "react";

import type { MetricVideoDepth3DResult } from "./videoScienceApi";

interface Scientific3DVisualizationProps {
  result: MetricVideoDepth3DResult;
  classNames: Map<string, string>;
}

interface XY {
  x: number;
  y: number;
}

const WIDTH = 620;
const HEIGHT = 240;
const LEFT = 58;
const RIGHT = 18;
const TOP = 18;
const BOTTOM = 38;

function extent(values: number[]): [number, number] {
  const clean = values.filter(Number.isFinite);
  if (clean.length === 0) return [0, 1];
  const minimum = Math.min(...clean);
  const maximum = Math.max(...clean);
  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * 0.05, 0.5);
    return [minimum - padding, maximum + padding];
  }
  const padding = (maximum - minimum) * 0.06;
  return [minimum - padding, maximum + padding];
}

function scale(
  value: number,
  domainMin: number,
  domainMax: number,
  rangeMin: number,
  rangeMax: number,
): number {
  if (domainMax === domainMin) return (rangeMin + rangeMax) / 2;
  return (
    rangeMin +
    ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin)
  );
}

function polyline(points: XY[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

function formatTick(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 100) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function LineChart({
  values,
  xLabel,
  yLabel,
  title,
}: {
  values: XY[];
  xLabel: string;
  yLabel: string;
  title: string;
}) {
  const xExtent = extent(values.map((point) => point.x));
  const yExtent = extent(values.map((point) => point.y));
  const plotLeft = LEFT;
  const plotRight = WIDTH - RIGHT;
  const plotTop = TOP;
  const plotBottom = HEIGHT - BOTTOM;
  const points = values.map((point) => ({
    x: scale(point.x, xExtent[0], xExtent[1], plotLeft, plotRight),
    y: scale(point.y, yExtent[0], yExtent[1], plotBottom, plotTop),
  }));

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={title}
      style={{ width: "100%", minHeight: 220 }}
    >
      <line
        x1={plotLeft}
        y1={plotTop}
        x2={plotLeft}
        y2={plotBottom}
        stroke="currentColor"
      />
      <line
        x1={plotLeft}
        y1={plotBottom}
        x2={plotRight}
        y2={plotBottom}
        stroke="currentColor"
      />
      <polyline
        points={polyline(points)}
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        vectorEffect="non-scaling-stroke"
      />
      {points.map((point, index) => (
        <circle
          key={`${point.x}-${point.y}-${index}`}
          cx={point.x}
          cy={point.y}
          r={2.6}
          fill="currentColor"
        />
      ))}
      <text x={plotLeft} y={HEIGHT - 9} fontSize={11}>
        {formatTick(xExtent[0])}
      </text>
      <text x={plotRight} y={HEIGHT - 9} fontSize={11} textAnchor="end">
        {formatTick(xExtent[1])}
      </text>
      <text x={plotLeft - 7} y={plotBottom} fontSize={11} textAnchor="end">
        {formatTick(yExtent[0])}
      </text>
      <text x={plotLeft - 7} y={plotTop + 4} fontSize={11} textAnchor="end">
        {formatTick(yExtent[1])}
      </text>
      <text
        x={(plotLeft + plotRight) / 2}
        y={HEIGHT - 8}
        fontSize={12}
        textAnchor="middle"
      >
        {xLabel}
      </text>
      <text
        x={15}
        y={(plotTop + plotBottom) / 2}
        fontSize={12}
        textAnchor="middle"
        transform={`rotate(-90 15 ${(plotTop + plotBottom) / 2})`}
      >
        {yLabel}
      </text>
    </svg>
  );
}

function Projection({
  values,
  firstLabel,
  secondLabel,
  title,
}: {
  values: Array<{ first: number; second: number }>;
  firstLabel: string;
  secondLabel: string;
  title: string;
}) {
  const firstExtent = extent(values.map((point) => point.first));
  const secondExtent = extent(values.map((point) => point.second));
  const plotLeft = LEFT;
  const plotRight = WIDTH - RIGHT;
  const plotTop = TOP;
  const plotBottom = HEIGHT - BOTTOM;
  const points = values.map((point) => ({
    x: scale(point.first, firstExtent[0], firstExtent[1], plotLeft, plotRight),
    y: scale(
      point.second,
      secondExtent[0],
      secondExtent[1],
      plotBottom,
      plotTop,
    ),
  }));

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={title}
      style={{ width: "100%", minHeight: 210 }}
    >
      <line
        x1={plotLeft}
        y1={plotTop}
        x2={plotLeft}
        y2={plotBottom}
        stroke="currentColor"
      />
      <line
        x1={plotLeft}
        y1={plotBottom}
        x2={plotRight}
        y2={plotBottom}
        stroke="currentColor"
      />
      <polyline
        points={polyline(points)}
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        vectorEffect="non-scaling-stroke"
      />
      {points.length > 0 && (
        <>
          <circle
            cx={points[0].x}
            cy={points[0].y}
            r={5}
            fill="currentColor"
            opacity={0.55}
          />
          <circle
            cx={points[points.length - 1].x}
            cy={points[points.length - 1].y}
            r={5}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
          />
        </>
      )}
      <text
        x={(plotLeft + plotRight) / 2}
        y={HEIGHT - 8}
        fontSize={12}
        textAnchor="middle"
      >
        {firstLabel}
      </text>
      <text
        x={15}
        y={(plotTop + plotBottom) / 2}
        fontSize={12}
        textAnchor="middle"
        transform={`rotate(-90 15 ${(plotTop + plotBottom) / 2})`}
      >
        {secondLabel}
      </text>
    </svg>
  );
}

function DepthHeatStrip({
  values,
}: {
  values: Array<{ time: number; depth: number; confidence: number | null }>;
}) {
  if (values.length === 0) return null;
  const minimum = Math.min(...values.map((item) => item.depth));
  const maximum = Math.max(...values.map((item) => item.depth));
  const span = maximum - minimum || 1;

  return (
    <div>
      <div
        role="img"
        aria-label="Track depth heat strip"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${values.length}, minmax(2px, 1fr))`,
          minHeight: 34,
          overflow: "hidden",
          borderRadius: 6,
        }}
      >
        {values.map((item, index) => {
          const normalized = Math.max(
            0,
            Math.min(1, (item.depth - minimum) / span),
          );
          const hue = 220 - normalized * 220;
          const opacity =
            item.confidence === null
              ? 0.72
              : Math.max(0.3, Math.min(1, item.confidence));
          return (
            <span
              key={`${item.time}-${index}`}
              title={`${item.time.toFixed(2)} s · ${item.depth.toFixed(3)} m`}
              style={{
                background: `hsl(${hue} 78% 50%)`,
                opacity,
              }}
            />
          );
        })}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.78rem",
          marginTop: 4,
        }}
      >
        <span>Nearer · {minimum.toFixed(3)} m</span>
        <span>Farther · {maximum.toFixed(3)} m</span>
      </div>
    </div>
  );
}

export function Scientific3DVisualization({
  result,
  classNames,
}: Scientific3DVisualizationProps) {
  const [trackId, setTrackId] = useState(
    result.analytics.tracks[0]?.track_id ?? "",
  );
  const selectedTrack =
    result.analytics.tracks.find((track) => track.track_id === trackId) ??
    result.analytics.tracks[0];

  const depthSeries = useMemo(
    () =>
      (selectedTrack?.points ?? []).map((point) => ({
        time: point.timestamp_seconds,
        depth: point.z,
        confidence: point.depth_confidence,
      })),
    [selectedTrack],
  );

  const confidenceValues = depthSeries
    .map((point) => point.confidence)
    .filter(
      (value): value is number => value !== null && Number.isFinite(value),
    );
  const meanConfidence =
    confidenceValues.length > 0
      ? confidenceValues.reduce((total, value) => total + value, 0) /
        confidenceValues.length
      : null;

  const groupNnSeries = result.group_3d_frames
    .filter(
      (frame) =>
        frame.mean_nearest_neighbor_distance !== null &&
        Number.isFinite(frame.mean_nearest_neighbor_distance),
    )
    .map((frame) => ({
      x: frame.timestamp_seconds,
      y: frame.mean_nearest_neighbor_distance as number,
    }));

  const groupPairwiseSeries = result.group_3d_frames
    .filter(
      (frame) =>
        frame.mean_pairwise_distance !== null &&
        Number.isFinite(frame.mean_pairwise_distance),
    )
    .map((frame) => ({
      x: frame.timestamp_seconds,
      y: frame.mean_pairwise_distance as number,
    }));

  if (!selectedTrack) {
    return (
      <section className="panel-card">
        <h4>Scientific 3D visualization</h4>
        <p className="annotation-helper">
          No reconstructed tracks are available to visualize.
        </p>
      </section>
    );
  }

  return (
    <section className="panel-card" data-testid="scientific-3d-visualization">
      <p className="eyebrow">Scientific visualization</p>
      <h4>Depth and X/Y/Z trajectories</h4>
      <p className="annotation-helper">
        These plots display ReefVision&apos;s reconstructed model-estimated
        metric geometry. They visualize the result but do not upgrade it to
        validated physical measurement.
      </p>

      <label>
        Track
        <select
          value={selectedTrack.track_id}
          onChange={(event) => setTrackId(event.target.value)}
        >
          {result.analytics.tracks.map((track) => (
            <option key={track.track_id} value={track.track_id}>
              Track {track.track_number} —{" "}
              {classNames.get(track.label_class_id) ?? "Unknown class"}
            </option>
          ))}
        </select>
      </label>

      <div className="annotation-selection-list">
        <div className="annotation-selection-row">
          <strong>Samples</strong>
          <span>{selectedTrack.points.length.toLocaleString()}</span>
        </div>
        <div className="annotation-selection-row">
          <strong>Mean estimated depth</strong>
          <span>{selectedTrack.mean_depth.toFixed(4)} m</span>
        </div>
        <div className="annotation-selection-row">
          <strong>Mean depth confidence</strong>
          <span>
            {meanConfidence === null ? "—" : meanConfidence.toFixed(3)}
          </span>
        </div>
        <div className="annotation-selection-row">
          <strong>Validity tier</strong>
          <span>{result.depth_tier.replaceAll("_", " ")}</span>
        </div>
      </div>

      <h5>Depth profile</h5>
      <DepthHeatStrip values={depthSeries} />
      <LineChart
        values={depthSeries.map((point) => ({
          x: point.time,
          y: point.depth,
        }))}
        xLabel="Time (s)"
        yLabel="Estimated depth (m)"
        title="Estimated depth over time"
      />

      <h5>Orthographic 3D trajectory projections</h5>
      <p className="annotation-helper">
        Filled circle = first reconstructed point. Open circle = final
        reconstructed point. The three views show the same X/Y/Z trajectory
        without perspective distortion.
      </p>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        <div>
          <strong>Top view · X/Y</strong>
          <Projection
            values={selectedTrack.points.map((point) => ({
              first: point.x,
              second: point.y,
            }))}
            firstLabel="X (m)"
            secondLabel="Y (m)"
            title="Top-view X Y trajectory"
          />
        </div>
        <div>
          <strong>Side view · X/Z</strong>
          <Projection
            values={selectedTrack.points.map((point) => ({
              first: point.x,
              second: point.z,
            }))}
            firstLabel="X (m)"
            secondLabel="Z / depth (m)"
            title="Side-view X Z trajectory"
          />
        </div>
        <div>
          <strong>Front view · Y/Z</strong>
          <Projection
            values={selectedTrack.points.map((point) => ({
              first: point.y,
              second: point.z,
            }))}
            firstLabel="Y (m)"
            secondLabel="Z / depth (m)"
            title="Front-view Y Z trajectory"
          />
        </div>
      </div>

      {result.group_3d_frames.length > 0 && (
        <>
          <h5>Group 3D spacing</h5>
          <p className="annotation-helper">
            Group metrics use simultaneous reconstructed fish positions. Frames
            with fewer than two valid individuals do not contribute a neighbor
            or pairwise distance.
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: 12,
            }}
          >
            {groupNnSeries.length > 0 && (
              <div>
                <strong>Nearest-neighbor distance</strong>
                <LineChart
                  values={groupNnSeries}
                  xLabel="Time (s)"
                  yLabel="Distance (m)"
                  title="3D nearest-neighbor distance over time"
                />
              </div>
            )}
            {groupPairwiseSeries.length > 0 && (
              <div>
                <strong>Mean pairwise distance</strong>
                <LineChart
                  values={groupPairwiseSeries}
                  xLabel="Time (s)"
                  yLabel="Distance (m)"
                  title="3D pairwise distance over time"
                />
              </div>
            )}
          </div>
        </>
      )}

      <p className="annotation-helper">
        Display coordinates are in meters because the selected VDA checkpoint is
        a metric-depth model. ReefVision still requires independent underwater
        validation before these values may be reported as validated physical
        measurements.
      </p>
    </section>
  );
}
