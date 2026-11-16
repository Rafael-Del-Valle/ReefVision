import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { cancelJob, getJob, retryJob } from "../../api/client";
import {
  beginTemporalRun,
  freezeTemporalDataset,
  getTemporalDatasets,
  getTemporalFrames,
  getTemporalRuns,
  reviewTemporalFrames,
  type TemporalCorrection,
  type TemporalDatasetRequest,
  type TemporalFrame,
  type TemporalReviewSource,
  type TemporalRunRequest,
} from "./temporalReefPoseApi";
import {
  temporalFieldsIssue,
  TemporalReefPoseFields,
} from "./TemporalReefPoseFields";

const operations = [
  ["dataset", "Freeze a sequence dataset"],
  ["training", "Train a temporal checkpoint"],
  ["inference", "Refine frame-model poses"],
  ["evaluation", "Compare frame and temporal predictions"],
] as const;
type Operation = (typeof operations)[number][0];
type Config = Record<string, unknown>;
const active = (status?: string) =>
  ["queued", "running", "pending", "cancel_requested"].includes(status ?? "");
const pointText = (x: number | null, y: number | null) =>
  x === null || y === null ? "Missing" : `${x.toFixed(2)}, ${y.toFixed(2)}`;
const empty: Record<Operation, Config> = {
  dataset: { name: "", sources: [] },
  training: {
    name: "",
    window_length: 9,
    context_mode: "centered",
    epochs: 20,
    batch_size: 32,
    device: "auto",
  },
  inference: { source: {}, device: "auto", chunk_size: 128 },
  evaluation: { device: "auto", chunk_size: 128 },
};

function FrameReview({
  frame,
  choice,
  onChoice,
  onFrame,
  corrections,
  onCorrect,
}: {
  frame: TemporalFrame;
  choice: TemporalReviewSource | undefined;
  onChoice: (value: TemporalReviewSource | undefined) => void;
  onFrame: (frame: number) => void;
  corrections: TemporalCorrection[];
  onCorrect: (value: TemporalCorrection[]) => void;
}) {
  const framePoints = frame.frame_points ?? [];
  const refinedPoints = frame.refined_points.filter((point) => point !== null);
  const landmarks = new Set(
    [...framePoints, ...refinedPoints].map((point) => point.landmark_id),
  );
  const locations = (points: typeof framePoints, id: string) => {
    const value = points.find((point) => point.landmark_id === id);
    return value
      ? `${pointText(value.x, value.y)} · ${value.visibility}`
      : "Missing";
  };
  return (
    <details>
      <summary>
        Frame {frame.frame_index} · {frame.timestamp_seconds.toFixed(3)} s{" "}
        {frame.review_source ? `· reviewed: ${frame.review_source}` : ""}
      </summary>
      <p>
        Future context {frame.future_frames} frames ·{" "}
        {frame.future_seconds.toFixed(3)} s.
      </p>
      <button type="button" onClick={() => onFrame(frame.frame_index)}>
        Show source frame
      </button>
      <table aria-label={`Landmarks at frame ${frame.frame_index}`}>
        <thead>
          <tr>
            <th scope="col">Landmark</th>
            <th scope="col">Frame model (px)</th>
            <th scope="col">Temporal model (px)</th>
          </tr>
        </thead>
        <tbody>
          {[...landmarks].map((id) => (
            <tr key={id}>
              <th scope="row">{id}</th>
              <td>{locations(framePoints, id)}</td>
              <td>{locations(refinedPoints, id)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <label>
        Review decision for frame {frame.frame_index}
        <select
          value={choice ?? ""}
          onChange={(event) =>
            onChoice(
              (event.target.value || undefined) as
                TemporalReviewSource | undefined,
            )
          }
        >
          <option value="">Keep existing review</option>
          <option value="frame">Accept frame-model prediction</option>
          <option value="refined">Accept temporal prediction</option>
          <option value="rejected">Reject both predictions</option>
        </select>
      </label>
      {choice && choice !== "rejected" && (
        <details>
          <summary>Correct landmark coordinates</summary>
          {[...landmarks].map((id) => {
            const point = (
              choice === "frame" ? framePoints : refinedPoints
            ).find((item) => item.landmark_id === id);
            const correction = corrections.find(
              (item) => item.landmark_id === id,
            );
            const set = (axis: "x" | "y", value: number) => {
              if (!Number.isFinite(value)) return;
              onCorrect([
                ...corrections.filter((item) => item.landmark_id !== id),
                {
                  landmark_id: id,
                  x: correction?.x ?? point?.x ?? 0,
                  y: correction?.y ?? point?.y ?? 0,
                  [axis]: value,
                },
              ]);
            };
            return (
              <div className="button-row" key={id}>
                <label>
                  {id} X (px)
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={correction?.x ?? point?.x ?? ""}
                    onChange={(event) => set("x", event.target.valueAsNumber)}
                  />
                </label>
                <label>
                  {id} Y (px)
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={correction?.y ?? point?.y ?? ""}
                    onChange={(event) => set("y", event.target.valueAsNumber)}
                  />
                </label>
                {correction && (
                  <button
                    type="button"
                    onClick={() =>
                      onCorrect(
                        corrections.filter((item) => item.landmark_id !== id),
                      )
                    }
                  >
                    Clear {id} correction
                  </button>
                )}
              </div>
            );
          })}
        </details>
      )}
    </details>
  );
}

export function TemporalReefPosePanel({
  projectId,
  videoId,
  onFrameChange,
  onReviewed,
}: {
  projectId: string;
  videoId?: string;
  onFrameChange?: (frame: number) => void;
  onReviewed?: (identityRunId: string, identityId: string) => void;
}) {
  const cache = useQueryClient();
  const [operation, setOperation] = useState<Operation>("dataset");
  const [drafts, setDrafts] = useState(empty);
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const [choices, setChoices] = useState<Record<number, TemporalReviewSource>>(
    {},
  );
  const [corrections, setCorrections] = useState<
    Record<number, TemporalCorrection[]>
  >({});
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const values = drafts[operation];
  const key = ["temporal-reefpose", projectId] as const;
  const runs = useQuery({
    queryKey: [...key, "runs"],
    queryFn: ({ signal }) => getTemporalRuns(projectId, signal),
    refetchInterval: (query) =>
      query.state.data?.some((row) => active(row.status)) ? 1500 : false,
  });
  const datasets = useQuery({
    queryKey: [...key, "datasets"],
    queryFn: ({ signal }) => getTemporalDatasets(projectId, signal),
  });
  const run = runs.data?.find((row) => row.id === selected);
  const job = useQuery({
    queryKey: ["job", run?.job_id],
    queryFn: ({ signal }) => getJob(run?.job_id ?? "", signal),
    enabled: !!run?.job_id,
    refetchInterval: (query) =>
      active(query.state.data?.status) ? 1000 : false,
  });
  const frames = useQuery({
    queryKey: [...key, "frames", selected, offset],
    queryFn: ({ signal }) =>
      getTemporalFrames(projectId, selected, offset, signal),
    enabled: run?.kind === "inference" && run.status === "succeeded",
  });
  const submission = useMutation({
    mutationFn: async () => {
      if (operation === "dataset")
        return {
          dataset: await freezeTemporalDataset(
            projectId,
            values as TemporalDatasetRequest,
          ),
        };
      return {
        run: await beginTemporalRun(projectId, {
          kind: operation,
          ...values,
        } as TemporalRunRequest),
      };
    },
    onSuccess: (data) => {
      if (data.run) {
        cache.setQueryData(
          [...key, "runs"],
          (
            previous: Awaited<ReturnType<typeof getTemporalRuns>> | undefined,
          ) => [
            data.run,
            ...(previous ?? []).filter((row) => row.id !== data.run.id),
          ],
        );
        openRun(data.run.id);
      } else if (data.dataset) {
        setDrafts((current) => ({
          ...current,
          training: { ...current.training, dataset_id: data.dataset.id },
        }));
        setOperation("training");
      }
      void cache.invalidateQueries({ queryKey: key });
    },
  });
  const review = useMutation({
    mutationFn: () => {
      if (!run || !confirmed)
        throw new Error("Review confirmation is required.");
      return reviewTemporalFrames(projectId, run.id, {
        base_revision: run.review_revision ?? 0,
        confirmed: true,
        note: note.trim() || undefined,
        frames: Object.entries(choices).map(([frame, source]) => ({
          frame_index: Number(frame),
          source,
          corrections:
            source === "rejected" ? [] : (corrections[Number(frame)] ?? []),
        })),
      });
    },
    onSuccess: () => {
      setChoices({});
      setCorrections({});
      setConfirmed(false);
      setNote("");
      void cache.invalidateQueries({ queryKey: key });
      void cache.invalidateQueries({
        queryKey: ["pose-identity-runs", projectId],
      });
    },
  });
  const jobAction = useMutation({
    mutationFn: (action: "cancel" | "retry") => {
      if (!run?.job_id)
        throw new Error("Choose a saved run with a background job.");
      return action === "cancel" ? cancelJob(run.job_id) : retryJob(run.job_id);
    },
    onSuccess: (data) => {
      void cache.invalidateQueries({ queryKey: key });
      void cache.invalidateQueries({ queryKey: ["job", data.id] });
    },
  });
  function openRun(id: string) {
    setSelected(id);
    setOffset(0);
    setChoices({});
    setCorrections({});
    setConfirmed(false);
    setNote("");
    review.reset();
  }
  const issue = temporalFieldsIssue(operation, values);
  const status = job.data?.status ?? run?.status;
  const completedTraining = run?.kind === "training" && status === "succeeded";
  useEffect(() => {
    if (!completedTraining) return;
    void cache.invalidateQueries({
      queryKey: ["temporal-reefpose", projectId, "inputs"],
    });
    void cache.invalidateQueries({
      queryKey: ["model_hub_bootstrap", projectId],
    });
  }, [cache, completedTraining, projectId]);
  return (
    <section className="management-card" aria-label="Native temporal ReefPose">
      <h3>Native temporal ReefPose</h3>
      <p>
        Use reviewed targets to train a refiner for a particular frame
        checkpoint. Frame and refined predictions remain separate until each
        review decision is saved.
      </p>
      <label>
        Operation
        <select
          value={operation}
          onChange={(event) => setOperation(event.target.value as Operation)}
        >
          {operations.map(([id, label]) => (
            <option value={id} key={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!issue) submission.mutate();
        }}
      >
        <TemporalReefPoseFields
          key={operation}
          projectId={projectId}
          kind={operation}
          videoId={videoId}
          values={values}
          onChange={(value) =>
            setDrafts((current) => ({ ...current, [operation]: value }))
          }
        />
        {issue && <p>{issue}</p>}
        <button type="submit" disabled={!!issue || submission.isPending}>
          {operations.find((row) => row[0] === operation)?.[1]}
        </button>
      </form>
      {datasets.data?.length ? (
        <details>
          <summary>{datasets.data.length} frozen temporal datasets</summary>
          <ul>
            {datasets.data.map((row) => (
              <li key={row.id}>
                {row.name}
                {row.source_count !== undefined
                  ? ` · ${row.source_count} sequences`
                  : ""}
                {row.manifest_sha256 && (
                  <>
                    {" "}
                    · <code>{row.manifest_sha256.slice(0, 12)}</code>
                  </>
                )}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <label>
        Saved temporal runs
        <select
          value={selected}
          onChange={(event) => openRun(event.target.value)}
        >
          <option value="">Choose a saved run</option>
          {runs.data?.map((row) => (
            <option value={row.id} key={row.id}>
              {row.kind} · {row.status} · {row.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      {[
        runs.error,
        datasets.error,
        job.error,
        submission.error,
        review.error,
        jobAction.error,
        frames.error,
      ]
        .filter(Boolean)
        .map((error, index) => (
          <p key={index} role="alert">
            {error?.message}
          </p>
        ))}
      {run && (
        <>
          {run.source_stale && (
            <p role="alert">
              The source track or identity changed. The saved predictions remain
              available for inspection. Run refinement on the current source
              before reviewing again.
            </p>
          )}
          <p role="status">
            {status}{" "}
            {job.data?.progress_total
              ? `· ${job.data.progress_current} of ${job.data.progress_total}`
              : ""}
          </p>
          {(job.data?.error_message || run.error) && (
            <p role="alert">{job.data?.error_message || run.error}</p>
          )}
          {run.job_id && active(status) && (
            <button
              type="button"
              disabled={jobAction.isPending}
              onClick={() => jobAction.mutate("cancel")}
            >
              Cancel temporal job
            </button>
          )}
          {run.job_id &&
            ["failed", "cancelled", "canceled"].includes(status ?? "") && (
              <button
                type="button"
                disabled={jobAction.isPending}
                onClick={() => jobAction.mutate("retry")}
              >
                Resume or retry temporal job
              </button>
            )}
          {run.result && (
            <details open>
              <summary>Temporal result and provenance</summary>
              <pre>{JSON.stringify(run.result, null, 2)}</pre>
            </details>
          )}
        </>
      )}
      {frames.data && (
        <>
          <h4>Review frame and refined poses</h4>
          <p>
            Inspect coordinates in source pixels. Only the frames you explicitly
            accept are written to the reviewed identity revision.
          </p>
          {frames.data.items.map((frame) => (
            <FrameReview
              key={frame.frame_index}
              frame={frame}
              choice={choices[frame.frame_index]}
              corrections={corrections[frame.frame_index] ?? []}
              onCorrect={(values) => {
                setCorrections((current) => ({
                  ...current,
                  [frame.frame_index]: values,
                }));
                setConfirmed(false);
              }}
              onFrame={onFrameChange ?? (() => {})}
              onChoice={(source) => {
                setChoices((current) => {
                  const next = { ...current };
                  if (source) next[frame.frame_index] = source;
                  else delete next[frame.frame_index];
                  return next;
                });
                setCorrections((current) => ({
                  ...current,
                  [frame.frame_index]: [],
                }));
                setConfirmed(false);
              }}
            />
          ))}
          <div className="button-row">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              Previous frames
            </button>
            <button
              type="button"
              disabled={offset + 25 >= frames.data.total}
              onClick={() => setOffset(offset + 25)}
            >
              More frames
            </button>
          </div>
          <label>
            Review note
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!Object.keys(choices).length}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I confirmed these pose choices against the recording
          </label>
          <button
            type="button"
            onClick={() => review.mutate()}
            disabled={!confirmed || review.isPending || run?.source_stale}
          >
            Save pose review revision
          </button>
          {review.data && (
            <p role="status">
              Review revision {review.data.revision} accepted{" "}
              {review.data.accepted_frame_count} frames.{" "}
              {onReviewed && !review.data.source_stale && (
                <button
                  type="button"
                  onClick={() =>
                    onReviewed(
                      review.data.identity_run_id,
                      review.data.identity_id,
                    )
                  }
                >
                  Open in biological measurements
                </button>
              )}
            </p>
          )}
        </>
      )}
    </section>
  );
}
