import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { cancelJob, type JobRecord } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { listPoseIdentityRuns } from "./poseIdentityTrackingApi";

type ReferenceSummary = {
  id: string;
  name: string;
  revision: number;
  data_kind: string;
  manifest_sha256: string;
};
type Reference = ReferenceSummary & {
  manifest: {
    recordings: {
      video_id: string;
      split: string;
      individuals: { id: string; species: string }[];
      annotations: { rater_id: string; adjudicates: string[] }[];
    }[];
  };
};
type Counts = {
  tp: number;
  fp: number;
  fn: number;
  f1: number | null;
  precision: number | null;
  recall: number | null;
};
type Report = {
  data_kind: string;
  result_sha256: string;
  selected_configuration_index: number;
  identity: { id_f1: number | null; conditional_id_f1?: number | null };
  pose: {
    matched_visible_count: number;
    visible_reference_count: number;
  } | null;
  sensitivity: { configuration_index: number; complete: Counts }[];
  pose_by_species: Record<
    string,
    { matched_visible_count: number; visible_reference_count: number }
  >;
  pose_by_individual: Record<
    string,
    { matched_visible_count: number; visible_reference_count: number }
  >;
  recordings: {
    video_id: string;
    fps: number;
    identity: {
      switches: {
        frame: number;
        individual_id: string;
        previous: string;
        current: string;
      }[];
    };
    measurements: {
      definition_id: string;
      individual_id: string;
      unit: string;
      bias: number | null;
      points: { mean: number; difference: number }[];
      matched_frames: number[];
    }[];
    events: {
      individual_id: string;
      label: string;
      start_s: number;
      complete?: Counts & {
        missed: string[];
        spurious: string[];
        matches: {
          reference: string;
          reference_start_s: number;
          onset_error_s: number;
          offset_error_s: number | null;
        }[];
      };
      reference_events?: { id: string; start: number }[];
      predicted_events?: { id: string; start: number }[];
    }[];
  }[];
  inter_observer: {
    measurements: {
      definition_id: string;
      unit: string;
      icc_a1: number | null;
    }[];
    events: { raters: string[]; f1: number | null; count_error: number }[];
  };
};

async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : JSON.stringify(payload.detail),
    );
  }
  return payload as T;
}

function post(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function value(number: number | null): string {
  return number === null ? "Unavailable" : number.toFixed(3);
}

function AgreementPlot({
  points,
  onSelect,
}: {
  points: { mean: number; difference: number }[];
  onSelect?: (index: number) => void;
}) {
  if (!points.length) return null;
  const minX = points.reduce(
    (min, point) => Math.min(min, point.mean),
    points[0].mean,
  );
  const maxX = points.reduce((max, point) => Math.max(max, point.mean), minX);
  const maxY =
    points.reduce(
      (max, point) => Math.max(max, Math.abs(point.difference)),
      0,
    ) || 1;
  return (
    <svg
      viewBox="0 0 320 125"
      width="320"
      role="img"
      aria-label="Paired mean versus signed difference"
    >
      <line x1="30" x2="310" y1="55" y2="55" stroke="currentColor" />
      {points.map((point, i) => (
        <circle
          key={i}
          cx={35 + (270 * (point.mean - minX)) / (maxX - minX || 1)}
          cy={55 - (45 * point.difference) / maxY}
          r="2.5"
          fill="currentColor"
          tabIndex={onSelect ? 0 : undefined}
          onClick={() => onSelect?.(i)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onSelect?.(i);
          }}
        >
          <title>{`Mean ${point.mean.toFixed(3)}, difference ${point.difference.toFixed(3)}`}</title>
        </circle>
      ))}
      <text x="100" y="115" fill="currentColor" fontSize="11">
        Paired measurement mean
      </text>
    </svg>
  );
}

function SensitivityPlot({ rows }: { rows: Report["sensitivity"] }) {
  if (rows.length < 2) return null;
  return (
    <svg
      viewBox="0 0 320 110"
      width="320"
      role="img"
      aria-label="Complete event F1 by configuration"
    >
      <line x1="20" y1="90" x2="300" y2="90" stroke="currentColor" />
      {rows.map(({ configuration_index: index, complete }, position) =>
        complete.f1 === null ? null : (
          <circle
            key={index}
            cx={25 + (270 * position) / (rows.length - 1)}
            cy={90 - 70 * complete.f1}
            r="4"
            fill="currentColor"
          >
            <title>{`Configuration ${index + 1}: F1 ${value(complete.f1)}`}</title>
          </circle>
        ),
      )}
    </svg>
  );
}

export function ReefPoseValidationPanel({
  projectId,
  videoId,
  onFrameChange,
}: {
  projectId: string;
  videoId?: string;
  onFrameChange?: (frame: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [manifest, setManifest] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [split, setSplit] = useState("development");
  const [rater, setRater] = useState("");
  const [sources, setSources] = useState<Record<string, string>>({});
  const [zeroSources, setZeroSources] = useState<Record<string, string>>({});
  const [configuration, setConfiguration] = useState("[{}]");
  const [lock, setLock] = useState("");
  const [jobId, setJobId] = useState("");
  const base = `${getApiBaseUrl()}/projects/${projectId}`;
  const references = useQuery({
    queryKey: ["reefpose-references", projectId],
    enabled: open,
    queryFn: ({ signal }) =>
      json<ReferenceSummary[]>(`${base}/reefpose-references`, { signal }),
  });
  const reference = useQuery({
    queryKey: ["reefpose-reference", projectId, referenceId],
    enabled: open && !!referenceId,
    queryFn: ({ signal }) =>
      json<Reference>(`${base}/reefpose-references/${referenceId}`, { signal }),
  });
  const jobs = useQuery({
    queryKey: ["reefpose-validations", projectId],
    enabled: open,
    queryFn: ({ signal }) =>
      json<JobRecord[]>(`${base}/reefpose-validations`, { signal }),
    refetchInterval: ({ state }) =>
      state.data?.some((job) =>
        ["queued", "running", "cancel_requested"].includes(job.status),
      )
        ? 1000
        : false,
  });
  const runs = useQuery({
    queryKey: ["pose-identity-runs", projectId],
    enabled: open,
    queryFn: ({ signal }) => listPoseIdentityRuns(projectId, signal),
  });
  const freeze = useMutation({
    mutationFn: () =>
      json<Reference>(
        `${base}/reefpose-references`,
        post(JSON.parse(manifest)),
      ),
    onSuccess: (row) => {
      setReferenceId(row.id);
      void references.refetch();
    },
  });
  const recordings =
    reference.data?.manifest.recordings.filter((row) => row.split === split) ??
    [];
  const raters =
    recordings[0]?.annotations.filter((rater) =>
      recordings.every((row) =>
        row.annotations.some((item) => item.rater_id === rater.rater_id),
      ),
    ) ?? [];
  const selectedRater = raters.some((item) => item.rater_id === rater)
    ? rater
    : (raters[0]?.rater_id ?? "");
  const run = useMutation({
    mutationFn: () =>
      json<JobRecord>(
        `${base}/reefpose-validations`,
        post({
          reference_id: referenceId,
          split,
          rater_id: selectedRater,
          source_runs: Object.fromEntries(
            recordings
              .filter((row) => sources[row.video_id])
              .map((row) => [row.video_id, sources[row.video_id]]),
          ),
          zero_detection_jobs: Object.fromEntries(
            recordings
              .filter((row) => zeroSources[row.video_id])
              .map((row) => [row.video_id, zeroSources[row.video_id]]),
          ),
          ...(split === "development"
            ? { configurations: JSON.parse(configuration) }
            : { development_job_id: lock }),
        }),
      ),
    onSuccess: (job) => {
      setJobId(job.id);
      void jobs.refetch();
    },
  });
  const cancel = useMutation({
    mutationFn: cancelJob,
    onSuccess: () => void jobs.refetch(),
  });
  const current = jobs.data?.find((item) => item.id === jobId);
  const exportUrl = `${base}/reefpose-validations/${jobId}/export`;
  const report = useQuery({
    queryKey: ["reefpose-validation-report", projectId, jobId],
    enabled: open && current?.status === "succeeded",
    queryFn: ({ signal }) => json<Report>(exportUrl, { signal }),
  });
  const result = report.data;
  const counts =
    result?.sensitivity[result.selected_configuration_index]?.complete;
  const error =
    freeze.error ??
    run.error ??
    cancel.error ??
    references.error ??
    reference.error ??
    jobs.error ??
    runs.error ??
    report.error;

  return (
    <details
      className="management-card"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>ReefPose scientific validation</summary>
      {open && (
        <section aria-label="ReefPose scientific validation">
          <label>
            Independent reference manifest
            <textarea
              value={manifest}
              rows={4}
              onChange={(event) => setManifest(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!manifest.trim() || freeze.isPending}
            onClick={() => freeze.mutate()}
          >
            Freeze reference
          </button>
          <label>
            Frozen reference dataset
            <select
              value={referenceId}
              onChange={(event) => setReferenceId(event.target.value)}
            >
              <option value="">Select a reference</option>
              {references.data?.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name} · revision {row.revision} · {row.data_kind}
                </option>
              ))}
            </select>
          </label>
          {reference.data && (
            <>
              <label>
                Partition
                <select
                  value={split}
                  onChange={(event) => setSplit(event.target.value)}
                >
                  <option value="development">Development</option>
                  <option value="test">Held-out test</option>
                </select>
              </label>
              <label>
                Reference rater
                <select
                  value={selectedRater}
                  onChange={(event) => setRater(event.target.value)}
                >
                  {raters.map((row) => (
                    <option key={row.rater_id} value={row.rater_id}>
                      {row.rater_id} ·{" "}
                      {row.adjudicates.length ? "adjudicated" : "independent"}
                    </option>
                  ))}
                </select>
              </label>
              {recordings.map((row) => (
                <div key={row.video_id}>
                  <label>
                    Original identity run for{" "}
                    {row.individuals.map((item) => item.species).join(", ")} (
                    {row.video_id.slice(0, 8)})
                    <select
                      value={sources[row.video_id] ?? ""}
                      onChange={(event) => {
                        setZeroSources({ ...zeroSources, [row.video_id]: "" });
                        setSources({
                          ...sources,
                          [row.video_id]: event.target.value,
                        });
                      }}
                    >
                      <option value="">Select a completed identity run</option>
                      {runs.data
                        ?.filter(
                          (item) =>
                            item.video_id === row.video_id &&
                            item.status === "completed",
                        )
                        .map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.id}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Zero-detection tracking job ID ({row.video_id.slice(0, 8)})
                    <input
                      value={zeroSources[row.video_id] ?? ""}
                      onChange={(event) => {
                        setSources({ ...sources, [row.video_id]: "" });
                        setZeroSources({
                          ...zeroSources,
                          [row.video_id]: event.target.value.trim(),
                        });
                      }}
                    />
                  </label>
                </div>
              ))}
              {split === "development" ? (
                <label>
                  Development configurations (JSON)
                  <textarea
                    value={configuration}
                    rows={4}
                    onChange={(event) => setConfiguration(event.target.value)}
                  />
                </label>
              ) : (
                <label>
                  Development report lock
                  <select
                    value={lock}
                    onChange={(event) => setLock(event.target.value)}
                  >
                    <option value="">
                      Select completed development report
                    </option>
                    {jobs.data
                      ?.filter(
                        (job) =>
                          job.status === "succeeded" &&
                          job.result_json?.split === "development" &&
                          job.result_json.reference_id === referenceId,
                      )
                      .map((job) => (
                        <option key={job.id} value={job.id}>
                          {job.id}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              <button
                type="button"
                disabled={
                  run.isPending ||
                  !selectedRater ||
                  !recordings.length ||
                  recordings.some(
                    (row) =>
                      !sources[row.video_id] && !zeroSources[row.video_id],
                  ) ||
                  (split === "test" && !lock)
                }
                onClick={() => run.mutate()}
              >
                Run scientific validation
              </button>
            </>
          )}
          <label>
            Validation runs
            <select
              value={jobId}
              onChange={(event) => setJobId(event.target.value)}
            >
              <option value="">Select a run</option>
              {jobs.data?.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.id} · {job.status}
                </option>
              ))}
            </select>
          </label>
          {current && (
            <p role="status">
              Validation {current.status} ({current.progress_current}/
              {current.progress_total})
            </p>
          )}
          {current && ["queued", "running"].includes(current.status) && (
            <button
              type="button"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate(current.id)}
            >
              Cancel validation
            </button>
          )}
          {(error || current?.error_message) && (
            <p role="alert">{error?.message ?? current?.error_message}</p>
          )}
          {result && (
            <>
              <p>
                {result.data_kind === "synthetic"
                  ? "Synthetic engineering evidence"
                  : "Biological reference evaluation"}
              </p>
              <p>
                Report SHA-256 <code>{result.result_sha256}</code>
              </p>
              <p>
                {result.identity.id_f1 === null &&
                result.identity.conditional_id_f1 != null
                  ? `Conditional identity F1 ${value(result.identity.conditional_id_f1)}`
                  : `IDF1 ${value(result.identity.id_f1)}`}{" "}
                · Landmarks{" "}
                {result.pose
                  ? `${result.pose.matched_visible_count}/${result.pose.visible_reference_count}`
                  : "Unavailable"}
              </p>
              {counts && (
                <p>
                  Complete event precision {value(counts.precision)} · Recall{" "}
                  {value(counts.recall)} · F1 {value(counts.f1)}
                  {" · "}
                  {counts.tp} TP, {counts.fp} FP, {counts.fn} FN
                </p>
              )}
              <table>
                <caption>Threshold sensitivity</caption>
                <thead>
                  <tr>
                    <th>Configuration</th>
                    <th>F1</th>
                    <th>Missed</th>
                  </tr>
                </thead>
                <tbody>
                  {result.sensitivity.map((row) => (
                    <tr key={row.configuration_index}>
                      <td>{row.configuration_index + 1}</td>
                      <td>{value(row.complete.f1)}</td>
                      <td>{row.complete.fn}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <SensitivityPlot rows={result.sensitivity} />
              {Object.entries(result.pose_by_species).map(([species, row]) => (
                <p key={species}>
                  {species} · {row.matched_visible_count}/
                  {row.visible_reference_count} visible landmarks matched
                </p>
              ))}
              <details>
                <summary>Individual landmark coverage</summary>
                {Object.entries(result.pose_by_individual).map(([key, row]) => (
                  <p key={key}>
                    {key} · {row.matched_visible_count}/
                    {row.visible_reference_count}
                  </p>
                ))}
              </details>
              {result.inter_observer.measurements.map((row) => (
                <p key={`${row.definition_id}:${row.unit}`}>
                  Inter-observer ICC(A,1) · {row.definition_id} ({row.unit}) ·{" "}
                  {value(row.icc_a1)}
                </p>
              ))}
              {result.inter_observer.events.map((row, index) => (
                <p key={index}>
                  {row.raters.join(" / ")} · Event F1 {value(row.f1)} · Count
                  difference {row.count_error}
                </p>
              ))}
              {result.recordings.map((recording) => (
                <div key={recording.video_id}>
                  {recording.identity.switches.map((item) => (
                    <p key={`${item.individual_id}:${item.frame}`}>
                      {item.individual_id} · Identity switch {item.previous} →{" "}
                      {item.current} · frame {item.frame}
                      {onFrameChange && recording.video_id === videoId && (
                        <button
                          type="button"
                          onClick={() => onFrameChange(item.frame)}
                        >
                          Go to switch frame
                        </button>
                      )}
                    </p>
                  ))}
                  {recording.measurements.map((row) => (
                    <div
                      key={`${row.individual_id}:${row.definition_id}:${row.unit}`}
                    >
                      <p>
                        {row.individual_id} · {row.definition_id} · Bias{" "}
                        {value(row.bias)} {row.unit}
                      </p>
                      <AgreementPlot
                        points={row.points}
                        onSelect={
                          onFrameChange && recording.video_id === videoId
                            ? (index) =>
                                onFrameChange(row.matched_frames[index])
                            : undefined
                        }
                      />
                    </div>
                  ))}
                  {recording.events.map(
                    (row) =>
                      row.complete && (
                        <details
                          key={`${row.individual_id}:${row.label}:${row.start_s}`}
                        >
                          <summary>
                            {row.individual_id} · {row.label} ·{" "}
                            {row.complete.tp} TP, {row.complete.fp} FP,{" "}
                            {row.complete.fn} FN
                          </summary>
                          {row.complete.matches.map((match) => (
                            <p key={match.reference}>
                              {match.reference} · Onset error{" "}
                              {value(match.onset_error_s)} s · Offset error{" "}
                              {value(match.offset_error_s)} s
                              {onFrameChange &&
                                recording.video_id === videoId && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      onFrameChange(
                                        Math.round(
                                          match.reference_start_s *
                                            recording.fps,
                                        ),
                                      )
                                    }
                                  >
                                    Go to reference event
                                  </button>
                                )}
                            </p>
                          ))}
                          {[
                            ...(row.reference_events ?? [])
                              .filter((item) =>
                                row.complete?.missed.includes(item.id),
                              )
                              .map((item) => ({ ...item, kind: "Missed" })),
                            ...(row.predicted_events ?? [])
                              .filter((item) =>
                                row.complete?.spurious.includes(item.id),
                              )
                              .map((item) => ({
                                ...item,
                                kind: "False positive",
                              })),
                          ].map((item) => (
                            <p key={`${item.kind}:${item.id}`}>
                              {item.kind} · {item.id} · {value(item.start)} s
                              {onFrameChange &&
                                recording.video_id === videoId && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      onFrameChange(
                                        Math.round(item.start * recording.fps),
                                      )
                                    }
                                  >
                                    Go to event
                                  </button>
                                )}
                            </p>
                          ))}
                        </details>
                      ),
                  )}
                </div>
              ))}
              <a href={exportUrl}>Validation JSON</a>
              {" · "}
              <a href={`${exportUrl}?format=csv`}>Validation CSV</a>
              {" · "}
              <a href={`${exportUrl}?format=summary`}>Research summary CSV</a>
            </>
          )}
        </section>
      )}
    </details>
  );
}
