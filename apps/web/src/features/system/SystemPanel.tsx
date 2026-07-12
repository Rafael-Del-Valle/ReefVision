import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  cancelJob,
  createBackup,
  createSystemDiagnostics,
  getBackups,
  getJob,
  getSystemCommandShortcuts,
  getSystemCompatibility,
  getSystemDiagnosticsStatus,
  getSystemLogsLocation,
  getSystemVersion,
  repairSystemCommandShortcuts,
  restoreBackup,
  verifyBackup,
  type BackupRecord,
  type BackupVerificationResponse,
  type JobRecord,
  type SystemCommandShortcutRepairResponse,
  type SystemDiagnosticsStatusResponse,
} from "../../api/client";

const ACTIVE_JOB_STATUSES = new Set(["queued", "running", "cancel_requested"]);

function bytesLabel(bytes: number | null | undefined): string {
  if (bytes == null) {
    return "Unknown";
  }
  if (bytes >= 1_073_741_824) {
    return `${(bytes / 1_073_741_824).toFixed(2)} GiB`;
  }
  if (bytes >= 1_048_576) {
    return `${(bytes / 1_048_576).toFixed(1)} MiB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  return `${bytes} B`;
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Not started";
  }
  return new Date(value).toLocaleString();
}

function previewFromBackup(backup: BackupRecord): {
  included_sections: string[];
  estimated_file_count: number | null;
  estimated_total_size_bytes: number | null;
} | null {
  const preview = backup.request_json.preview;
  if (!preview || typeof preview !== "object") {
    return null;
  }
  const record = preview as Record<string, unknown>;
  return {
    included_sections: Array.isArray(record.included_sections)
      ? record.included_sections.filter(
          (item): item is string => typeof item === "string",
        )
      : [],
    estimated_file_count:
      typeof record.estimated_file_count === "number"
        ? record.estimated_file_count
        : null,
    estimated_total_size_bytes:
      typeof record.estimated_total_size_bytes === "number"
        ? record.estimated_total_size_bytes
        : null,
  };
}

function JobStatusCard({
  title,
  job,
  onCancel,
}: {
  title: string;
  job: JobRecord;
  onCancel?: () => void;
}) {
  const stage =
    typeof job.result_json?.stage === "string"
      ? job.result_json.stage
      : job.status;
  const canCancel = ACTIVE_JOB_STATUSES.has(job.status) && onCancel;

  return (
    <article className="system-job-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{title}</p>
          <h4>{job.status}</h4>
        </div>
        <span className="status-chip">{stage}</span>
      </div>
      <p>
        Progress {job.progress_current} / {job.progress_total}
      </p>
      {job.error_message && <p className="form-error">{job.error_message}</p>}
      {canCancel && (
        <button
          type="button"
          className="secondary"
          onClick={() => onCancel?.()}
        >
          Cancel job
        </button>
      )}
    </article>
  );
}

export function SystemPanel({
  onOpenOnboarding,
}: {
  onOpenOnboarding?: () => void;
}) {
  const queryClient = useQueryClient();
  const [includeExports, setIncludeExports] = useState(false);
  const [includeLogs, setIncludeLogs] = useState(false);
  const [backupNotes, setBackupNotes] = useState("");
  const [restoreNames, setRestoreNames] = useState<Record<string, string>>({});
  const [verificationReports, setVerificationReports] = useState<
    Record<string, BackupVerificationResponse>
  >({});
  const [latestBackupJobId, setLatestBackupJobId] = useState<string | null>(
    null,
  );
  const [latestRestoreJobId, setLatestRestoreJobId] = useState<string | null>(
    null,
  );
  const [latestDiagnosticsJobId, setLatestDiagnosticsJobId] = useState<
    string | null
  >(null);

  const version = useQuery({
    queryKey: ["system", "version"],
    queryFn: ({ signal }) => getSystemVersion(signal),
  });
  const compatibility = useQuery({
    queryKey: ["system", "compatibility"],
    queryFn: ({ signal }) => getSystemCompatibility(signal),
  });
  const logs = useQuery({
    queryKey: ["system", "logs"],
    queryFn: ({ signal }) => getSystemLogsLocation(signal),
  });
  const backups = useQuery({
    queryKey: ["backups"],
    queryFn: ({ signal }) => getBackups(signal),
    refetchInterval:
      latestBackupJobId || latestRestoreJobId || latestDiagnosticsJobId
        ? 1000
        : false,
  });
  const backupJob = useQuery({
    queryKey: ["jobs", latestBackupJobId],
    queryFn: ({ signal }) => getJob(latestBackupJobId as string, signal),
    enabled: Boolean(latestBackupJobId),
    refetchInterval: 1000,
  });
  const restoreJob = useQuery({
    queryKey: ["jobs", latestRestoreJobId],
    queryFn: ({ signal }) => getJob(latestRestoreJobId as string, signal),
    enabled: Boolean(latestRestoreJobId),
    refetchInterval: 1000,
  });
  const diagnostics = useQuery({
    queryKey: ["system", "diagnostics", latestDiagnosticsJobId],
    queryFn: ({ signal }) =>
      getSystemDiagnosticsStatus(latestDiagnosticsJobId as string, signal),
    enabled: Boolean(latestDiagnosticsJobId),
    refetchInterval: 1000,
  });
  const commandShortcuts = useQuery({
    queryKey: ["system", "command-shortcuts"],
    queryFn: ({ signal }) => getSystemCommandShortcuts(signal),
  });

  const refreshBackups = async () => {
    await queryClient.invalidateQueries({ queryKey: ["backups"] });
  };

  const createBackupMutation = useMutation({
    mutationFn: () =>
      createBackup({
        include_exports: includeExports,
        include_logs: includeLogs,
        notes: backupNotes || undefined,
      }),
    onSuccess: async (response) => {
      setLatestBackupJobId(response.job.id);
      setBackupNotes("");
      await refreshBackups();
    },
  });
  const verifyBackupMutation = useMutation({
    mutationFn: (backupId: string) => verifyBackup(backupId),
    onSuccess: (report) => {
      setVerificationReports((current) => ({
        ...current,
        [report.backup_id]: report,
      }));
    },
  });
  const restoreBackupMutation = useMutation({
    mutationFn: (payload: { backupId: string; destinationName?: string }) =>
      restoreBackup(payload.backupId, {
        destination_name: payload.destinationName || undefined,
      }),
    onSuccess: async (response) => {
      setLatestRestoreJobId(response.job.id);
      await refreshBackups();
    },
  });
  const diagnosticsMutation = useMutation({
    mutationFn: () => createSystemDiagnostics({ strict_redaction: true }),
    onSuccess: (response) => {
      setLatestDiagnosticsJobId(response.job.id);
    },
  });
  const repairCommandsMutation = useMutation({
    mutationFn: () => repairSystemCommandShortcuts(),
    onSuccess: async (response: SystemCommandShortcutRepairResponse) => {
      await queryClient.setQueryData(
        ["system", "command-shortcuts"],
        response.status,
      );
      await queryClient.invalidateQueries({
        queryKey: ["system", "command-shortcuts"],
      });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
  });

  if (
    version.isPending ||
    compatibility.isPending ||
    logs.isPending ||
    backups.isPending ||
    commandShortcuts.isPending
  ) {
    return (
      <div className="welcome-panel">
        <p className="eyebrow">Milestone 8 foundations</p>
        <h2>System status</h2>
        <p>
          Loading version, schema, compatibility, logs, command shortcuts,
          backup history, and recovery tools...
        </p>
      </div>
    );
  }

  if (
    version.error ||
    compatibility.error ||
    logs.error ||
    backups.error ||
    commandShortcuts.error
  ) {
    return (
      <div className="welcome-panel">
        <p className="eyebrow">Milestone 8 foundations</p>
        <h2>System status</h2>
        <p className="form-error">
          {version.error?.message ||
            compatibility.error?.message ||
            logs.error?.message ||
            backups.error?.message ||
            commandShortcuts.error?.message}
        </p>
      </div>
    );
  }

  const versionData = version.data;
  const compatibilityData = compatibility.data;
  const logsData = logs.data;
  const commandShortcutData = commandShortcuts.data;
  const backupData = backups.data;
  const diagnosticsData: SystemDiagnosticsStatusResponse | undefined =
    diagnostics.data;

  return (
    <div className="system-panel">
      <div className="project-header">
        <div>
          <p className="eyebrow">Milestone 8 foundations</p>
          <h2>System status</h2>
          <p>
            Current application identity, database compatibility, backups,
            diagnostics, onboarding, and bounded log locations.
          </p>
        </div>
        <div className="system-header-actions">
          {onOpenOnboarding && (
            <button
              type="button"
              className="secondary"
              onClick={onOpenOnboarding}
            >
              Reopen onboarding
            </button>
          )}
          <span className="status-chip">{compatibilityData.schema_status}</span>
        </div>
      </div>

      <div className="system-grid">
        <section className="system-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Application</p>
              <h3>Version</h3>
            </div>
          </div>
          <dl className="system-list">
            <div>
              <dt>ReefVision</dt>
              <dd>{versionData.application_version}</dd>
            </div>
            <div>
              <dt>Backup format</dt>
              <dd>{versionData.backup_format_version}</dd>
            </div>
            <div>
              <dt>Environment</dt>
              <dd>{versionData.environment}</dd>
            </div>
            <div>
              <dt>Safe mode</dt>
              <dd>{versionData.safe_mode ? "Enabled" : "Disabled"}</dd>
            </div>
            <div>
              <dt>Current schema</dt>
              <dd>{versionData.current_schema_revision ?? "Uninitialized"}</dd>
            </div>
            <div>
              <dt>Expected schema</dt>
              <dd>{versionData.expected_schema_revision ?? "Unknown"}</dd>
            </div>
          </dl>
        </section>

        <section className="system-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Compatibility</p>
              <h3>Database</h3>
            </div>
          </div>
          <dl className="system-list">
            <div>
              <dt>Status</dt>
              <dd>{compatibilityData.schema_status}</dd>
            </div>
            <div>
              <dt>Read/write allowed</dt>
              <dd>
                {compatibilityData.compatible_for_read_write ? "Yes" : "No"}
              </dd>
            </div>
            <div>
              <dt>Pending revisions</dt>
              <dd>
                {compatibilityData.pending_revisions.length > 0
                  ? compatibilityData.pending_revisions.join(", ")
                  : "None"}
              </dd>
            </div>
          </dl>
          {compatibilityData.details.length > 0 && (
            <ul className="system-details">
              {compatibilityData.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="system-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Recovery</p>
            <h3>Backups and restore</h3>
          </div>
        </div>
        <form
          className="system-form"
          onSubmit={(event) => {
            event.preventDefault();
            createBackupMutation.mutate();
          }}
        >
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={includeExports}
              onChange={(event) => setIncludeExports(event.target.checked)}
            />
            Include managed exports
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={includeLogs}
              onChange={(event) => setIncludeLogs(event.target.checked)}
            />
            Include logs
          </label>
          <label>
            Backup notes
            <textarea
              value={backupNotes}
              onChange={(event) => setBackupNotes(event.target.value)}
              placeholder="Optional notes for this backup"
            />
          </label>
          <div className="system-actions">
            <button type="submit" disabled={createBackupMutation.isPending}>
              {createBackupMutation.isPending ? "Queueing..." : "Create backup"}
            </button>
          </div>
          {createBackupMutation.error && (
            <p className="form-error">{createBackupMutation.error.message}</p>
          )}
        </form>

        {backupJob.data && (
          <JobStatusCard
            title="Latest backup job"
            job={backupJob.data}
            onCancel={
              ACTIVE_JOB_STATUSES.has(backupJob.data.status)
                ? () => cancelMutation.mutate(backupJob.data.id)
                : undefined
            }
          />
        )}
        {restoreJob.data && (
          <JobStatusCard
            title="Latest restore job"
            job={restoreJob.data}
            onCancel={
              ACTIVE_JOB_STATUSES.has(restoreJob.data.status)
                ? () => cancelMutation.mutate(restoreJob.data.id)
                : undefined
            }
          />
        )}

        <div className="system-record-list">
          {backupData.length === 0 ? (
            <p>No managed backups exist yet.</p>
          ) : (
            backupData.map((backup) => {
              const preview = previewFromBackup(backup);
              const report = verificationReports[backup.id];
              return (
                <article key={backup.id} className="system-record-card">
                  <div className="section-heading">
                    <div>
                      <strong>{backup.id}</strong>
                      <p className="system-subtle">
                        Created {formatTimestamp(backup.created_at)}
                      </p>
                    </div>
                    <span className="status-chip">{backup.status}</span>
                  </div>
                  {preview && (
                    <p className="system-subtle">
                      Includes {preview.included_sections.join(", ")}. Estimated{" "}
                      {preview.estimated_file_count ?? "?"} files and{" "}
                      {bytesLabel(preview.estimated_total_size_bytes)}.
                    </p>
                  )}
                  <code>{backup.destination_path}</code>
                  <div className="system-inline-form">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => verifyBackupMutation.mutate(backup.id)}
                      disabled={verifyBackupMutation.isPending}
                    >
                      Verify backup
                    </button>
                    <input
                      aria-label={`Restore destination for ${backup.id}`}
                      value={restoreNames[backup.id] ?? ""}
                      onChange={(event) =>
                        setRestoreNames((current) => ({
                          ...current,
                          [backup.id]: event.target.value,
                        }))
                      }
                      placeholder="restore-copy"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        restoreBackupMutation.mutate({
                          backupId: backup.id,
                          destinationName: restoreNames[backup.id],
                        })
                      }
                      disabled={restoreBackupMutation.isPending}
                    >
                      Restore into new location
                    </button>
                  </div>
                  {report && (
                    <div className="system-verification-report">
                      <strong>Verification: {report.status}</strong>
                      <span>
                        {report.file_count} files,{" "}
                        {bytesLabel(report.total_size_bytes)}
                      </span>
                      {report.warnings.length > 0 && (
                        <p className="system-subtle">
                          Warnings: {report.warnings.join(" | ")}
                        </p>
                      )}
                      {report.errors.length > 0 && (
                        <p className="form-error">
                          Errors: {report.errors.join(" | ")}
                        </p>
                      )}
                    </div>
                  )}
                </article>
              );
            })
          )}
        </div>
        {(verifyBackupMutation.error || restoreBackupMutation.error) && (
          <p className="form-error">
            {verifyBackupMutation.error?.message ||
              restoreBackupMutation.error?.message}
          </p>
        )}
      </section>

      <section className="system-grid">
        <section className="system-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Commands</p>
              <h3>Install or repair shortcuts</h3>
            </div>
            <span className="status-chip">
              {commandShortcutData.verification_result}
            </span>
          </div>
          <p className="system-subtle">
            Installs the per-user `start-reefvision` and `update-reefvision`
            wrappers and verifies that the shared command directory is on PATH.
          </p>
          <dl className="system-list">
            <div>
              <dt>Command version</dt>
              <dd>{commandShortcutData.command_version}</dd>
            </div>
            <div>
              <dt>PATH status</dt>
              <dd>
                {commandShortcutData.path_contains_command_directory
                  ? "Configured"
                  : "Missing"}
              </dd>
            </div>
            <div>
              <dt>`start-reefvision`</dt>
              <dd>
                {commandShortcutData.start_command_exists
                  ? commandShortcutData.start_command_managed
                    ? "Managed wrapper"
                    : "Conflict detected"
                  : "Missing"}
              </dd>
            </div>
            <div>
              <dt>`update-reefvision`</dt>
              <dd>
                {commandShortcutData.update_command_exists
                  ? commandShortcutData.update_command_managed
                    ? "Managed wrapper"
                    : "Conflict detected"
                  : "Missing"}
              </dd>
            </div>
            <div>
              <dt>Command directory</dt>
              <dd>
                <code>{commandShortcutData.command_directory}</code>
              </dd>
            </div>
            <div>
              <dt>Support directory</dt>
              <dd>
                <code>{commandShortcutData.support_directory}</code>
              </dd>
            </div>
            <div>
              <dt>Repository path</dt>
              <dd>
                <code>
                  {commandShortcutData.repo_path ?? "Not configured"}
                </code>
              </dd>
            </div>
          </dl>
          {commandShortcutData.notes.length > 0 && (
            <ul className="system-details">
              {commandShortcutData.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
          <div className="system-actions">
            <button
              type="button"
              onClick={() => repairCommandsMutation.mutate()}
              disabled={repairCommandsMutation.isPending}
            >
              {repairCommandsMutation.isPending
                ? "Repairing..."
                : "Install or Repair Command-Line Shortcuts"}
            </button>
          </div>
          {repairCommandsMutation.error && (
            <p className="form-error">
              {repairCommandsMutation.error.message}
            </p>
          )}
          {repairCommandsMutation.data && (
            <div className="system-verification-report">
              <strong>
                Verification:{" "}
                {repairCommandsMutation.data.status.verification_result}
              </strong>
              <code>{repairCommandsMutation.data.output}</code>
            </div>
          )}
        </section>

        <section className="system-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Diagnostics</p>
              <h3>Export support bundle</h3>
            </div>
          </div>
          <p className="system-subtle">
            Creates a redacted diagnostic archive with version, dependency,
            migration, disk, and recent log information. Media files are not
            included by default.
          </p>
          <div className="system-actions">
            <button
              type="button"
              onClick={() => diagnosticsMutation.mutate()}
              disabled={diagnosticsMutation.isPending}
            >
              {diagnosticsMutation.isPending
                ? "Queueing..."
                : "Create diagnostics bundle"}
            </button>
          </div>
          {diagnosticsMutation.error && (
            <p className="form-error">{diagnosticsMutation.error.message}</p>
          )}
          {diagnosticsData && (
            <div className="system-verification-report">
              <strong>Diagnostics job: {diagnosticsData.job.status}</strong>
              <span>
                Bundle version{" "}
                {diagnosticsData.diagnostic_bundle_version ?? "Pending"}
              </span>
              {diagnosticsData.bundle_path && (
                <code>{diagnosticsData.bundle_path}</code>
              )}
              {diagnosticsData.bundle_size_bytes != null && (
                <span>{bytesLabel(diagnosticsData.bundle_size_bytes)}</span>
              )}
              {ACTIVE_JOB_STATUSES.has(diagnosticsData.job.status) && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => cancelMutation.mutate(diagnosticsData.job.id)}
                >
                  Cancel job
                </button>
              )}
            </div>
          )}
        </section>

        <section className="system-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Paths</p>
              <h3>Data and logs</h3>
            </div>
          </div>
          <dl className="system-list">
            <div>
              <dt>Data directory</dt>
              <dd>
                <code>{versionData.data_dir}</code>
              </dd>
            </div>
            <div>
              <dt>Database</dt>
              <dd>
                <code>
                  {versionData.database_path ?? "In-memory or unavailable"}
                </code>
              </dd>
            </div>
            <div>
              <dt>Logs directory</dt>
              <dd>
                <code>{logsData.logs_dir}</code>
              </dd>
            </div>
          </dl>
          <div className="system-log-list">
            {logsData.files.length === 0 ? (
              <p>No log files exist yet.</p>
            ) : (
              logsData.files.map((file) => (
                <article key={file.path} className="system-log-item">
                  <strong>{file.name}</strong>
                  <span>{bytesLabel(file.size_bytes)}</span>
                  <code>{file.path}</code>
                </article>
              ))
            )}
          </div>
        </section>
      </section>
    </div>
  );
}
