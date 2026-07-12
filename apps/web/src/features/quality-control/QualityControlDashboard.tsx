import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  acknowledgeQualityControlIssue,
  cancelQualityControlRun,
  compareQualityControlRuns,
  createDatasetVersionQualityControlRun,
  createQualityControlRun,
  dismissQualityControlIssue,
  getDatasetVersionQualityControlRuns,
  getDatasetVersions,
  getQualityControlIssues,
  getQualityControlRun,
  getQualityControlRuns,
  type Project,
  type QualityControlIssue,
  type QualityControlRuleCategory,
  type QualityControlRunRecord,
  type QualityControlThresholdConfig,
} from "../../api/client";

const ruleCategories: QualityControlRuleCategory[] = [
  "annotation_geometry",
  "annotation_semantics",
  "image_integrity",
  "predictions",
  "statistics",
  "dataset_versions",
];

const defaultThresholds: QualityControlThresholdConfig = {
  small_box_min_width_px: 6,
  small_box_min_height_px: 6,
  near_duplicate_iou_threshold: 0.9,
  same_class_overlap_iou_threshold: 0.75,
  different_class_overlap_iou_threshold: 0.8,
  boundary_touch_margin_px: 0,
  annotation_count_mad_multiplier: 3.5,
  class_imbalance_majority_ratio: 0.85,
  suspicious_bulk_acceptance_min_count: 12,
  suspicious_bulk_acceptance_window_minutes: 10,
  overlap_spatial_cell_px: 128,
};

function stringifyRecord(record: Record<string, unknown>): string {
  return JSON.stringify(record, null, 2);
}

function runLabel(run: QualityControlRunRecord): string {
  const scope = run.dataset_version_id ? "version" : "project";
  return `${run.status} | ${scope} | ${run.issue_count} issues`;
}

export function QualityControlDashboard({
  project,
  onOpenImage,
}: {
  project: Project;
  onOpenImage: (issue: QualityControlIssue) => void;
}) {
  const queryClient = useQueryClient();
  const [scopeType, setScopeType] = useState<"project" | "dataset_version">(
    "project",
  );
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [compareRunId, setCompareRunId] = useState("");
  const [issuePage, setIssuePage] = useState(1);
  const [issueSeverity, setIssueSeverity] = useState("");
  const [issueRuleId, setIssueRuleId] = useState("");
  const [issueClassId, setIssueClassId] = useState("");
  const [issueImageId, setIssueImageId] = useState("");
  const [issueStatus, setIssueStatus] = useState("");
  const [enabledCategories, setEnabledCategories] = useState<
    Record<QualityControlRuleCategory, boolean>
  >({
    annotation_geometry: true,
    annotation_semantics: true,
    image_integrity: true,
    predictions: true,
    statistics: true,
    dataset_versions: true,
  });
  const [thresholds, setThresholds] =
    useState<QualityControlThresholdConfig>(defaultThresholds);

  const versions = useQuery({
    queryKey: ["dataset_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const runs = useQuery({
    queryKey: ["quality_control_runs", project.id, scopeType, datasetVersionId],
    queryFn: ({ signal }) =>
      scopeType === "dataset_version" && datasetVersionId
        ? getDatasetVersionQualityControlRuns(datasetVersionId, signal)
        : getQualityControlRuns(project.id, signal),
  });
  const selectedRun = useQuery({
    queryKey: ["quality_control_run", selectedRunId],
    queryFn: ({ signal }) => getQualityControlRun(selectedRunId, signal),
    enabled: selectedRunId.length > 0,
    refetchInterval: (query) => {
      const run = query.state.data;
      return run &&
        ["queued", "running", "cancel_requested"].includes(run.status)
        ? 1000
        : false;
    },
  });
  const issues = useQuery({
    queryKey: [
      "quality_control_issues",
      selectedRunId,
      issuePage,
      issueSeverity,
      issueRuleId,
      issueClassId,
      issueImageId,
      issueStatus,
    ],
    queryFn: ({ signal }) =>
      getQualityControlIssues(
        selectedRunId,
        {
          page: issuePage,
          pageSize: 25,
          severity: issueSeverity || undefined,
          ruleId: issueRuleId.trim() || undefined,
          classId: issueClassId || undefined,
          imageId: issueImageId.trim() || undefined,
          status: issueStatus || undefined,
        },
        signal,
      ),
    enabled: selectedRunId.length > 0,
  });
  const comparison = useQuery({
    queryKey: ["quality_control_compare", selectedRunId, compareRunId],
    queryFn: ({ signal }) =>
      compareQualityControlRuns(selectedRunId, compareRunId, signal),
    enabled:
      selectedRunId.length > 0 &&
      compareRunId.length > 0 &&
      compareRunId !== selectedRunId,
  });

  useEffect(() => {
    if (!runs.data?.length) {
      setSelectedRunId("");
      setCompareRunId("");
      return;
    }
    if (!selectedRunId) {
      setSelectedRunId(runs.data[0].id);
      setCompareRunId(runs.data[1]?.id ?? "");
    }
  }, [runs.data, selectedRunId]);

  useEffect(() => {
    setIssuePage(1);
  }, [issueSeverity, issueRuleId, issueClassId, issueImageId, issueStatus]);

  useEffect(() => {
    if (!selectedRun.data) {
      return;
    }
    if (
      ["succeeded", "failed", "cancelled"].includes(selectedRun.data.status)
    ) {
      void queryClient.invalidateQueries({
        queryKey: [
          "quality_control_runs",
          project.id,
          scopeType,
          datasetVersionId,
        ],
      });
    }
  }, [datasetVersionId, project.id, queryClient, scopeType, selectedRun.data]);

  const createRun = useMutation({
    mutationFn: async () => {
      const payload = {
        rule_categories: ruleCategories.filter(
          (category) => enabledCategories[category],
        ),
        thresholds,
      };
      return scopeType === "dataset_version" && datasetVersionId
        ? createDatasetVersionQualityControlRun(datasetVersionId, payload)
        : createQualityControlRun(project.id, payload);
    },
    onSuccess: async (run) => {
      setSelectedRunId(run.id);
      await queryClient.invalidateQueries({
        queryKey: ["quality_control_runs", project.id],
      });
    },
  });
  const cancelRun = useMutation({
    mutationFn: (runId: string) => cancelQualityControlRun(runId),
    onSuccess: async (run) => {
      setSelectedRunId(run.id);
      await queryClient.invalidateQueries({
        queryKey: ["quality_control_runs", project.id],
      });
    },
  });
  const acknowledgeIssue = useMutation({
    mutationFn: (issueId: string) => acknowledgeQualityControlIssue(issueId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["quality_control_issues", selectedRunId],
      });
    },
  });
  const dismissIssue = useMutation({
    mutationFn: async (issueId: string) => {
      const reason = window.prompt("Dismiss reason");
      if (!reason?.trim()) {
        throw new Error("A dismissal reason is required");
      }
      return dismissQualityControlIssue(issueId, reason.trim());
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["quality_control_issues", selectedRunId],
      });
    },
  });

  const selectedVersion = useMemo(
    () =>
      versions.data?.find((version) => version.id === datasetVersionId) ?? null,
    [datasetVersionId, versions.data],
  );
  const activeRun = selectedRun.data ?? null;

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Milestone 7</p>
          <h3>Quality Control</h3>
          <span>{runs.data?.length ?? 0} historical runs</span>
        </div>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Run configuration</p>
                <h4>Start checks</h4>
              </div>
            </div>
            <label>
              Scope
              <select
                value={scopeType}
                onChange={(event) =>
                  setScopeType(
                    event.target.value as "project" | "dataset_version",
                  )
                }
              >
                <option value="project">Entire project</option>
                <option value="dataset_version">Dataset version</option>
              </select>
            </label>
            {scopeType === "dataset_version" && (
              <label>
                Dataset version
                <select
                  value={datasetVersionId}
                  onChange={(event) => setDatasetVersionId(event.target.value)}
                >
                  <option value="">Choose a version</option>
                  {versions.data?.map((version) => (
                    <option key={version.id} value={version.id}>
                      v{version.version_number} - {version.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="dashboard-grid">
              {ruleCategories.map((category) => (
                <label key={category} className="toggle-row">
                  <input
                    type="checkbox"
                    checked={enabledCategories[category]}
                    onChange={(event) =>
                      setEnabledCategories((current) => ({
                        ...current,
                        [category]: event.target.checked,
                      }))
                    }
                  />
                  {category.replaceAll("_", " ")}
                </label>
              ))}
            </div>
            <div className="dashboard-grid compact-grid">
              <label>
                Small box min width
                <input
                  type="number"
                  value={thresholds.small_box_min_width_px}
                  onChange={(event) =>
                    setThresholds((current) => ({
                      ...current,
                      small_box_min_width_px: Number(event.target.value),
                    }))
                  }
                />
              </label>
              <label>
                Small box min height
                <input
                  type="number"
                  value={thresholds.small_box_min_height_px}
                  onChange={(event) =>
                    setThresholds((current) => ({
                      ...current,
                      small_box_min_height_px: Number(event.target.value),
                    }))
                  }
                />
              </label>
              <label>
                Near duplicate IoU
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={thresholds.near_duplicate_iou_threshold}
                  onChange={(event) =>
                    setThresholds((current) => ({
                      ...current,
                      near_duplicate_iou_threshold: Number(event.target.value),
                    }))
                  }
                />
              </label>
              <label>
                Count MAD multiplier
                <input
                  type="number"
                  min="0"
                  step="0.5"
                  value={thresholds.annotation_count_mad_multiplier}
                  onChange={(event) =>
                    setThresholds((current) => ({
                      ...current,
                      annotation_count_mad_multiplier: Number(
                        event.target.value,
                      ),
                    }))
                  }
                />
              </label>
            </div>
            <div className="version-actions">
              <button
                type="button"
                disabled={
                  createRun.isPending ||
                  (scopeType === "dataset_version" && !datasetVersionId)
                }
                onClick={() => createRun.mutate()}
              >
                {createRun.isPending ? "Queueing..." : "Run quality control"}
              </button>
              {activeRun &&
                ["queued", "running", "cancel_requested"].includes(
                  activeRun.status,
                ) && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => cancelRun.mutate(activeRun.id)}
                  >
                    Cancel run
                  </button>
                )}
            </div>
            {(createRun.error || cancelRun.error) && (
              <p className="form-error">
                {(createRun.error ?? cancelRun.error)?.message}
              </p>
            )}
            {selectedVersion && (
              <p className="annotation-helper">
                Active version scope: v{selectedVersion.version_number} -{" "}
                {selectedVersion.name}
              </p>
            )}
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Run history</p>
                <h4>Historical runs</h4>
              </div>
            </div>
            <div className="version-list">
              {runs.data?.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  className={`version-card ${
                    selectedRunId === run.id ? "selected" : ""
                  }`}
                  onClick={() => setSelectedRunId(run.id)}
                >
                  <strong>{new Date(run.created_at).toLocaleString()}</strong>
                  <span>{runLabel(run)}</span>
                  <small>{run.selected_rule_ids_json.join(", ")}</small>
                </button>
              ))}
            </div>
            {runs.error && <p className="form-error">{runs.error.message}</p>}
          </div>
        </div>

        <div className="dashboard-main">
          {activeRun && (
            <div className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Selected run</p>
                  <h4>{activeRun.status}</h4>
                </div>
                <span>{activeRun.issue_count} issues</span>
              </div>
              <div className="version-preview-metrics">
                <span>
                  Created: {new Date(activeRun.created_at).toLocaleString()}
                </span>
                <span>
                  Started:{" "}
                  {activeRun.started_at
                    ? new Date(activeRun.started_at).toLocaleString()
                    : "pending"}
                </span>
                <span>
                  Completed:{" "}
                  {activeRun.completed_at
                    ? new Date(activeRun.completed_at).toLocaleString()
                    : "not complete"}
                </span>
              </div>
              {activeRun.error_message && (
                <p className="form-error">{activeRun.error_message}</p>
              )}
              <div className="dashboard-grid compact-grid">
                <label>
                  Compare against
                  <select
                    value={compareRunId}
                    onChange={(event) => setCompareRunId(event.target.value)}
                  >
                    <option value="">Choose another run</option>
                    {runs.data
                      ?.filter((run) => run.id !== activeRun.id)
                      .map((run) => (
                        <option key={run.id} value={run.id}>
                          {new Date(run.created_at).toLocaleString()}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              {comparison.data && (
                <div className="version-preview-metrics">
                  <span>Added: {comparison.data.added_count}</span>
                  <span>Resolved: {comparison.data.resolved_count}</span>
                  <span>Unchanged: {comparison.data.unchanged_count}</span>
                </div>
              )}
            </div>
          )}

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Issue filters</p>
                <h4>Diagnostic findings</h4>
              </div>
              <span>{issues.data?.total ?? 0} matches</span>
            </div>
            <div className="dashboard-grid compact-grid">
              <label>
                Severity
                <select
                  value={issueSeverity}
                  onChange={(event) => setIssueSeverity(event.target.value)}
                >
                  <option value="">All severities</option>
                  <option value="error">Error</option>
                  <option value="warning">Warning</option>
                  <option value="info">Info</option>
                </select>
              </label>
              <label>
                Rule ID
                <input
                  value={issueRuleId}
                  onChange={(event) => setIssueRuleId(event.target.value)}
                  placeholder="e.g. exact_duplicate_box"
                />
              </label>
              <label>
                Class ID
                <select
                  value={issueClassId}
                  onChange={(event) => setIssueClassId(event.target.value)}
                >
                  <option value="">All classes</option>
                  {project.label_classes.map((labelClass) => (
                    <option key={labelClass.id} value={labelClass.id}>
                      {labelClass.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Image ID
                <input
                  value={issueImageId}
                  onChange={(event) => setIssueImageId(event.target.value)}
                  placeholder="Filter image id"
                />
              </label>
              <label>
                Status
                <select
                  value={issueStatus}
                  onChange={(event) => setIssueStatus(event.target.value)}
                >
                  <option value="">All statuses</option>
                  <option value="open">Open</option>
                  <option value="acknowledged">Acknowledged</option>
                  <option value="dismissed">Dismissed</option>
                  <option value="resolved_in_later_run">Resolved later</option>
                </select>
              </label>
            </div>
            {issues.isPending && <p>Loading quality-control issues...</p>}
            {issues.error && (
              <p className="form-error">{issues.error.message}</p>
            )}
            <div className="dashboard-list">
              {issues.data?.items.map((issue) => (
                <article
                  key={issue.id}
                  className={`dashboard-row severity-${issue.severity}`}
                >
                  <div>
                    <div className="image-card-topline">
                      <strong>{issue.title}</strong>
                      <span className="count-chip">{issue.severity}</span>
                      <span className="count-chip secondary-chip">
                        {issue.status}
                      </span>
                    </div>
                    <p>{issue.explanation}</p>
                    <small>{issue.rule_id}</small>
                    <pre className="json-block">
                      {stringifyRecord(issue.measured_values_json)}
                    </pre>
                    {Object.keys(issue.thresholds_json).length > 0 && (
                      <pre className="json-block">
                        {stringifyRecord(issue.thresholds_json)}
                      </pre>
                    )}
                  </div>
                  <div className="dashboard-actions">
                    {issue.image_id && (
                      <button type="button" onClick={() => onOpenImage(issue)}>
                        Open image
                      </button>
                    )}
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => acknowledgeIssue.mutate(issue.id)}
                      disabled={
                        acknowledgeIssue.isPending ||
                        issue.status === "dismissed"
                      }
                    >
                      Acknowledge
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => dismissIssue.mutate(issue.id)}
                      disabled={
                        dismissIssue.isPending || issue.status === "dismissed"
                      }
                    >
                      Dismiss
                    </button>
                  </div>
                </article>
              ))}
            </div>
            {issues.data && issues.data.pages > 1 && (
              <nav className="pagination" aria-label="QC issue pages">
                <button
                  type="button"
                  className="secondary"
                  disabled={issuePage === 1}
                  onClick={() => setIssuePage((current) => current - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {issues.data.page} of {issues.data.pages}
                </span>
                <button
                  type="button"
                  className="secondary"
                  disabled={issuePage === issues.data.pages}
                  onClick={() => setIssuePage((current) => current + 1)}
                >
                  Next
                </button>
              </nav>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
