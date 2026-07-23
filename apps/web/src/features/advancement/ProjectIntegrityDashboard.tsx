import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import type { Project } from "../../api/client";
import { inspectProjectIntegrity } from "./api";
import { ProjectLifecyclePanel } from "./ProjectLifecyclePanel";
import {
  applyProjectRepairs,
  previewProjectRepairs,
} from "./projectRepairApi";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

export function ProjectIntegrityDashboard({ project }: { project: Project }) {
  const [verifyChecksums, setVerifyChecksums] = useState(false);
  const [staleJobMinutes, setStaleJobMinutes] = useState(60);
  const [minimumOrphanAgeMinutes, setMinimumOrphanAgeMinutes] = useState(60);
  const [selectedRepairIds, setSelectedRepairIds] = useState<string[]>([]);
  const report = useMutation({
    mutationFn: () =>
      inspectProjectIntegrity(project.id, verifyChecksums, staleJobMinutes),
  });
  const repairPlan = useMutation({
    mutationFn: () =>
      previewProjectRepairs(project.id, minimumOrphanAgeMinutes * 60),
    onSuccess: (plan) => {
      setSelectedRepairIds(
        plan.actions
          .filter((action) => action.safe_automatic)
          .map((action) => action.action_id),
      );
    },
  });
  const applyRepairs = useMutation({
    mutationFn: () =>
      applyProjectRepairs(
        project.id,
        selectedRepairIds,
        minimumOrphanAgeMinutes * 60,
      ),
    onSuccess: () => {
      setSelectedRepairIds([]);
      repairPlan.mutate();
      report.mutate();
    },
  });

  function toggleRepair(actionId: string) {
    setSelectedRepairIds((current) =>
      current.includes(actionId)
        ? current.filter((item) => item !== actionId)
        : [...current, actionId],
    );
  }

  return (
    <>
      <ProjectLifecyclePanel project={project} />
      <section className="dashboard-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Phase 1</p>
            <h3>Project integrity</h3>
            <span>
              Verify database records, managed files, model checksums, exports,
              and interrupted jobs. Preview safe storage repairs before applying
              them.
            </span>
          </div>
          {report.data && (
            <span>{new Date(report.data.checked_at).toLocaleString()}</span>
          )}
        </div>

        <div className="dashboard-layout">
          <div className="dashboard-sidebar">
            <article className="dashboard-card">
              <p className="eyebrow">Inspection settings</p>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={verifyChecksums}
                  onChange={(event) => setVerifyChecksums(event.target.checked)}
                />
                Verify image, video, and model SHA-256 checksums
              </label>
              <label>
                Flag active jobs older than
                <div className="inline-field-row">
                  <input
                    type="number"
                    min="1"
                    max="43200"
                    value={staleJobMinutes}
                    onChange={(event) =>
                      setStaleJobMinutes(Number(event.target.value))
                    }
                  />
                  <span>minutes</span>
                </div>
              </label>
              <button
                type="button"
                disabled={report.isPending || staleJobMinutes < 1}
                onClick={() => report.mutate()}
              >
                {report.isPending
                  ? "Inspecting..."
                  : "Inspect project integrity"}
              </button>
              <p>
                Checksum verification reads entire managed files and can take
                longer on large projects.
              </p>
              {report.error && (
                <p className="form-error">{report.error.message}</p>
              )}
            </article>

            <article className="dashboard-card">
              <p className="eyebrow">Safe storage repair</p>
              <h4>Preview orphan cleanup</h4>
              <label>
                Ignore files modified within
                <div className="inline-field-row">
                  <input
                    type="number"
                    min="1"
                    max="525600"
                    value={minimumOrphanAgeMinutes}
                    onChange={(event) =>
                      setMinimumOrphanAgeMinutes(Number(event.target.value))
                    }
                  />
                  <span>minutes</span>
                </div>
              </label>
              <button
                type="button"
                disabled={
                  repairPlan.isPending || minimumOrphanAgeMinutes < 1
                }
                onClick={() => repairPlan.mutate()}
              >
                {repairPlan.isPending ? "Scanning..." : "Preview safe repairs"}
              </button>
              <p>
                Unreferenced files are moved to the project quarantine. ReefVision
                does not permanently delete them.
              </p>
              {repairPlan.error && (
                <p className="form-error">{repairPlan.error.message}</p>
              )}
            </article>
          </div>

          <div className="dashboard-main">
            {applyRepairs.data && (
              <p className="form-success">
                Applied {applyRepairs.data.applied_action_ids.length} repairs ·{" "}
                {applyRepairs.data.quarantined_paths.length} files quarantined
              </p>
            )}
            {applyRepairs.error && (
              <p className="form-error">{applyRepairs.error.message}</p>
            )}

            {repairPlan.data && (
              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Repair preview</p>
                    <h4>{repairPlan.data.actions.length} safe actions available</h4>
                  </div>
                  <span>
                    {repairPlan.data.orphan_file_count} orphan files ·{" "}
                    {formatBytes(repairPlan.data.orphan_file_bytes)}
                  </span>
                </div>
                {repairPlan.data.warnings.map((warning) => (
                  <p key={warning} className="form-warning">
                    {warning}
                  </p>
                ))}
                {repairPlan.data.actions.length === 0 && (
                  <p>No missing root or old unreferenced files were found.</p>
                )}
                <div className="dashboard-list">
                  {repairPlan.data.actions.map((action) => (
                    <label
                      key={action.action_id}
                      className="annotation-selection-row"
                    >
                      <input
                        type="checkbox"
                        checked={selectedRepairIds.includes(action.action_id)}
                        onChange={() => toggleRepair(action.action_id)}
                      />
                      <span>
                        <strong>
                          {action.action_kind.replaceAll("_", " ")}
                        </strong>
                        <small>{action.managed_path}</small>
                        <small>{action.reason}</small>
                      </span>
                      <small>
                        {action.size_bytes === null
                          ? "Directory repair"
                          : formatBytes(action.size_bytes)}
                      </small>
                    </label>
                  ))}
                </div>
                <div className="version-actions">
                  <button
                    type="button"
                    className="secondary"
                    disabled={!repairPlan.data.actions.length}
                    onClick={() =>
                      setSelectedRepairIds(
                        repairPlan.data.actions.map((action) => action.action_id),
                      )
                    }
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={!selectedRepairIds.length}
                    onClick={() => setSelectedRepairIds([])}
                  >
                    Clear selection
                  </button>
                  <button
                    type="button"
                    disabled={
                      !selectedRepairIds.length || applyRepairs.isPending
                    }
                    onClick={() => applyRepairs.mutate()}
                  >
                    {applyRepairs.isPending
                      ? "Applying..."
                      : `Quarantine/apply ${selectedRepairIds.length} selected`}
                  </button>
                </div>
              </article>
            )}

            {!report.data && (
              <div className="empty-state">
                <h4>No integrity report yet</h4>
                <p>
                  Run an inspection to inventory all managed project resources.
                </p>
              </div>
            )}
            {report.data && (
              <>
                <div className="dashboard-grid">
                  <article className="dashboard-card">
                    <p className="eyebrow">Overall status</p>
                    <h4>
                      {report.data.valid ? "Valid" : "Attention required"}
                    </h4>
                    <p>
                      {report.data.error_count} errors ·{" "}
                      {report.data.warning_count} warnings
                    </p>
                  </article>
                  <article className="dashboard-card">
                    <p className="eyebrow">Managed paths</p>
                    <h4>{report.data.existing_referenced_files} available</h4>
                    <p>{report.data.missing_referenced_files} missing</p>
                  </article>
                  <article className="dashboard-card">
                    <p className="eyebrow">Managed size</p>
                    <h4>{formatBytes(report.data.total_existing_bytes)}</h4>
                    <p>{report.data.total_referenced_files} referenced paths</p>
                  </article>
                </div>

                <article className="dashboard-card">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Resource inventory</p>
                      <h4>Managed record coverage</h4>
                    </div>
                  </div>
                  <div className="dashboard-list">
                    {report.data.categories
                      .filter(
                        (category) =>
                          category.record_count > 0 ||
                          category.referenced_file_count > 0,
                      )
                      .map((category) => (
                        <div
                          key={category.resource_kind}
                          className="dashboard-row"
                        >
                          <div>
                            <strong>
                              {category.resource_kind.replaceAll("_", " ")}
                            </strong>
                            <p>
                              {category.record_count} records ·{" "}
                              {category.existing_file_count}/
                              {category.referenced_file_count} available
                            </p>
                            <small>
                              {formatBytes(category.total_existing_bytes)} ·{" "}
                              {category.checksum_verified_count} checksums
                              verified
                            </small>
                          </div>
                          <span>
                            {category.missing_file_count} missing ·{" "}
                            {category.checksum_mismatch_count} mismatched
                          </span>
                        </div>
                      ))}
                  </div>
                </article>

                <article className="dashboard-card">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Findings</p>
                      <h4>{report.data.issues.length} integrity findings</h4>
                    </div>
                  </div>
                  {report.data.issues.length === 0 && (
                    <p>
                      No missing, unsafe, stale, or inconsistent records were
                      found.
                    </p>
                  )}
                  <div className="dashboard-list">
                    {report.data.issues.map((issue, index) => (
                      <div
                        key={`${issue.code}-${issue.record_id ?? index}`}
                        className="dashboard-row"
                      >
                        <div>
                          <strong>
                            {issue.severity.toUpperCase()} ·{" "}
                            {issue.code.replaceAll("_", " ")}
                          </strong>
                          <p>{issue.message}</p>
                          <small>
                            {issue.resource_kind}
                            {issue.record_id ? ` · ${issue.record_id}` : ""}
                            {issue.managed_path
                              ? ` · ${issue.managed_path}`
                              : ""}
                          </small>
                        </div>
                        <span>
                          {issue.repairable ? "Repairable" : "Review"}
                        </span>
                      </div>
                    ))}
                  </div>
                </article>
              </>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
