import {
  trainingArtifactUrl,
  type TrainingArtifact,
  type TrainingRun,
  type TuningResults,
  type TuningTrial,
} from "../../api/client";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { TuningDashboard } from "./TuningDashboard";
import { ResultsPackageDialog } from "./ResultsPackageDialog";
import { useState } from "react";
import { getRuntimeContext, openDesktopTrainingConsole } from "../../runtime";

function history(run: TrainingRun): Record<string, number[]> {
  return Object.fromEntries(
    Object.entries(run.metrics_history).filter(
      (entry): entry is [string, number[]] =>
        Array.isArray(entry[1]) &&
        entry[1].every((value) => typeof value === "number"),
    ),
  );
}

function metricLabel(key: string): string {
  return key.replaceAll("/", " ").replaceAll("_", " ");
}

function preferredMetric(run: TrainingRun): [string, number[]] | null {
  const entries = Object.entries(history(run));
  const preferences =
    run.task === "classify"
      ? ["metrics/accuracy_top1", "metrics/accuracy_top5", "val/accuracy"]
      : run.task === "segment"
        ? ["metrics/mAP50-95(M)", "metrics/mAP50(M)", "metrics/mAP50-95(B)"]
        : ["metrics/mAP50-95(B)", "metrics/mAP50(B)", "metrics/precision(B)"];
  return (
    preferences
      .map((key) => entries.find(([candidate]) => candidate === key))
      .find(Boolean) ??
    entries.find(([key]) => /mAP|accuracy|precision/i.test(key)) ??
    null
  );
}

function bestEpoch(
  run: TrainingRun,
): { epoch: number; key: string; value: number } | null {
  const metric = preferredMetric(run);
  if (!metric || metric[1].length === 0) return null;
  let bestIndex = 0;
  metric[1].forEach((value, index) => {
    if (value > metric[1][bestIndex]) bestIndex = index;
  });
  const epochs = history(run).epoch;
  return {
    epoch: Math.round(epochs?.[bestIndex] ?? bestIndex + 1),
    key: metric[0],
    value: metric[1][bestIndex],
  };
}

function MetricChart({ label, values }: { label: string; values: number[] }) {
  if (values.length < 2) return null;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = maximum - minimum || 1;
  const points = values
    .map(
      (value, index) =>
        `${(index / (values.length - 1)) * 100},${40 - ((value - minimum) / range) * 36}`,
    )
    .join(" ");
  return (
    <figure className="training-metric-chart">
      <figcaption>{metricLabel(label)}</figcaption>
      <svg
        viewBox="0 0 100 44"
        role="img"
        aria-label={`${metricLabel(label)} across ${values.length} epochs`}
      >
        <polyline points={points} />
      </svg>
      <small>
        Latest {values.at(-1)?.toFixed(4)} · {values.length} epochs
      </small>
    </figure>
  );
}

export function TrainingRunDetail({
  run,
  registeredName,
  registering,
  onCancel,
  onRegister,
  onApplyBest,
}: {
  run: TrainingRun;
  registeredName?: string;
  registering: boolean;
  onCancel: () => void;
  onRegister: () => void;
  onApplyBest?: (trial: TuningTrial) => void;
}) {
  const [exportOpen, setExportOpen] = useState(false);
  const [consoleOpening, setConsoleOpening] = useState(false);
  const [consoleError, setConsoleError] = useState<string | null>(null);
  const desktopConsoleAvailable = getRuntimeContext().desktopMode;

  async function handleOpenTrainingConsole() {
    setConsoleOpening(true);
    setConsoleError(null);
    try {
      await openDesktopTrainingConsole(run.id);
    } catch (error) {
      setConsoleError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsoleOpening(false);
    }
  }
  const metricHistory = history(run);
  const best = bestEpoch(run);
  const artifacts = Array.isArray(run.artifact_manifest.artifacts)
    ? (run.artifact_manifest.artifacts as TrainingArtifact[])
    : [];
  const tuningResults = run.artifact_manifest.tuning_results as
    TuningResults | null | undefined;
  const nativeRows = Array.isArray(run.artifact_manifest.native_results_rows)
    ? (run.artifact_manifest.native_results_rows as Array<
        Record<string, unknown>
      >)
    : [];
  const bestCheckpoint = artifacts.find((item) => item.name === "best.pt");
  const lastCheckpoint = artifacts.find((item) => item.name === "last.pt");
  const active = [
    "queued",
    "preflight",
    "preparing_dataset",
    "training",
    "tuning",
    "running",
    "cancel_requested",
  ].includes(run.status);
  const progress =
    run.progress_total_epochs > 0
      ? Math.min(100, (run.progress_epoch / run.progress_total_epochs) * 100)
      : 0;

  return (
    <article
      className="system-card training-run-detail"
      aria-label={`Training run ${run.run_name}`}
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Run detail</p>
          <h4>{run.run_name}</h4>
          <span>
            {run.architecture} · {run.task}
          </span>
        </div>
        <StatusBadge status={run.status} />
      </div>
      <div className="training-progress-summary">
        <strong>
          {run.tuning_config.mode && run.tuning_config.mode !== "disabled"
            ? "Trial"
            : "Epoch"}{" "}
          {run.progress_epoch} of {run.progress_total_epochs || "—"}
        </strong>
        <progress
          value={progress}
          max="100"
          aria-label={`${run.run_name} training progress`}
        />
        <span>Stage: {run.stage.replaceAll("_", " ")}</span>
      </div>
      {run.error_message && (
        <div className="editor-message error">
          <strong>Training failed</strong>
          <p>{run.error_message}</p>
        </div>
      )}
      <div className="training-result-facts">
        {best && (
          <div>
            <span>Best epoch</span>
            <strong>{best.epoch}</strong>
            <small>
              {metricLabel(best.key)} {best.value.toFixed(4)}
            </small>
          </div>
        )}
        <div>
          <span>Dataset snapshot</span>
          <strong>{run.dataset_manifest_sha256.slice(0, 12)}…</strong>
          <small>{run.dataset_version_id ?? "Unavailable"}</small>
        </div>
        <div>
          <span>Initialization</span>
          <strong>{run.initial_checkpoint_source.replaceAll("_", " ")}</strong>
          <small>
            {run.resolved_model_checksum?.slice(0, 12) ??
              "No checkpoint checksum"}
          </small>
        </div>
      </div>
      <div className="training-chart-grid">
        {Object.entries(metricHistory)
          .filter(([key]) => !/^epoch$|^time$/i.test(key))
          .map(([key, values]) => (
            <MetricChart key={key} label={key} values={values} />
          ))}
      </div>
      {tuningResults?.trials?.length ? (
        <TuningDashboard results={tuningResults} onApply={onApplyBest} />
      ) : (
        <section>
          <h5>Per-epoch metrics</h5>
          {nativeRows.length ? (
            <div className="training-table-wrap">
              <table>
                <thead>
                  <tr>
                    {Object.keys(nativeRows[0]).map((key) => (
                      <th key={key}>{key}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {nativeRows.map((row, index) => (
                    <tr key={index}>
                      {Object.keys(nativeRows[0]).map((key) => (
                        <td key={key}>
                          {row[key] == null ? "—" : String(row[key])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="system-subtle">
              The provider did not preserve a per-epoch results table.
            </p>
          )}
        </section>
      )}
      <section>
        <h5>Checkpoints</h5>
        <div className="training-artifact-grid">
          {[bestCheckpoint, lastCheckpoint]
            .filter((item): item is TrainingArtifact => Boolean(item))
            .map((item) => (
              <a
                key={item.name}
                className="system-record-card"
                href={trainingArtifactUrl(run.id, artifacts.indexOf(item))}
                target="_blank"
                rel="noreferrer"
              >
                <strong>
                  {item.name === "best.pt"
                    ? "Best checkpoint"
                    : "Last checkpoint"}
                </strong>
                <span>
                  {Math.round(item.size_bytes / 1024).toLocaleString()} KB
                </span>
              </a>
            ))}
        </div>
      </section>
      <section>
        <h5>Artifacts</h5>
        {artifacts.length === 0 ? (
          <p className="system-subtle">
            No cataloged artifacts are available for this run.
          </p>
        ) : (
          <div className="training-artifact-grid">
            {artifacts.map((artifact, index) => (
              <a
                key={`${artifact.relative_path}-${index}`}
                className="system-record-card"
                href={trainingArtifactUrl(run.id, index)}
                target="_blank"
                rel="noreferrer"
              >
                <strong>{artifact.name}</strong>
                <span>
                  {artifact.category} ·{" "}
                  {Math.round(artifact.size_bytes / 1024).toLocaleString()} KB
                </span>
                {artifact.previewable && <small>Preview available</small>}
                {artifact.previewable &&
                  /\.(png|jpg|jpeg)$/i.test(artifact.name) && (
                    <img
                      src={trainingArtifactUrl(run.id, index)}
                      alt={`${artifact.name}, native Ultralytics artifact`}
                      loading="lazy"
                    />
                  )}
              </a>
            ))}
          </div>
        )}
      </section>
      <details>
        <summary>Configuration and provenance</summary>
        <dl className="training-provenance-list">
          <div>
            <dt>Run ID</dt>
            <dd>{run.id}</dd>
          </div>
          <div>
            <dt>Dataset version</dt>
            <dd>{run.dataset_version_id ?? "Unavailable"}</dd>
          </div>
          <div>
            <dt>Split checksum</dt>
            <dd>{run.split_manifest_sha256}</dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd>{run.provider_id}</dd>
          </div>
          <div>
            <dt>Device / precision</dt>
            <dd>
              {run.device} / {run.precision}
            </dd>
          </div>
          <div>
            <dt>Seed</dt>
            <dd>{run.random_seed ?? "Provider default"}</dd>
          </div>
        </dl>
        <pre className="json-block">
          {JSON.stringify(run.draft_snapshot, null, 2)}
        </pre>
      </details>
      <div className="image-card-actions">
        {desktopConsoleAvailable && (
          <button
            type="button"
            className="secondary"
            disabled={consoleOpening}
            onClick={() => void handleOpenTrainingConsole()}
          >
            {consoleOpening ? "Opening Console…" : "Open Training Console"}
          </button>
        )}
        {!active && (
          <button type="button" onClick={() => setExportOpen(true)}>
            Export Results Package
          </button>
        )}
        {active && (
          <button type="button" className="danger-ghost" onClick={onCancel}>
            Cancel training
          </button>
        )}
        {run.status === "completed" &&
          (registeredName ? (
            <span>Best model registered as {registeredName}</span>
          ) : (
            <button
              type="button"
              disabled={registering || !run.result_checkpoint_path}
              onClick={onRegister}
            >
              {registering
                ? "Registering…"
                : `Register best ${run.task === "segment" ? "segmenter" : "detector"}`}
            </button>
          ))}
      </div>
      {consoleError && (
        <p className="form-error" role="alert">
          {consoleError}
        </p>
      )}
      {exportOpen && (
        <ResultsPackageDialog run={run} onClose={() => setExportOpen(false)} />
      )}
    </article>
  );
}
