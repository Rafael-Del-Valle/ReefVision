import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { getJob } from "../../api/client";
import { JobStatusCard } from "../system/SystemPanel";

export function ScheduledJobDetails({
  projectId,
  jobId,
  runId,
}: {
  projectId: string;
  jobId: string;
  runId: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const job = useQuery({
    queryKey: ["scheduled-job", projectId, runId, jobId],
    enabled: open,
    queryFn: async ({ signal }) => {
      const result = await getJob(jobId, signal);
      if (
        result.id !== jobId ||
        result.project_id !== projectId ||
        result.job_type !== "workflow_run" ||
        result.request_json.workflow_run_id !== runId
      ) {
        throw new Error("This workflow job does not match this occurrence.");
      }
      return result;
    },
    refetchInterval: (query) =>
      open &&
      ["queued", "running", "cancel_requested", "waiting_for_review"].includes(
        query.state.data?.status ?? "",
      )
        ? 2000
        : false,
  });
  return (
    <div>
      <button
        type="button"
        className="secondary"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(!open)}
      >
        {open ? "Close job" : "Open job"}
      </button>
      {open && (
        <section id={panelId} aria-label="Scheduled job details">
          {job.isPending && <p role="status">Loading job…</p>}
          {job.error && <p role="alert">{job.error.message}</p>}
          {job.data && (
            <JobStatusCard title="Scheduled workflow job" job={job.data} />
          )}
        </section>
      )}
    </div>
  );
}
