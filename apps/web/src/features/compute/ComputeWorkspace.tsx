import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { cancelJob, request, retryJob, type JobRecord } from "../../api/client";

type Limits = { cpu_slots: number; gpu_slots: number };
type Resources = Limits & { cpu_in_use: number; gpu_in_use: number };
type Entry = {
  job: JobRecord;
  pool: "cpu" | "gpu";
  admission: "ready" | "waiting" | "reserved" | "inactive";
  reason: string | null;
  heartbeat_at: string | null;
  checkpoint_available: boolean;
  can_retry: boolean;
  can_cancel: boolean;
};
type Action = "cancel" | "retry" | "resume";
const pageSize = 30;

export function ComputeWorkspace({ projectId }: { projectId: string }) {
  const cache = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [edited, setEdited] = useState<Limits | null>(null);
  const [notice, setNotice] = useState("");
  const resources = useQuery({
    queryKey: ["compute-resources"],
    queryFn: ({ signal }) =>
      request<Resources>("/compute/resources", { signal }),
    refetchInterval: 4000,
  });
  const jobs = useQuery({
    queryKey: ["compute-jobs", projectId, offset],
    queryFn: ({ signal }) =>
      request<{ items: Entry[]; total: number }>(
        `/projects/${projectId}/compute/jobs?limit=${pageSize}&offset=${offset}`,
        { signal },
      ),
    refetchInterval: 2000,
  });
  const limits = edited ?? resources.data;
  const save = useMutation({
    mutationFn: (value: Limits) =>
      request<Resources>("/compute/resources", {
        method: "PUT",
        body: JSON.stringify({
          cpu_slots: value.cpu_slots,
          gpu_slots: value.gpu_slots,
        }),
      }),
    onSuccess(data) {
      cache.setQueryData(["compute-resources"], data);
      setEdited(null);
      void jobs.refetch();
      setNotice("Resource limits saved.");
    },
  });
  const action = useMutation({
    mutationFn: ({ id, operation }: { id: string; operation: Action }) => {
      if (operation === "cancel") return cancelJob(id);
      if (operation === "retry") return retryJob(id);
      return request<JobRecord>(`/jobs/${id}/resume`, { method: "POST" });
    },
    onSuccess(job) {
      setNotice(`Job ${job.id} is ${job.status.replaceAll("_", " ")}.`);
      void jobs.refetch();
      void resources.refetch();
    },
  });
  return (
    <section className="panel" aria-label="Jobs and resources">
      <h2>Jobs and resources</h2>
      <p>
        Set concurrent jobs for this local profile. Choose zero to pause new
        work in a queue. Active jobs can finish.
      </p>
      {limits && resources.data && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(limits);
          }}
        >
          <fieldset disabled={save.isPending}>
            <legend>Local compute limits</legend>
            {(["cpu", "gpu"] as const).map((pool) => (
              <label key={pool}>
                {pool.toUpperCase()} slots
                <select
                  value={limits[`${pool}_slots`]}
                  onChange={(event) => {
                    setEdited({
                      cpu_slots: limits.cpu_slots,
                      gpu_slots: limits.gpu_slots,
                      [`${pool}_slots`]: Number(event.target.value),
                    });
                    setNotice("");
                  }}
                >
                  {Array.from({ length: pool === "cpu" ? 9 : 2 }, (_, i) => (
                    <option value={i} key={i}>
                      {i}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <button type="submit" disabled={!edited}>
              Save resource limits
            </button>
          </fieldset>
          <p>
            In use · CPU {resources.data.cpu_in_use} of{" "}
            {resources.data.cpu_slots} · GPU {resources.data.gpu_in_use} of{" "}
            {resources.data.gpu_slots}
          </p>
        </form>
      )}
      <p role="status">{notice}</p>
      {(resources.error || jobs.error || save.error || action.error) && (
        <p role="alert">
          {
            (action.error ?? save.error ?? jobs.error ?? resources.error)
              ?.message
          }
        </p>
      )}
      <h3>Project jobs</h3>
      {jobs.isPending && <p role="status">Loading project jobs…</p>}
      {jobs.data?.total === 0 && <p>No jobs in this project.</p>}
      {jobs.data?.items.map(
        ({
          job,
          pool,
          admission,
          reason,
          heartbeat_at,
          checkpoint_available,
          can_cancel,
          can_retry,
        }) => (
          <article
            className="system-job-card"
            key={job.id}
            aria-label={`${job.job_type} ${job.id}`}
          >
            <h4>{job.job_type.replaceAll("_", " ")}</h4>
            <p>
              <code>{job.id}</code> · {pool.toUpperCase()} ·{" "}
              {job.status.replaceAll("_", " ")}
              {admission !== "inactive" && ` · ${admission}`}
            </p>
            {reason && <p>{reason}</p>}
            <p>
              Progress {job.progress_current} / {job.progress_total}
              {typeof job.result_json?.stage === "string" &&
                ` · ${job.result_json.stage.replaceAll("_", " ")}`}
            </p>
            {heartbeat_at && (
              <p>
                Worker heartbeat{" "}
                <time dateTime={heartbeat_at}>
                  {new Date(heartbeat_at).toLocaleString()}
                </time>
              </p>
            )}
            {job.error_message && (
              <p className="form-error">{job.error_message}</p>
            )}
            {can_cancel && (
              <button
                disabled={action.isPending}
                onClick={() =>
                  action.mutate({ id: job.id, operation: "cancel" })
                }
              >
                Cancel job
              </button>
            )}
            {checkpoint_available && (
              <button
                disabled={action.isPending}
                onClick={() =>
                  action.mutate({ id: job.id, operation: "resume" })
                }
              >
                Resume from checkpoint
              </button>
            )}
            {can_retry && !checkpoint_available && (
              <button
                disabled={action.isPending}
                onClick={() =>
                  action.mutate({ id: job.id, operation: "retry" })
                }
              >
                Retry job
              </button>
            )}
          </article>
        ),
      )}
      {jobs.data && (offset > 0 || jobs.data.total > pageSize) && (
        <nav aria-label="Project jobs pages">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - pageSize))}
          >
            Previous jobs
          </button>
          <span>
            {offset + 1}–{Math.min(offset + pageSize, jobs.data.total)} of{" "}
            {jobs.data.total}
          </span>
          <button
            disabled={offset + pageSize >= jobs.data.total}
            onClick={() => setOffset(offset + pageSize)}
          >
            Next jobs
          </button>
        </nav>
      )}
    </section>
  );
}
