import { useState } from "react";
import {
  createResultsPackage,
  resultsPackageDownloadUrl,
  type ResultsPackageOptions,
  type ResultsPackageResult,
  type TrainingRun,
} from "../../api/client";

const defaults: ResultsPackageOptions = {
  include_excel: true,
  include_machine_data: true,
  include_native_artifacts: true,
  include_logs: true,
  checkpoint_mode: "best",
};

export function ResultsPackageDialog({
  run,
  onClose,
}: {
  run: TrainingRun;
  onClose: () => void;
}) {
  const [options, setOptions] = useState(defaults);
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<ResultsPackageResult | null>(null);
  const tuning = Boolean(
    run.tuning_config.mode && run.tuning_config.mode !== "disabled",
  );

  async function exportPackage() {
    setError("");
    setStage("Preparing workbook, data, artifacts, checksums, and validation…");
    try {
      const created = await createResultsPackage(run.id, options);
      setResult(created);
      setStage("Complete and verified");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Results Package export failed",
      );
      setStage("");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="system-card results-package-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="results-package-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">Scientific export</p>
            <h4 id="results-package-title">Export Results Package</h4>
            <span>
              {tuning ? "Tuning" : "Training"} run · {run.run_name}
            </span>
          </div>
          <button
            type="button"
            className="ghost-button"
            onClick={onClose}
            aria-label="Close export dialog"
          >
            Close
          </button>
        </div>
        <fieldset disabled={Boolean(stage) && !result}>
          <legend>Include</legend>
          {(
            [
              ["include_excel", "Excel workbook"],
              ["include_machine_data", "CSV, JSON, and YAML data"],
              ["include_native_artifacts", "Native provider artifacts"],
              ["include_logs", "Logs and diagnostics"],
            ] as const
          ).map(([key, label]) => (
            <label className="checkbox-row" key={key}>
              <input
                type="checkbox"
                checked={options[key]}
                onChange={(event) =>
                  setOptions((current) => ({
                    ...current,
                    [key]: event.target.checked,
                  }))
                }
              />
              {label}
            </label>
          ))}
          <label>
            Model checkpoints
            <select
              value={options.checkpoint_mode}
              onChange={(event) =>
                setOptions((current) => ({
                  ...current,
                  checkpoint_mode: event.target
                    .value as ResultsPackageOptions["checkpoint_mode"],
                }))
              }
            >
              <option value="best">Best only</option>
              <option value="best_and_last">Best + Last</option>
              {tuning && (
                <option value="retained">
                  All retained tuning checkpoints
                </option>
              )}
              <option value="none">None</option>
            </select>
          </label>
        </fieldset>
        <p className="system-subtle">
          Provenance, manifest, checksums, and package verification are always
          included.
        </p>
        {stage && <p role="status">{stage}</p>}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {result && (
          <div className="editor-message success">
            <strong>{result.archive_name}</strong>
            <p>
              {(result.archive_size_bytes / 1024 / 1024).toFixed(2)} MB ·
              SHA-256 inventory verified
            </p>
            <a
              className="primary-button"
              href={resultsPackageDownloadUrl(result.download_url)}
            >
              Download Results Package
            </a>
            {result.warnings.length > 0 && (
              <details>
                <summary>{result.warnings.length} package warnings</summary>
                <ul>
                  {result.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
        {!result && (
          <div className="image-card-actions">
            <button
              type="button"
              onClick={() => void exportPackage()}
              disabled={Boolean(stage)}
            >
              Export Results Package
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
