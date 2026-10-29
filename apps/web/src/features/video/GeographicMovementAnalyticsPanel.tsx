import type {
  GeographicCoordinate,
  GeographicTrackAnalytics,
} from "./videoGeographicMovementAnalyticsApi";

import type { GeographicMovementAnalyticsState } from "./videoGeographicMovementAnalyticsState";

import {
  activeGeographicSegmentForFrame,
  geographicSegmentSeekTarget,
} from "./videoGeographicMovementSynchronization";

interface GeographicMovementAnalyticsPanelProps {
  state: GeographicMovementAnalyticsState;
  onReload: () => void;
  activeFrameIndex?: number | null;
  onFrameSelect?: (frameIndex: number, frameTimeSeconds: number) => void;
}

function meters(value: number | null): string {
  return value === null ? "Unavailable" : `${value.toFixed(2)} m`;
}

function seconds(value: number | null): string {
  return value === null ? "Unavailable" : `${value.toFixed(2)} s`;
}

function speed(value: number | null): string {
  return value === null ? "Unavailable" : `${value.toFixed(2)} m/s`;
}

function bearing(value: number | null | undefined): string {
  return value == null ? "Unavailable" : `${value.toFixed(2)}°`;
}

function coordinate(value: GeographicCoordinate | null): string {
  if (value === null) {
    return "Unavailable";
  }

  return (
    `${value.latitude_deg.toFixed(6)}, ` +
    `${value.longitude_deg.toFixed(6)} ` +
    `(${value.crs})`
  );
}

function AnalyticsResults({
  data,
  activeFrameIndex,
  onFrameSelect,
}: {
  data: GeographicTrackAnalytics;
  activeFrameIndex: number | null;
  onFrameSelect?: (frameIndex: number, frameTimeSeconds: number) => void;
}) {
  const activeSegment = activeGeographicSegmentForFrame(
    data.segments,
    activeFrameIndex,
  );

  if (data.observation_count === 0) {
    return (
      <div role="status" data-testid="geographic-analytics-empty">
        <p>No fresh geographic observations for this track.</p>
        <p className="annotation-helper">
          Geographic movement metrics are not available yet.
        </p>
      </div>
    );
  }

  const metrics = [
    ["Total distance", meters(data.total_distance_m)],
    ["Net displacement", meters(data.net_displacement_m)],
    ["Elapsed time", seconds(data.elapsed_time_s)],
    ["Mean speed", speed(data.mean_speed_m_s)],
    ["Maximum segment speed", speed(data.max_segment_speed_m_s)],
  ];

  return (
    <>
      <p className="annotation-helper">
        {data.observation_count.toLocaleString()} observations;{" "}
        {data.segment_count.toLocaleString()} trajectory segments
      </p>

      <dl className="annotation-selection-list">
        {metrics.map(([label, value]) => (
          <div className="annotation-selection-row" key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}

        <div className="annotation-selection-row">
          <dt>Start position</dt>
          <dd>{coordinate(data.start_location)}</dd>
        </div>

        <div className="annotation-selection-row">
          <dt>End position</dt>
          <dd>{coordinate(data.end_location)}</dd>
        </div>
      </dl>

      {data.segments.length === 0 ? (
        <p className="annotation-helper">No trajectory segments available.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table aria-label="Geographic trajectory segments">
            <thead>
              <tr>
                <th>From frame</th>
                <th>To frame</th>
                <th>Distance</th>
                <th>Elapsed</th>
                <th>Speed</th>
                <th>Speed status</th>
                <th>Initial bearing</th>
                <th>Video</th>
              </tr>
            </thead>

            <tbody>
              {data.segments.map((segment) => {
                const active = activeSegment === segment;
                const target = geographicSegmentSeekTarget(segment);

                return (
                  <tr
                    key={`${segment.start_observation_id}:${segment.end_observation_id}`}
                    data-active-segment={active ? "true" : "false"}
                    aria-current={active ? "step" : undefined}
                  >
                    <td>{segment.start_frame_index}</td>
                    <td>{segment.end_frame_index}</td>
                    <td>{meters(segment.distance_m)}</td>
                    <td>{seconds(segment.elapsed_time_s)}</td>
                    <td>
                      {segment.speed_valid
                        ? speed(segment.speed_m_s)
                        : "Unavailable"}
                    </td>
                    <td>
                      {segment.speed_valid
                        ? "Valid"
                        : segment.invalid_reason === "non_positive_elapsed_time"
                          ? "Non-positive elapsed time"
                          : (segment.invalid_reason ?? "Invalid")}
                    </td>
                    <td>{bearing(segment.initial_bearing_deg)}</td>
                    <td>
                      {onFrameSelect && target ? (
                        <button
                          type="button"
                          className="secondary"
                          onClick={() =>
                            onFrameSelect(
                              target.frameIndex,
                              target.frameTimeSeconds,
                            )
                          }
                        >
                          Seek to frame {target.frameIndex}
                        </button>
                      ) : (
                        "Unavailable"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function GeographicMovementAnalyticsPanel({
  state,
  onReload,
  activeFrameIndex = null,
  onFrameSelect,
}: GeographicMovementAnalyticsPanelProps) {
  return (
    <section
      className="management-card"
      aria-label="Geographic movement analytics"
      data-testid="geographic-movement-analytics-panel"
      data-status={state.status}
      data-track-id={state.trackId ?? ""}
    >
      <p className="eyebrow">Georeferenced tracking</p>

      <h3>Geographic movement analytics</h3>

      <p className="annotation-helper">
        Movement metrics calculated from fresh persisted geographic
        observations. Initial bearing describes displacement between sampled
        positions on WGS84, in degrees clockwise from true north. Organism
        orientation is not measured; coincident positions have no bearing.
      </p>

      <button
        type="button"
        className="secondary"
        onClick={onReload}
        disabled={state.status === "idle" || state.status === "loading"}
      >
        Refresh analytics
      </button>

      {state.status === "idle" && (
        <p role="status">
          Select an existing track to view geographic movement analytics.
        </p>
      )}

      {state.status === "loading" && (
        <p role="status" aria-live="polite">
          Loading geographic movement analytics...
        </p>
      )}

      {state.status === "error" && (
        <div role="alert">
          <strong>Unable to load geographic movement analytics.</strong>

          <p className="error-copy">{state.error}</p>

          <button type="button" className="secondary" onClick={onReload}>
            Retry geographic analytics
          </button>
        </div>
      )}

      {state.status === "success" && (
        <AnalyticsResults
          data={state.data}
          activeFrameIndex={activeFrameIndex}
          onFrameSelect={onFrameSelect}
        />
      )}
    </section>
  );
}
