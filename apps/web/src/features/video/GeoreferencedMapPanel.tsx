import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import {
  getGeoreferencedObservation,
  getVideoGeoreferencedObservations,
  type GeoReferencedObservationSummary,
} from "./videoGeoreferencedObservationsApi";

import {
  createGeoMapState,
  geoMapReducer,
  groupGeoObservationsByTrack,
} from "./videoGeoreferencedObservationsState";

import { activeObservationForFrame } from "./videoMapSynchronization";

interface GeoreferencedMapPanelProps {
  videoId: string;
  activeFrameIndex?: number | null;
  onFrameSelect?: (frameIndex: number, frameTimeSeconds: number) => void;
}

interface ProjectedObservation {
  observation: GeoReferencedObservationSummary;
  x: number;
  y: number;
}

const MAP_WIDTH = 640;
const MAP_HEIGHT = 360;
const MAP_PADDING = 36;

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Unable to load georeferenced observations.";
}

function formatCoordinate(value: number): string {
  return value.toFixed(6);
}

function formatSeconds(value: number): string {
  return `${value.toFixed(3)} s`;
}

function projectObservations(
  observations: GeoReferencedObservationSummary[],
): ProjectedObservation[] {
  if (observations.length === 0) {
    return [];
  }

  const latitudes = observations.map((item) => item.location.latitude_deg);

  const longitudes = observations.map((item) => item.location.longitude_deg);

  const minimumLatitude = Math.min(...latitudes);

  const maximumLatitude = Math.max(...latitudes);

  const minimumLongitude = Math.min(...longitudes);

  const maximumLongitude = Math.max(...longitudes);

  const latitudeSpan = Math.max(maximumLatitude - minimumLatitude, 0.000001);

  const longitudeSpan = Math.max(maximumLongitude - minimumLongitude, 0.000001);

  return observations.map((observation) => {
    const normalizedX =
      (observation.location.longitude_deg - minimumLongitude) / longitudeSpan;

    const normalizedY =
      (observation.location.latitude_deg - minimumLatitude) / latitudeSpan;

    return {
      observation,
      x: MAP_PADDING + normalizedX * (MAP_WIDTH - MAP_PADDING * 2),
      y:
        MAP_HEIGHT - MAP_PADDING - normalizedY * (MAP_HEIGHT - MAP_PADDING * 2),
    };
  });
}

export function GeoreferencedMapPanel({
  videoId,
  activeFrameIndex = null,
  onFrameSelect,
}: GeoreferencedMapPanelProps) {
  const [state, dispatch] = useReducer(
    geoMapReducer,
    undefined,
    createGeoMapState,
  );

  const collectionAbortRef = useRef<AbortController | null>(null);

  const detailAbortRef = useRef<AbortController | null>(null);

  const requestIdRef = useRef(0);

  const loadCollection = useCallback(async () => {
    collectionAbortRef.current?.abort();

    const controller = new AbortController();

    collectionAbortRef.current = controller;

    dispatch({
      type: "collection-loading",
    });

    try {
      const response = await getVideoGeoreferencedObservations(
        videoId,
        {},
        controller.signal,
      );

      if (controller.signal.aborted) {
        return;
      }

      dispatch({
        type: "collection-success",
        observations: response.items,
      });
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }

      dispatch({
        type: "collection-error",
        error: errorMessage(error),
      });
    }
  }, [videoId]);

  useEffect(() => {
    void loadCollection();

    return () => {
      collectionAbortRef.current?.abort();
      detailAbortRef.current?.abort();
    };
  }, [loadCollection]);

  const projected = useMemo(
    () => projectObservations(state.observations),
    [state.observations],
  );

  const projectedById = useMemo(
    () => new Map(projected.map((item) => [item.observation.id, item])),
    [projected],
  );

  const trackGroups = useMemo(
    () => groupGeoObservationsByTrack(state.observations),
    [state.observations],
  );

  const activeObservation = useMemo(
    () => activeObservationForFrame(state.observations, activeFrameIndex),
    [activeFrameIndex, state.observations],
  );

  const activeTrackId = activeObservation?.track_id ?? null;

  const selectedSummary = useMemo(
    () =>
      state.observations.find(
        (item) => item.id === state.selectedObservationId,
      ) ?? null,
    [state.observations, state.selectedObservationId],
  );

  const selectObservation = useCallback(
    async (observation: GeoReferencedObservationSummary) => {
      detailAbortRef.current?.abort();

      requestIdRef.current += 1;

      const requestId = requestIdRef.current;

      dispatch({
        type: "select-observation",
        observationId: observation.id,
        requestId,
      });

      onFrameSelect?.(observation.frame_index, observation.frame_time_s);

      if (state.detailCache.has(observation.id)) {
        return;
      }

      const controller = new AbortController();

      detailAbortRef.current = controller;

      try {
        const detail = await getGeoreferencedObservation(
          observation.id,
          controller.signal,
        );

        if (controller.signal.aborted) {
          return;
        }

        dispatch({
          type: "detail-success",
          observationId: observation.id,
          requestId,
          observation: detail,
        });
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }

        dispatch({
          type: "detail-error",
          observationId: observation.id,
          requestId,
          error: errorMessage(error),
        });
      }
    },
    [onFrameSelect, state.detailCache],
  );

  const hasObservations = state.observations.length > 0;

  const initialLoading =
    state.collectionStatus === "loading" && !hasObservations;

  const initialError = state.collectionStatus === "error" && !hasObservations;

  const successfulEmpty =
    state.collectionStatus === "success" && !hasObservations;

  return (
    <section className="management-card" data-testid="georeferenced-map-panel">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <p className="eyebrow">Georeferencing</p>

          <h3>Geographic observations</h3>

          <p className="annotation-helper">
            Persisted geographic positions derived from the source video.
            Coordinates shown here come directly from the backend georeferencing
            result.
          </p>
        </div>

        <button
          type="button"
          className="secondary"
          disabled={state.collectionStatus === "loading"}
          onClick={() => {
            void loadCollection();
          }}
        >
          {state.collectionStatus === "loading"
            ? "Refreshing..."
            : "Refresh map"}
        </button>
      </div>

      {initialLoading && (
        <div
          role="status"
          aria-live="polite"
          style={{
            padding: "28px 0",
          }}
        >
          Loading georeferenced observations...
        </div>
      )}

      {initialError && (
        <div
          role="alert"
          style={{
            display: "grid",
            gap: 12,
            padding: "20px 0",
          }}
        >
          <strong>Unable to load georeferenced observations.</strong>

          <span className="error-copy">{state.collectionError}</span>

          <div>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                void loadCollection();
              }}
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {successfulEmpty && (
        <div
          role="status"
          style={{
            display: "grid",
            gap: 6,
            padding: "24px 0",
          }}
        >
          <strong>No georeferenced observations</strong>

          <span className="annotation-helper">
            This video does not currently have any persisted geographic
            observations.
          </span>
        </div>
      )}

      {hasObservations && (
        <>
          {state.collectionStatus === "loading" && (
            <p className="annotation-helper" role="status">
              Refreshing geographic observations...
            </p>
          )}

          {state.collectionStatus === "error" && (
            <div
              role="alert"
              style={{
                display: "flex",
                gap: 12,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span className="error-copy">
                Could not refresh geographic observations. Existing map points
                are still shown.
              </span>

              <button
                type="button"
                className="secondary"
                onClick={() => {
                  void loadCollection();
                }}
              >
                Retry refresh
              </button>
            </div>
          )}

          <p className="annotation-helper">
            {state.observations.length.toLocaleString()} persisted observation
            {state.observations.length === 1 ? "" : "s"}
          </p>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1.6fr) minmax(240px, 1fr)",
              gap: 16,
              alignItems: "start",
            }}
          >
            <div
              style={{
                minWidth: 0,
                overflowX: "auto",
              }}
            >
              <svg
                viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
                aria-label="Georeferenced observations map"
                role="img"
                style={{
                  display: "block",
                  width: "100%",
                  minWidth: 320,
                  border: "1px solid var(--border-color, #cbd5e1)",
                  borderRadius: 8,
                  background: "var(--panel-background, #f8fafc)",
                }}
              >
                <rect
                  x={0}
                  y={0}
                  width={MAP_WIDTH}
                  height={MAP_HEIGHT}
                  fill="transparent"
                />

                {[1, 2, 3].map((division) => (
                  <g key={division}>
                    <line
                      x1={(MAP_WIDTH / 4) * division}
                      y1={0}
                      x2={(MAP_WIDTH / 4) * division}
                      y2={MAP_HEIGHT}
                      stroke="currentColor"
                      opacity={0.08}
                    />

                    <line
                      x1={0}
                      y1={(MAP_HEIGHT / 4) * division}
                      x2={MAP_WIDTH}
                      y2={(MAP_HEIGHT / 4) * division}
                      stroke="currentColor"
                      opacity={0.08}
                    />
                  </g>
                ))}

                {Array.from(trackGroups.tracked.entries()).map(
                  ([trackId, observations]) => {
                    const points = observations
                      .map((observation) => projectedById.get(observation.id))
                      .filter(
                        (item): item is ProjectedObservation =>
                          item !== undefined,
                      )
                      .map((item) => `${item.x},${item.y}`)
                      .join(" ");

                    if (observations.length < 2 || !points) {
                      return null;
                    }

                    return (
                      <polyline
                        key={trackId}
                        points={points}
                        fill="none"
                        stroke={
                          activeTrackId === trackId
                            ? "var(--accent-color, #2563eb)"
                            : "currentColor"
                        }
                        strokeWidth={activeTrackId === trackId ? 4 : 2}
                        opacity={activeTrackId === trackId ? 0.9 : 0.3}
                        vectorEffect="non-scaling-stroke"
                        data-track-id={trackId}
                        data-active-track={
                          activeTrackId === trackId ? "true" : "false"
                        }
                      />
                    );
                  },
                )}

                {projected.map(({ observation, x, y }) => {
                  const selected =
                    state.selectedObservationId === observation.id;

                  const active = activeObservation?.id === observation.id;

                  return (
                    <>
                      {active && (
                        <circle
                          cx={x}
                          cy={y}
                          r={11}
                          fill="none"
                          stroke="var(--accent-color, #2563eb)"
                          strokeWidth={4}
                          opacity={0.9}
                          vectorEffect="non-scaling-stroke"
                          pointerEvents="none"
                          data-playback-active-halo="true"
                          data-active-observation="true"
                          data-active-observation-id={observation.id}
                          data-active-track-id={observation.track_id ?? ""}
                        />
                      )}

                      <circle
                        key={observation.id}
                        cx={x}
                        cy={y}
                        r={selected ? 9 : 6}
                        fill={
                          selected
                            ? "var(--accent-color, #2563eb)"
                            : "currentColor"
                        }
                        opacity={selected ? 1 : 0.75}
                        stroke={selected ? "currentColor" : "none"}
                        strokeWidth={selected ? 2 : 0}
                        vectorEffect="non-scaling-stroke"
                        role="button"
                        tabIndex={0}
                        aria-label={`Observation at frame ${observation.frame_index}`}
                        aria-pressed={selected}
                        style={{
                          cursor: "pointer",
                        }}
                        onClick={() => {
                          void selectObservation(observation);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();

                            void selectObservation(observation);
                          }
                        }}
                      />
                    </>
                  );
                })}

                <text
                  x={12}
                  y={22}
                  fontSize={12}
                  fill="currentColor"
                  opacity={0.72}
                >
                  Geographic observation extent
                </text>

                <text
                  x={12}
                  y={MAP_HEIGHT - 10}
                  fontSize={11}
                  fill="currentColor"
                  opacity={0.6}
                >
                  Longitude →
                </text>

                <text
                  x={MAP_WIDTH - 12}
                  y={22}
                  textAnchor="end"
                  fontSize={11}
                  fill="currentColor"
                  opacity={0.6}
                >
                  Latitude ↑
                </text>
              </svg>

              <p className="annotation-helper">
                Points are plotted from persisted latitude and longitude. Lines
                connect observations that share a track ID in frame order. No
                uncertainty radius is shown unless the backend provides one in a
                later task.
              </p>
            </div>

            <aside
              aria-label="Georeferenced observation inspector"
              style={{
                minWidth: 0,
                border: "1px solid var(--border-color, #cbd5e1)",
                borderRadius: 8,
                padding: 14,
                display: "grid",
                gap: 10,
              }}
            >
              {!selectedSummary && (
                <p className="annotation-helper">
                  Select a geographic point to inspect its persisted provenance.
                </p>
              )}

              {selectedSummary && (
                <>
                  <div>
                    <p className="eyebrow">Observation</p>

                    <strong>Frame {selectedSummary.frame_index}</strong>
                  </div>

                  <dl
                    style={{
                      display: "grid",
                      gridTemplateColumns: "auto minmax(0, 1fr)",
                      columnGap: 10,
                      rowGap: 6,
                      margin: 0,
                    }}
                  >
                    <dt>Latitude</dt>
                    <dd
                      style={{
                        margin: 0,
                      }}
                    >
                      {formatCoordinate(selectedSummary.location.latitude_deg)}
                    </dd>

                    <dt>Longitude</dt>
                    <dd
                      style={{
                        margin: 0,
                      }}
                    >
                      {formatCoordinate(selectedSummary.location.longitude_deg)}
                    </dd>

                    <dt>CRS</dt>
                    <dd
                      style={{
                        margin: 0,
                      }}
                    >
                      {selectedSummary.location.crs}
                    </dd>

                    <dt>Video time</dt>
                    <dd
                      style={{
                        margin: 0,
                      }}
                    >
                      {formatSeconds(selectedSummary.frame_time_s)}
                    </dd>

                    <dt>Track</dt>
                    <dd
                      style={{
                        margin: 0,
                        overflowWrap: "anywhere",
                      }}
                    >
                      {selectedSummary.track_id ?? "Untracked"}
                    </dd>

                    <dt>Point method</dt>
                    <dd
                      style={{
                        margin: 0,
                      }}
                    >
                      {selectedSummary.representative_pixel.method}
                    </dd>

                    <dt>Uncertainty</dt>
                    <dd
                      style={{
                        margin: 0,
                      }}
                    >
                      {selectedSummary.uncertainty_available
                        ? "Available"
                        : "Unavailable"}
                    </dd>
                  </dl>

                  {state.detailStatus === "loading" && (
                    <p role="status" className="annotation-helper">
                      Loading observation details...
                    </p>
                  )}

                  {state.detailStatus === "error" && (
                    <div
                      role="alert"
                      style={{
                        display: "grid",
                        gap: 8,
                      }}
                    >
                      <span className="error-copy">
                        Unable to load observation details.
                      </span>

                      <span className="annotation-helper">
                        {state.detailError}
                      </span>

                      <div>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => {
                            void selectObservation(selectedSummary);
                          }}
                        >
                          Retry details
                        </button>
                      </div>
                    </div>
                  )}

                  {state.detailStatus === "success" &&
                    state.selectedObservation && (
                      <details>
                        <summary>Georeferencing details</summary>

                        <dl
                          style={{
                            display: "grid",
                            gridTemplateColumns: "auto minmax(0, 1fr)",
                            columnGap: 10,
                            rowGap: 6,
                            marginTop: 10,
                          }}
                        >
                          <dt>Method</dt>
                          <dd
                            style={{
                              margin: 0,
                              overflowWrap: "anywhere",
                            }}
                          >
                            {state.selectedObservation.method.name}
                          </dd>

                          <dt>Version</dt>
                          <dd
                            style={{
                              margin: 0,
                              overflowWrap: "anywhere",
                            }}
                          >
                            {state.selectedObservation.method.version}
                          </dd>

                          <dt>Calibration</dt>
                          <dd
                            style={{
                              margin: 0,
                              overflowWrap: "anywhere",
                            }}
                          >
                            {
                              state.selectedObservation.calibration
                                .calibration_id
                            }
                          </dd>

                          <dt>Calibration version</dt>
                          <dd
                            style={{
                              margin: 0,
                            }}
                          >
                            {
                              state.selectedObservation.calibration
                                .calibration_version
                            }
                          </dd>

                          <dt>Telemetry</dt>
                          <dd
                            style={{
                              margin: 0,
                              overflowWrap: "anywhere",
                            }}
                          >
                            {state.selectedObservation.telemetry.source_id}
                          </dd>

                          <dt>Sample</dt>
                          <dd
                            style={{
                              margin: 0,
                            }}
                          >
                            {state.selectedObservation.telemetry.sample_index ??
                              "Unavailable"}
                          </dd>

                          <dt>Sync delta</dt>
                          <dd
                            style={{
                              margin: 0,
                            }}
                          >
                            {state.selectedObservation.telemetry
                              .signed_time_delta_ms === null
                              ? "Unavailable"
                              : `${state.selectedObservation.telemetry.signed_time_delta_ms.toFixed(3)} ms`}
                          </dd>

                          <dt>Camera pose</dt>
                          <dd
                            style={{
                              margin: 0,
                            }}
                          >
                            yaw{" "}
                            {state.selectedObservation.pose.camera.yaw_deg ??
                              "—"}
                            , pitch{" "}
                            {state.selectedObservation.pose.camera.pitch_deg ??
                              "—"}
                            , roll{" "}
                            {state.selectedObservation.pose.camera.roll_deg ??
                              "—"}
                          </dd>

                          <dt>Platform pose</dt>
                          <dd
                            style={{
                              margin: 0,
                            }}
                          >
                            yaw{" "}
                            {state.selectedObservation.pose.platform.yaw_deg ??
                              "—"}
                            , pitch{" "}
                            {state.selectedObservation.pose.platform
                              .pitch_deg ?? "—"}
                            , roll{" "}
                            {state.selectedObservation.pose.platform.roll_deg ??
                              "—"}
                          </dd>

                          <dt>Source bbox</dt>
                          <dd
                            style={{
                              margin: 0,
                            }}
                          >
                            {state.selectedObservation.bbox.x_min},{" "}
                            {state.selectedObservation.bbox.y_min} →{" "}
                            {state.selectedObservation.bbox.x_max},{" "}
                            {state.selectedObservation.bbox.y_max}
                          </dd>

                          <dt>Pixel</dt>
                          <dd
                            style={{
                              margin: 0,
                            }}
                          >
                            {state.selectedObservation.representative_pixel.x},{" "}
                            {state.selectedObservation.representative_pixel.y}
                          </dd>

                          <dt>Created</dt>
                          <dd
                            style={{
                              margin: 0,
                              overflowWrap: "anywhere",
                            }}
                          >
                            {state.selectedObservation.created_at}
                          </dd>
                        </dl>
                      </details>
                    )}
                </>
              )}
            </aside>
          </div>
        </>
      )}
    </section>
  );
}
