import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { getRuntimeContext, openDesktopTrainingConsole } from "../../runtime";

import {
  cancelTrainingRun,
  getTrainingRuns,
  type TrainingRun,
} from "../../api/client";
import {
  trainingRunIsActive,
  trainingRunsContainActive,
} from "../../features/training/trainingRunState";

function statusLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function metricLabel(value: string): string {
  return value.replaceAll("/", " ").replaceAll("_", " ");
}

function isPlausibleMetricObservation(
  key: string,
  value: unknown,
): value is number {
  if (typeof value !== "number" || !Number.isFinite(value)) return false;
  // Standard YOLO component losses are nonnegative. Corrupt live samples
  // must not be presented as scientific measurements. Do not impose that
  // constraint on deliberately signed custom objectives or other metrics.
  return (
    value >= 0 || !/^(?:train|val)\/(?:box|cls|dfl|seg|mask)_loss$/i.test(key)
  );
}

// Standard training-loss aliases are semantically identical even when a
// provider changes capitalization between epoch history and run summaries.
// Keep other metric names intact so arbitrary signed objectives retain their
// original scientific identity.
function canonicalTrainingLossKey(key: string): string {
  return /^(?:train|val)\/(?:box|cls|dfl|seg|mask)_loss$/i.test(key)
    ? key.toLowerCase()
    : key;
}

function metricEntries(run: TrainingRun): Array<[string, number, string]> {
  // Training summaries can lag behind per-epoch history. Prefer the last
  // finite observed loss for live box/cls/dfl reporting, while keeping the
  // summary authoritative for non-training metrics such as validation mAP.
  // Show the persisted source, and flag stale epoch samples as older evidence.
  const latest = new Map<string, { value: number; provenance: string }>();
  const histories = new Map<string, unknown[]>();
  for (const [key, values] of Object.entries(run.metrics_history ?? {})) {
    if (!Array.isArray(values)) continue;
    const canonicalKey = canonicalTrainingLossKey(key);
    histories.set(canonicalKey, values);
    // An in-progress epoch can append a missing or non-finite sample before
    // the next loss is available. Retain the last real observation instead
    // of making the box/cls/dfl metric disappear from the live monitor.
    for (let index = values.length - 1; index >= 0; index -= 1) {
      const value = values[index];
      if (isPlausibleMetricObservation(key, value)) {
        const source = `history entry ${index + 1}/${values.length}`;
        const prior = index < values.length - 1 ? "; prior sample" : "";
        latest.set(canonicalKey, {
          value,
          provenance: `${source}${prior}; epoch association unverified`,
        });
        break;
      }
    }
  }
  for (const [key, value] of Object.entries(run.metrics ?? {})) {
    if (isPlausibleMetricObservation(key, value)) {
      const canonicalKey = canonicalTrainingLossKey(key);
      if (!canonicalKey.startsWith("train/") || !latest.has(canonicalKey)) {
        const history = histories.get(canonicalKey);
        let source = "summary";
        if (latest.has(canonicalKey)) {
          source = "summary; history also available";
        } else if (Array.isArray(history) && history.length > 0) {
          source = "summary fallback; history unavailable";
        }
        latest.set(canonicalKey, {
          value,
          provenance: `${source}; epoch association unverified`,
        });
      }
    }
  }

  const preferred = [
    "train/box_loss",
    "train/cls_loss",
    "train/dfl_loss",
    "train/seg_loss",
    "train/loss",
    "metrics/mAP50(B)",
    "metrics/mAP50(M)",
    "metrics/mAP50-95(B)",
    "metrics/mAP50-95(M)",
  ];
  const priority = (key: string) => {
    const index = preferred.indexOf(key);
    return index < 0 ? preferred.length : index;
  };
  return [...latest.entries()]
    .sort(([left], [right]) => priority(left) - priority(right))
    .slice(0, 5)
    .map(([key, metric]): [string, number, string] => [
      key,
      metric.value,
      metric.provenance,
    ]);
}

function metricValue(value: number): string {
  // A real low-magnitude loss must never be rounded into an observed zero.
  // Preserve the sign and a few significant digits in the read-only UI;
  // persisted training metrics and their provenance remain untouched.
  if (value !== 0 && Math.abs(value) < 0.00005) {
    return value.toExponential(3).replace(/\.?0+e/, "e");
  }
  if (Math.abs(value) >= 100) {
    return value.toFixed(1);
  }

  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

export function ProjectTrainingMonitor({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [openingRunId, setOpeningRunId] = useState<string | null>(null);
  // React state updates are batched; block rapid duplicate clicks synchronously
  // so one run never launches multiple external PowerShell monitors.
  const consoleOpening = useRef(false);
  const [terminalError, setTerminalError] = useState<string | null>(null);
  const showPowerShell = getRuntimeContext().desktopMode;

  async function openConsole(runId: string) {
    if (consoleOpening.current) return;
    consoleOpening.current = true;
    setOpeningRunId(runId);
    setTerminalError(null);
    try {
      await openDesktopTrainingConsole(runId);
    } catch (error) {
      setTerminalError(error instanceof Error ? error.message : String(error));
    } finally {
      consoleOpening.current = false;
      setOpeningRunId(null);
    }
  }

  const runsQuery = useQuery({
    queryKey: ["training_runs", projectId],
    queryFn: ({ signal }) => getTrainingRuns(projectId, signal),
    refetchOnMount: "always",
    refetchInterval: (query) =>
      query.state.status === "error" ||
      trainingRunsContainActive(query.state.data as TrainingRun[] | undefined)
        ? 2000
        : 5000, // Discover runs started in another window while idle.
  });

  const cancelMutation = useMutation({
    mutationFn: (runId: string) => cancelTrainingRun(runId),
    onSuccess: async (updatedRun) => {
      // A status request started before cancellation may return an older
      // active snapshot. Discard it before applying the canonical response.
      await queryClient.cancelQueries({
        queryKey: ["training_runs", projectId],
        exact: true,
      });
      queryClient.setQueryData<TrainingRun[]>(
        ["training_runs", projectId],
        (current) =>
          current?.map((run) =>
            run.id === updatedRun.id ? updatedRun : run,
          ) ?? [updatedRun],
      );
    },
  });

  const runs = useMemo(
    () =>
      [...(runsQuery.data ?? [])].sort(
        (left, right) =>
          new Date(right.created_at).getTime() -
          new Date(left.created_at).getTime(),
      ),
    [runsQuery.data],
  );

  const activeRuns = runs.filter(trainingRunIsActive);
  let activityLabel =
    activeRuns.length > 0 ? `${activeRuns.length} active` : "No active runs";
  if (runsQuery.isPending) activityLabel = "Checking training status…";
  if (runsQuery.isError) activityLabel = "Training status unavailable";

  const visibleRuns = [
    ...activeRuns,
    ...runs.filter((run) => !trainingRunIsActive(run)),
  ]
    .filter(
      (run, index, all) =>
        all.findIndex((candidate) => candidate.id === run.id) === index,
    )
    .slice(0, 4);

  return (
    <section
      className="rv-inspector-card rv-training-monitor"
      aria-label="Training monitor"
    >
      <div className="rv-inspector-card-heading">
        <strong>Training monitor</strong>
        <span
          className={
            !runsQuery.isError && activeRuns.length > 0
              ? "training-active"
              : undefined
          }
        >
          {activityLabel}
        </span>
      </div>

      <p>
        Monitor canonical project training runs without leaving the current
        training workflow. Launch configuration, preflight, tuning, experiments,
        and model registration remain in the main Training workspace.
      </p>

      {runsQuery.isPending && (
        <p className="annotation-helper">Loading training runs…</p>
      )}

      {runsQuery.error && (
        <p className="form-error" role="alert">
          Training runs could not be loaded: {runsQuery.error.message}
          {visibleRuns.length > 0 &&
            " Showing last known observations; current status is unverified."}
        </p>
      )}

      {!runsQuery.isPending && !runsQuery.error && visibleRuns.length === 0 && (
        <div className="rv-inspector-empty-control">
          <strong>No training runs yet</strong>
          <p>
            Configure a versioned dataset and launch the first run from the main
            Training workspace.
          </p>
        </div>
      )}

      {visibleRuns.length > 0 && (
        <div className="rv-training-monitor-list">
          {visibleRuns.map((run) => {
            const active = trainingRunIsActive(run);
            const canCancel =
              !runsQuery.isError && active && run.status !== "cancel_requested";
            const metrics = metricEntries(run);

            return (
              <article
                key={run.id}
                className="rv-training-monitor-run"
                data-training-status={run.status}
              >
                <div className="rv-training-monitor-run-heading">
                  <div>
                    <strong>{run.run_name}</strong>
                    <small>
                      {run.provider_id} · {run.architecture}
                    </small>
                  </div>

                  <span className={active ? "active" : undefined}>
                    {statusLabel(run.status)}
                  </span>
                </div>

                <div className="rv-training-monitor-meta">
                  <span>{statusLabel(run.stage)}</span>
                  <span>{run.task}</span>
                  <span>{run.device}</span>
                </div>

                <div className="rv-training-monitor-progress">
                  <div>
                    <span>Progress</span>
                    <strong>
                      {run.progress_epoch}/{run.progress_total_epochs}
                    </strong>
                  </div>

                  <progress
                    value={Math.min(
                      run.progress_epoch,
                      Math.max(run.progress_total_epochs, 1),
                    )}
                    max={Math.max(run.progress_total_epochs, 1)}
                    aria-label={`${run.run_name} progress`}
                  />
                </div>

                {metrics.length > 0 && (
                  <dl className="rv-training-monitor-metrics">
                    {metrics.map(([key, value, provenance]) => (
                      <div key={key}>
                        <dt>{metricLabel(key)}</dt>
                        <dd>
                          <span>{metricValue(value)}</span>
                          {" · "}
                          <small className="rv-training-monitor-metric-source">
                            {provenance}
                          </small>
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}

                <div className="rv-training-monitor-provenance">
                  <span>Dataset</span>
                  <code>
                    {run.dataset_manifest_sha256
                      ? run.dataset_manifest_sha256.slice(0, 10)
                      : "unavailable"}
                  </code>
                </div>

                {run.warnings.length > 0 && (
                  <p className="annotation-helper">
                    {run.warnings.length} training{" "}
                    {run.warnings.length === 1 ? "warning" : "warnings"}
                  </p>
                )}

                {run.error_message && (
                  <p className="form-error">{run.error_message}</p>
                )}

                {showPowerShell && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={openingRunId !== null}
                    onClick={() => void openConsole(run.id)}
                  >
                    {openingRunId === run.id
                      ? "Opening Console…"
                      : "Open Training Console"}
                  </button>
                )}

                {canCancel && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={
                      cancelMutation.isPending &&
                      cancelMutation.variables === run.id
                    }
                    onClick={() => {
                      if (
                        window.confirm(
                          `Cancel training run ${run.run_name}? Safely written artifacts will be retained.`,
                        )
                      ) {
                        cancelMutation.mutate(run.id);
                      }
                    }}
                  >
                    {cancelMutation.isPending &&
                    cancelMutation.variables === run.id
                      ? "Cancelling…"
                      : "Cancel run"}
                  </button>
                )}
              </article>
            );
          })}
        </div>
      )}

      {terminalError && (
        <p className="form-error" role="alert">
          {terminalError}
        </p>
      )}

      {cancelMutation.error && (
        <p className="form-error" role="alert">
          {cancelMutation.error.message}
        </p>
      )}

      <button
        type="button"
        className="secondary"
        disabled={runsQuery.isFetching}
        onClick={() => void runsQuery.refetch()}
      >
        {runsQuery.isFetching ? "Refreshing…" : "Refresh runs"}
      </button>

      <div className="rv-inference-boundary">
        <strong>Model artifact boundary</strong>
        <p>
          Training progress, metrics, and checkpoints are reproducible model
          records. A completed checkpoint does not convert predictions into
          scientist-verified annotations.
        </p>
      </div>
    </section>
  );
}
