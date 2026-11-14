import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { cancelJob } from "../../api/client";
import {
  biologicalMovementExportUrl,
  correctBiologicalEvent,
  createEventRun,
  createMeasurementRun,
  listBiologicalEvents,
  listEventRuns,
  listMeasurementRuns,
  listMeasurementSamples,
  listMeasurementSeries,
  type BiologicalEvent,
  type MeasurementSample,
} from "./biologicalMovementApi";
import {
  getPoseIdentityIdentities,
  listPoseIdentityRuns,
} from "./poseIdentityTrackingApi";
import {
  poseLandmarkSchemaFromMetadata,
  type VideoTrackRecord,
} from "./videoApi";

import type { PoseEvidenceNavigation } from "./videoWorkspaceBridge";

interface BiologicalMovementPanelProps {
  evidence?: PoseEvidenceNavigation | null;
  projectId: string;
  videoId: string;
  tracks: VideoTrackRecord[];
  onFrameChange: (frame: number) => void;
}

const terminal = new Set(["completed", "failed", "cancelled"]);

function segments(samples: MeasurementSample[]): string[] {
  const validValues = samples
    .map((sample) => sample.physical_value ?? sample.pixel_value)
    .filter((value): value is number => value != null);
  if (samples.length === 0 || validValues.length === 0) return [];
  const times = samples.map((sample) => sample.time_s);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const minValue = Math.min(...validValues);
  const maxValue = Math.max(...validValues);
  const scaleX = (time: number) =>
    36 + ((time - minTime) / Math.max(maxTime - minTime, 1)) * 648;
  const scaleY = (value: number) =>
    210 - ((value - minValue) / Math.max(maxValue - minValue, 1)) * 176;
  const paths: string[] = [];
  let current = "";
  for (const sample of samples) {
    const value = sample.physical_value ?? sample.pixel_value;
    if (!sample.valid || value == null) {
      if (current) paths.push(current);
      current = "";
      continue;
    }
    current += `${current ? " L" : "M"} ${scaleX(sample.time_s)} ${scaleY(value)}`;
  }
  if (current) paths.push(current);
  return paths;
}

function eventFrame(event: BiologicalEvent): number {
  return event.peak_frame ?? event.start_frame;
}

export function BiologicalMovementPanel({
  projectId,
  videoId,
  tracks,
  onFrameChange,
  evidence,
}: BiologicalMovementPanelProps) {
  const queryClient = useQueryClient();
  const [identityRunId, setIdentityRunId] = useState(
    evidence?.identityRunId ?? "",
  );
  const [identityId, setIdentityId] = useState(
    evidence?.animalIdentityId ?? "",
  );
  const [verificationMode, setVerificationMode] = useState<
    "exploratory" | "scientific"
  >("scientific");
  const [kind, setKind] = useState<"distance" | "angle">("distance");
  const [landmarkIds, setLandmarkIds] = useState(["", "", ""]);
  const [measurementRunId, setMeasurementRunId] = useState(
    evidence?.measurementRunId ?? "",
  );
  const [seriesId, setSeriesId] = useState(evidence?.measurementSeriesId ?? "");
  const [eventRunId, setEventRunId] = useState(evidence?.eventRunId ?? "");
  const [openThreshold, setOpenThreshold] = useState("6");
  const [closeThreshold, setCloseThreshold] = useState("3");
  const [selectedEventId, setSelectedEventId] = useState(
    evidence?.eventRevisionId ?? "",
  );
  const [startFrame, setStartFrame] = useState("");
  const [endFrame, setEndFrame] = useState("");
  const [reason, setReason] = useState("Scientist review");
  const [message, setMessage] = useState<string | null>(null);

  const landmarkOptions = useMemo(() => {
    const schema = tracks
      .map((track) => poseLandmarkSchemaFromMetadata(track.metadata_json))
      .find((item) => item?.landmarks?.length);
    return schema?.landmarks ?? [];
  }, [tracks]);
  useEffect(() => {
    if (landmarkOptions.length >= 2 && !landmarkIds[0]) {
      setLandmarkIds([
        landmarkOptions[0].id,
        landmarkOptions[1].id,
        landmarkOptions[2]?.id ?? landmarkOptions[1].id,
      ]);
    }
  }, [landmarkIds, landmarkOptions]);

  const identityRunsQuery = useQuery({
    queryKey: ["pose-identity-runs", projectId],
    queryFn: ({ signal }) => listPoseIdentityRuns(projectId, signal),
    refetchInterval: 2000,
  });
  const identityRuns = (identityRunsQuery.data ?? []).filter(
    (run) => run.video_id === videoId && run.status === "completed",
  );
  useEffect(() => {
    if (!identityRunId && identityRuns[0]) setIdentityRunId(identityRuns[0].id);
  }, [identityRunId, identityRuns]);
  const identityRun = identityRuns.find((run) => run.id === identityRunId);
  const identitiesQuery = useQuery({
    queryKey: ["pose-identity-identities", identityRunId],
    queryFn: ({ signal }) => getPoseIdentityIdentities(identityRunId, signal),
    enabled: Boolean(identityRunId),
  });
  const identities = identitiesQuery.data ?? [];
  useEffect(() => {
    if (
      identitiesQuery.data &&
      !identities.some((identity) => identity.id === identityId)
    ) {
      setIdentityId(identities[0]?.id ?? "");
    }
  }, [identities, identitiesQuery.data, identityId]);

  const runsQuery = useQuery({
    queryKey: ["pose-measurement-runs", projectId],
    queryFn: ({ signal }) => listMeasurementRuns(projectId, signal),
    refetchInterval: 1500,
  });
  const measurementRuns = (runsQuery.data ?? []).filter(
    (run) => run.video_id === videoId,
  );
  useEffect(() => {
    if (!measurementRunId && measurementRuns[0])
      setMeasurementRunId(measurementRuns[0].id);
  }, [measurementRunId, measurementRuns]);
  const measurementRun = measurementRuns.find(
    (run) => run.id === measurementRunId,
  );

  const seriesQuery = useQuery({
    queryKey: ["pose-measurement-series", measurementRunId],
    queryFn: ({ signal }) => listMeasurementSeries(measurementRunId, signal),
    enabled: Boolean(
      measurementRunId && measurementRun?.status === "completed",
    ),
  });
  const series = (seriesQuery.data ?? []).filter(
    (item) => !identityId || item.animal_identity_id === identityId,
  );
  useEffect(() => {
    if (seriesQuery.data && !series.some((item) => item.id === seriesId))
      setSeriesId(series[0]?.id ?? "");
  }, [series, seriesQuery.data, seriesId]);
  const selectedSeries = series.find((item) => item.id === seriesId);
  const samplesQuery = useQuery({
    queryKey: ["pose-measurement-samples", seriesId],
    queryFn: ({ signal }) => listMeasurementSamples(seriesId, signal),
    enabled: Boolean(seriesId),
  });
  const samples = samplesQuery.data ?? [];

  const eventRunsQuery = useQuery({
    queryKey: ["pose-event-runs", projectId],
    queryFn: ({ signal }) => listEventRuns(projectId, signal),
    refetchInterval: 1500,
  });
  const eventRuns = (eventRunsQuery.data ?? []).filter(
    (run) => run.measurement_run_id === measurementRunId,
  );
  useEffect(() => {
    if (eventRunsQuery.data && !eventRuns.some((run) => run.id === eventRunId))
      setEventRunId(eventRuns[0]?.id ?? "");
  }, [eventRunId, eventRuns, eventRunsQuery.data]);
  const eventRun = eventRuns.find((run) => run.id === eventRunId);
  const eventsQuery = useQuery({
    queryKey: ["pose-biological-events", eventRunId],
    queryFn: ({ signal }) => listBiologicalEvents(eventRunId, false, signal),
    enabled: Boolean(eventRunId && eventRun?.status === "completed"),
  });
  const historyQuery = useQuery({
    queryKey: ["pose-biological-event-history", eventRunId],
    queryFn: ({ signal }) => listBiologicalEvents(eventRunId, true, signal),
    enabled: Boolean(eventRunId && eventRun?.status === "completed"),
  });
  const events = (eventsQuery.data ?? []).filter(
    (event) => !seriesId || event.measurement_series_id === seriesId,
  );
  const linkedHistoricalEvent = historyQuery.data?.find(
    (event) => event.id === evidence?.eventRevisionId && !event.is_current,
  );
  const selectedEvent =
    events.find((event) => event.id === selectedEventId) ?? events[0];
  useEffect(() => {
    if (
      eventsQuery.data &&
      !events.some((event) => event.id === selectedEventId)
    ) {
      setSelectedEventId(events[0]?.id ?? "");
    }
  }, [events, eventsQuery.data, selectedEventId]);
  useEffect(() => {
    if (selectedEvent) {
      setStartFrame(String(selectedEvent.start_frame));
      setEndFrame(
        selectedEvent.end_frame == null ? "" : String(selectedEvent.end_frame),
      );
    }
  }, [selectedEvent]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["pose-measurement-runs", projectId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-measurement-series", measurementRunId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-measurement-samples", seriesId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-event-runs", projectId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-biological-events", eventRunId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-biological-event-history", eventRunId],
      }),
    ]);
  };

  const measureMutation = useMutation({
    mutationFn: async () => {
      if (!identityRun || !identityId)
        throw new Error("Select a reviewed animal identity");
      const required = kind === "angle" ? 3 : 2;
      const selected = landmarkIds.slice(0, required);
      if (selected.some((id) => !id) || new Set(selected).size !== required) {
        throw new Error(`Select ${required} distinct stable landmarks`);
      }
      return createMeasurementRun(projectId, {
        video_id: videoId,
        source_identity_run_id: identityRun.id,
        source_identity_run_revision: identityRun.revision,
        identity_ids: [identityId],
        definitions: [
          {
            id: `${kind}-${selected.join("-")}`,
            name: `Custom ${kind}`,
            kind,
            landmark_ids: selected,
          },
        ],
        maximum_gap_s: 0.25,
        verification_mode: verificationMode,
      });
    },
    onSuccess: (job) => {
      const runId = job.result_json?.run_id;
      if (runId) setMeasurementRunId(runId);
      setMessage("Measurement job queued.");
      void refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });
  const eventMutation = useMutation({
    mutationFn: () => {
      if (!measurementRun || !selectedSeries)
        throw new Error("Select a completed series");
      const open = Number(openThreshold);
      const close = Number(closeThreshold);
      if (!Number.isFinite(open) || !Number.isFinite(close) || open <= close) {
        throw new Error("Open threshold must be greater than close threshold");
      }
      return createEventRun(projectId, {
        measurement_run_id: measurementRun.id,
        cycles: [
          {
            measurement_series_id: selectedSeries.id,
            open_threshold: open,
            close_threshold: close,
            maximum_gap_s: 0.25,
          },
        ],
      });
    },
    onSuccess: (job) => {
      const runId = job.result_json?.run_id;
      if (runId) setEventRunId(runId);
      setMessage("Event-detection job queued.");
      void refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });
  const reviewMutation = useMutation({
    mutationFn: (
      action: "confirm" | "reject" | "adjust_boundaries" | "remove",
    ) => {
      if (!selectedEvent) throw new Error("Select an event candidate");
      if (action === "confirm" && selectedEvent.cycle_state !== "complete") {
        throw new Error("Partial cycles cannot be confirmed");
      }
      if (action === "adjust_boundaries") {
        const start = Number(startFrame);
        const end = Number(endFrame);
        if (
          !Number.isInteger(start) ||
          !Number.isInteger(end) ||
          start < 0 ||
          end < start
        ) {
          throw new Error(
            "Event boundaries require integer frames with end at or after start",
          );
        }
      }
      return correctBiologicalEvent(selectedEvent.id, {
        action,
        ...(action === "adjust_boundaries"
          ? { start_frame: Number(startFrame), end_frame: Number(endFrame) }
          : {}),
        reason,
        actor: "local_user",
      });
    },
    onSuccess: () => {
      setMessage("Append-only event revision saved.");
      void refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  const chartPaths = segments(samples);
  const completeConfirmed = events.filter(
    (event) =>
      event.cycle_state === "complete" && event.review_state === "confirmed",
  ).length;
  const confirmedAmplitudes = events
    .filter(
      (event) =>
        event.cycle_state === "complete" &&
        event.review_state === "confirmed" &&
        event.amplitude !== null,
    )
    .map((event) => event.amplitude as number);
  const cycleConfiguration = (
    Array.isArray(eventRun?.configuration_json.cycles)
      ? eventRun.configuration_json.cycles
      : []
  ).find(
    (value): value is Record<string, unknown> =>
      typeof value === "object" &&
      value !== null &&
      value.measurement_series_id === selectedSeries?.id,
  );
  const maximumGapSeconds =
    typeof cycleConfiguration?.maximum_gap_s === "number"
      ? cycleConfiguration.maximum_gap_s
      : 0.25;
  const validSamples = samples.filter(
    (sample) =>
      sample.valid &&
      (sample.pixel_value !== null || sample.physical_value !== null),
  );
  const evaluatedDuration = validSamples
    .slice(1)
    .reduce((total, sample, index) => {
      const delta = sample.time_s - validSamples[index].time_s;
      return total + (delta > 0 && delta <= maximumGapSeconds ? delta : 0);
    }, 0);
  const confirmedFrequency =
    evaluatedDuration > 0 ? completeConfirmed / evaluatedDuration : null;
  const meanConfirmedAmplitude = confirmedAmplitudes.length
    ? confirmedAmplitudes.reduce((total, value) => total + value, 0) /
      confirmedAmplitudes.length
    : null;

  return (
    <section
      className="management-card"
      aria-label="Biological movement analysis"
    >
      <p className="eyebrow">ReefPose Phase 5</p>
      <h3>Biological movement</h3>
      <p className="muted">
        Explore anatomical signals, then explicitly review event candidates.
        Partial or unreviewed cycles are never reported as confirmed
        observations.
      </p>
      <div className="field-grid compact-grid">
        <label>
          Result mode
          <select
            value={verificationMode}
            onChange={(event) =>
              setVerificationMode(
                event.target.value as "exploratory" | "scientific",
              )
            }
          >
            <option value="scientific">Scientist-reviewed result</option>
            <option value="exploratory">Exploratory measurement</option>
          </select>
        </label>
        {verificationMode === "scientific" && (
          <p className="muted">
            Scientific eligibility is validated from every selected current
            identity observation when calculation starts.
          </p>
        )}
        <label>
          Reviewed identity run
          <select
            value={identityRunId}
            onChange={(event) => setIdentityRunId(event.target.value)}
          >
            <option value="">Select run</option>
            {identityRuns.map((run) => (
              <option key={run.id} value={run.id}>
                {run.id.slice(0, 8)} · revision {run.revision}
              </option>
            ))}
          </select>
        </label>
        <label>
          Individual
          <select
            value={identityId}
            onChange={(event) => setIdentityId(event.target.value)}
          >
            <option value="">Select individual</option>
            {identities.map((identity) => (
              <option key={identity.id} value={identity.id}>
                {identity.display_name ?? identity.stable_identity_key} ·{" "}
                {identity.verification_state}
              </option>
            ))}
          </select>
        </label>
        <label>
          Formula
          <select
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as "distance" | "angle")
            }
          >
            <option value="distance">Distance</option>
            <option value="angle">Joint angle</option>
          </select>
        </label>
        {Array.from({ length: kind === "angle" ? 3 : 2 }, (_, index) => (
          <label key={index}>
            Landmark {index + 1}
            <select
              value={landmarkIds[index]}
              onChange={(event) =>
                setLandmarkIds((current) =>
                  current.map((id, item) =>
                    item === index ? event.target.value : id,
                  ),
                )
              }
            >
              <option value="">Select landmark</option>
              {landmarkOptions.map((landmark) => (
                <option key={landmark.id} value={landmark.id}>
                  {landmark.name} · {landmark.id}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {verificationMode === "scientific" &&
        identities.length === 0 &&
        identityRunId && (
          <p role="alert">
            No scientist-reviewed identities are available in this run.
          </p>
        )}
      <div className="button-row">
        <button
          type="button"
          onClick={() => measureMutation.mutate()}
          disabled={measureMutation.isPending}
        >
          Calculate measurements
        </button>
        {measurementRun?.source_job_id &&
          !terminal.has(measurementRun.status) && (
            <button
              type="button"
              className="secondary-button"
              onClick={() =>
                void cancelJob(measurementRun.source_job_id!).then(refresh)
              }
            >
              Cancel measurement
            </button>
          )}
      </div>
      {measurementRun && (
        <p className="muted" data-testid="measurement-status">
          Measurement: {measurementRun.status} ·{" "}
          {measurementRun.verification_state}
          {typeof measurementRun.progress_json.stage === "string"
            ? ` · ${measurementRun.progress_json.stage}`
            : ""}
        </p>
      )}
      {measurementRuns.length > 0 && (
        <label>
          Saved measurement run
          <select
            value={measurementRunId}
            onChange={(event) => setMeasurementRunId(event.target.value)}
          >
            {measurementRuns.map((run) => (
              <option key={run.id} value={run.id}>
                {run.id.slice(0, 8)} · {run.status}
              </option>
            ))}
          </select>
        </label>
      )}
      {series.length > 0 && (
        <label>
          Measurement series
          <select
            value={seriesId}
            onChange={(event) => setSeriesId(event.target.value)}
          >
            {series.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name} · {item.physical_unit ?? item.pixel_unit}
              </option>
            ))}
          </select>
        </label>
      )}

      {selectedSeries && (
        <div>
          <h4>{selectedSeries.display_name} time series</h4>
          <svg
            viewBox="0 0 720 240"
            role="img"
            aria-label="Anatomical measurement time series"
            style={{ width: "100%", maxHeight: 280 }}
          >
            <rect
              x="36"
              y="24"
              width="648"
              height="186"
              fill="none"
              stroke="currentColor"
              opacity="0.25"
            />
            {chartPaths.map((path, index) => (
              <path
                key={index}
                d={path}
                fill="none"
                stroke="var(--accent, #22c55e)"
                strokeWidth="3"
              />
            ))}
            {samples
              .filter((sample) => !sample.valid)
              .map((sample) => (
                <line
                  key={sample.frame_index}
                  x1={
                    36 +
                    (sample.frame_index /
                      Math.max(samples.at(-1)?.frame_index ?? 1, 1)) *
                      648
                  }
                  x2={
                    36 +
                    (sample.frame_index /
                      Math.max(samples.at(-1)?.frame_index ?? 1, 1)) *
                      648
                  }
                  y1="24"
                  y2="210"
                  stroke="#f59e0b"
                  strokeDasharray="4 4"
                >
                  <title>{sample.quality_flags_json.join(", ")}</title>
                </line>
              ))}
            {events.map((event) => (
              <line
                key={event.id}
                x1={
                  36 +
                  (eventFrame(event) /
                    Math.max(samples.at(-1)?.frame_index ?? 1, 1)) *
                    648
                }
                x2={
                  36 +
                  (eventFrame(event) /
                    Math.max(samples.at(-1)?.frame_index ?? 1, 1)) *
                    648
                }
                y1="24"
                y2="210"
                stroke={
                  event.review_state === "confirmed" &&
                  event.cycle_state === "complete"
                    ? "#22c55e"
                    : "#ef4444"
                }
                strokeWidth="2"
              >
                <title>
                  {event.cycle_state} · {event.review_state}
                </title>
              </line>
            ))}
          </svg>
          <p className="muted">
            Unit: {selectedSeries.physical_unit ?? selectedSeries.pixel_unit}.
            Orange gaps are invalid/missing observations.
          </p>
        </div>
      )}

      <div className="field-grid compact-grid">
        <label>
          Open threshold
          <input
            value={openThreshold}
            onChange={(event) => setOpenThreshold(event.target.value)}
            inputMode="decimal"
          />
        </label>
        <label>
          Close threshold
          <input
            value={closeThreshold}
            onChange={(event) => setCloseThreshold(event.target.value)}
            inputMode="decimal"
          />
        </label>
      </div>
      <div className="button-row">
        <button
          type="button"
          onClick={() => eventMutation.mutate()}
          disabled={!selectedSeries || eventMutation.isPending}
        >
          Detect cycles
        </button>
        {eventRun?.source_job_id && !terminal.has(eventRun.status) && (
          <button
            type="button"
            className="secondary-button"
            onClick={() =>
              void cancelJob(eventRun.source_job_id!).then(refresh)
            }
          >
            Cancel detection
          </button>
        )}
      </div>
      {eventRun && (
        <p className="muted" data-testid="event-status">
          Detection: {eventRun.status}
          {typeof eventRun.progress_json.stage === "string"
            ? ` · ${eventRun.progress_json.stage}`
            : ""}
          . Confirmed complete cycles: {completeConfirmed}.
          {` Evaluated duration: ${evaluatedDuration.toFixed(3)} s.`}
          {` Confirmed frequency: ${confirmedFrequency?.toFixed(3) ?? "not available"} Hz.`}
          {` Mean confirmed amplitude: ${meanConfirmedAmplitude?.toFixed(3) ?? "not available"}.`}
        </p>
      )}
      {eventRuns.length > 0 && (
        <label>
          Saved event run
          <select
            value={eventRunId}
            onChange={(event) => setEventRunId(event.target.value)}
          >
            {eventRuns.map((run) => (
              <option key={run.id} value={run.id}>
                {run.id.slice(0, 8)} · {run.status}
              </option>
            ))}
          </select>
        </label>
      )}

      {linkedHistoricalEvent && (
        <p role="status">
          Linked historical event revision {linkedHistoricalEvent.revision} ·
          frames {linkedHistoricalEvent.start_frame}–
          {linkedHistoricalEvent.end_frame ?? "…"} ·{" "}
          {linkedHistoricalEvent.review_state}
        </p>
      )}
      {events.length > 0 && (
        <div className="field-grid compact-grid">
          <label>
            Event candidate
            <select
              value={selectedEventId}
              onChange={(event) => setSelectedEventId(event.target.value)}
            >
              {events.map((event) => (
                <option key={event.id} value={event.id}>
                  Frames {event.start_frame}–{event.end_frame ?? "…"} ·{" "}
                  {event.cycle_state} · {event.review_state}
                </option>
              ))}
            </select>
          </label>
          <label>
            Start frame
            <input
              value={startFrame}
              onChange={(event) => setStartFrame(event.target.value)}
              inputMode="numeric"
            />
          </label>
          <label>
            End frame
            <input
              value={endFrame}
              onChange={(event) => setEndFrame(event.target.value)}
              inputMode="numeric"
            />
          </label>
          <label>
            Review reason
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <div className="button-row">
            <button
              type="button"
              onClick={() =>
                selectedEvent && onFrameChange(eventFrame(selectedEvent))
              }
            >
              Go to event frame
            </button>
            <button
              type="button"
              onClick={() => reviewMutation.mutate("confirm")}
              disabled={
                !selectedEvent || selectedEvent.cycle_state !== "complete"
              }
            >
              Confirm complete
            </button>
            <button
              type="button"
              onClick={() => reviewMutation.mutate("reject")}
              disabled={!selectedEvent}
            >
              Reject
            </button>
            <button
              type="button"
              onClick={() => reviewMutation.mutate("adjust_boundaries")}
              disabled={!selectedEvent || !endFrame}
            >
              Save boundaries
            </button>
          </div>
        </div>
      )}
      {(historyQuery.data?.length ?? 0) > 0 && (
        <details>
          <summary>
            Event revision history ({historyQuery.data?.length})
          </summary>
          <ul>
            {historyQuery.data?.map((event) => (
              <li key={event.id}>
                {event.event_series_id.slice(0, 8)} r{event.revision}:{" "}
                {event.cycle_state}, {event.review_state}, frames{" "}
                {event.start_frame}–{event.end_frame ?? "…"}
              </li>
            ))}
          </ul>
        </details>
      )}
      {eventRunId && (
        <div className="button-row">
          <a href={biologicalMovementExportUrl(eventRunId, "json")}>
            Reviewed JSON
          </a>
          <a href={biologicalMovementExportUrl(eventRunId, "csv")}>
            Reviewed CSV package
          </a>
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
