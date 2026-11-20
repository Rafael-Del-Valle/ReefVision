import { useQuery } from "@tanstack/react-query";

import {
  getDatasetVersionQualityControlRuns,
  getDatasetVersions,
  getQualityControlRuns,
} from "../../api/client";

type SetParameter = (name: string, value: unknown) => void;

export function WorkflowDatasetPicker({
  projectId,
  selected,
  onSelect,
}: {
  projectId: string;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const versions = useQuery({
    queryKey: ["dataset_versions", projectId],
    queryFn: ({ signal }) => getDatasetVersions(projectId, signal),
  });
  const complete = (versions.data ?? []).filter(
    (version) =>
      version.project_id === projectId && version.status === "complete",
  );
  const unavailable =
    selected && !complete.some((version) => version.id === selected);

  return (
    <label className="workflow-parameter-field">
      <span>Frozen dataset version</span>
      <select
        value={selected}
        disabled={versions.isPending}
        onChange={(event) => onSelect(event.target.value)}
      >
        <option value="">Choose a complete version</option>
        {unavailable && (
          <option value={selected}>Saved version unavailable</option>
        )}
        {complete.map((version) => (
          <option key={version.id} value={version.id}>
            v{version.version_number} - {version.name}
          </option>
        ))}
      </select>
      {versions.isError && <small>Could not load dataset versions.</small>}
    </label>
  );
}

export function QcReviewQueueFields({
  projectId,
  datasetVersionId,
  parameters,
  onChange,
}: {
  projectId: string;
  datasetVersionId: string | null;
  parameters: Record<string, unknown>;
  onChange: SetParameter;
}) {
  // null is project scope; an empty string is an unconfigured frozen source.
  const runs = useQuery({
    queryKey: ["quality_control_runs", projectId, datasetVersionId],
    queryFn: ({ signal }) =>
      datasetVersionId === null
        ? getQualityControlRuns(projectId, signal)
        : getDatasetVersionQualityControlRuns(datasetVersionId, signal),
    enabled: datasetVersionId !== "",
  });
  const complete = (runs.data ?? []).filter(
    (run) =>
      run.project_id === projectId &&
      run.dataset_version_id === datasetVersionId &&
      run.status === "succeeded",
  );
  const sourceRun = String(parameters.source_quality_control_run_id ?? "");
  const threshold = parameters.review_below_confidence;

  return (
    <div className="workflow-parameter-grid">
      <label className="workflow-parameter-field">
        <span>Source QC run</span>
        <select
          value={sourceRun}
          disabled={runs.isPending}
          onChange={(event) =>
            onChange(
              "source_quality_control_run_id",
              event.target.value || null,
            )
          }
        >
          <option value="">Latest completed run</option>
          {sourceRun && !complete.some((run) => run.id === sourceRun) && (
            <option value={sourceRun}>Saved QC run unavailable</option>
          )}
          {complete.map((run) => (
            <option key={run.id} value={run.id}>
              {new Date(run.created_at).toLocaleString()} · {run.issue_count}{" "}
              findings
            </option>
          ))}
        </select>
        {runs.isError && <small>Could not load QC runs for this scope.</small>}
      </label>
      {(datasetVersionId === null || threshold != null) && (
        <label className="workflow-parameter-field">
          <span>Review confidence threshold (0 to 1)</span>
          <input
            type="number"
            min={0}
            max={1}
            step="any"
            value={typeof threshold === "number" ? threshold : ""}
            onChange={(event) =>
              onChange(
                "review_below_confidence",
                event.target.value === "" ? null : event.target.valueAsNumber,
              )
            }
          />
        </label>
      )}
      <p className="annotation-helper">
        {datasetVersionId === null
          ? "Priority scores are dimensionless. Observations require researcher review."
          : "Frozen datasets omit predictions. Leave confidence blank and choose the version on the connected dataset source."}
      </p>
    </div>
  );
}
