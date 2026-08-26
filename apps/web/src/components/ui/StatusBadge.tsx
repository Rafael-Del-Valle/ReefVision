const LABELS: Record<string, string> = {
  ready: "Ready",
  installed: "Installed",
  available: "Available",
  training: "Training",
  running: "Running",
  queued: "Queued",
  succeeded: "Succeeded",
  completed: "Succeeded",
  failed: "Failed",
  warning: "Warning",
  needs_review: "Needs review",
  pending: "Pending",
  accepted: "Accepted",
  edited_and_accepted: "Edited and accepted",
  rejected: "Rejected",
  verified: "Verified",
  unavailable: "Unavailable",
  unannotated: "Unannotated",
  in_progress: "In progress",
  annotated: "Annotated",
  reviewed: "Reviewed",
  excluded: "Excluded",
};

export function StatusBadge({
  status,
  label,
}: {
  status: string;
  label?: string;
}) {
  const normalized = status.toLowerCase().replace(/[ -]+/g, "_");
  return (
    <span
      className={`rv-status rv-status-${normalized}`}
      data-status={normalized}
    >
      <span className="rv-status-icon" aria-hidden="true" />
      {label ?? LABELS[normalized] ?? status}
    </span>
  );
}
