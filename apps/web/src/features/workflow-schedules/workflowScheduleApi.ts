import { request } from "../../api/client";

export type SchedulePurpose = "acquisition" | "inference" | "qc" | "report";

export type ScheduleOccurrenceStatus =
  | "queued"
  | "running"
  | "waiting_for_review"
  | "cancel_requested"
  | "cancelled"
  | "succeeded"
  | "failed";

export type ScheduleStatus =
  | "scheduled"
  | "paused"
  | "waiting_previous_run"
  | "blocked_storage"
  | "dispatch_failed"
  | ScheduleOccurrenceStatus;

export interface WorkflowSchedule {
  id: string;
  project_id: string;
  name: string;
  purpose: SchedulePurpose;
  workflow_graph_record_id: string;
  graph_sha256: string;
  inputs: Record<string, unknown>;
  inputs_sha256: string;
  interval_seconds: number;
  next_due_at: string;
  enabled: boolean;
  revision: number;
  minimum_free_bytes: number;
  last_status: ScheduleStatus;
  last_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleOccurrence {
  id: string;
  project_id: string;
  schedule_id: string;
  scheduled_at: string;
  created_at: string;
  missed_intervals: number;
  status: ScheduleOccurrenceStatus;
  detail: string | null;
  workflow_run_id: string | null;
  job_id: string | null;
  graph_sha256: string;
  inputs_sha256: string;
}

export interface WorkflowScheduleReceipt {
  receipt_sha256: string;
  receipt: {
    schema_version: "workflow-schedule-receipt-0001";
    project_id: string;
    schedule_id: string;
    occurrence_id: string;
    scheduled_at: string;
    dispatched_at: string;
    purpose: SchedulePurpose;
    missed_intervals: number;
    workflow_graph_record_id: string;
    graph_sha256: string;
    inputs: Record<string, unknown>;
    inputs_sha256: string;
    workflow_run_id: string | null;
    job_id: string | null;
    status: "succeeded" | "failed" | "cancelled";
    detail: string | null;
    workflow_provenance_sha256: string | null;
    artifacts: {
      artifact_id: string;
      producer_node_run_id: string;
      producer_port_id: string;
      data_type: string;
      payload_sha256: string;
    }[];
  };
}

export interface WorkflowScheduleCreate {
  name: string;
  purpose: SchedulePurpose;
  workflow_graph_record_id: string;
  interval_seconds: number;
  next_due_at: string;
  enabled: boolean;
  minimum_free_bytes: number;
}

export type WorkflowScheduleUpdate = Partial<
  Omit<WorkflowScheduleCreate, "purpose" | "workflow_graph_record_id">
> & {
  expected_revision: number;
};

interface SchedulePage<T> {
  items: T[];
  total: number;
}

export const schedulePageSize = 20;

function schedulePath(projectId: string, scheduleId?: string) {
  const project = `/projects/${encodeURIComponent(projectId)}/workflow-schedules`;
  return scheduleId ? `${project}/${encodeURIComponent(scheduleId)}` : project;
}

export function listWorkflowSchedules(
  projectId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<SchedulePage<WorkflowSchedule>>(
    `${schedulePath(projectId)}?limit=${schedulePageSize}&offset=${offset}`,
    { signal },
  );
}

export function createWorkflowSchedule(
  projectId: string,
  data: WorkflowScheduleCreate,
) {
  return request<WorkflowSchedule>(schedulePath(projectId), {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateWorkflowSchedule(
  projectId: string,
  scheduleId: string,
  data: WorkflowScheduleUpdate,
) {
  return request<WorkflowSchedule>(schedulePath(projectId, scheduleId), {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function listScheduleOccurrences(
  projectId: string,
  scheduleId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<SchedulePage<ScheduleOccurrence>>(
    `${schedulePath(projectId, scheduleId)}/occurrences?limit=${schedulePageSize}&offset=${offset}`,
    { signal },
  );
}

export function cancelScheduleOccurrence(
  projectId: string,
  scheduleId: string,
  occurrenceId: string,
) {
  return request<ScheduleOccurrence>(
    `${schedulePath(projectId, scheduleId)}/occurrences/${encodeURIComponent(occurrenceId)}/cancel`,
    { method: "POST" },
  );
}

export function getScheduleOccurrenceReceipt(
  projectId: string,
  occurrenceId: string,
) {
  return request<WorkflowScheduleReceipt>(
    `/projects/${encodeURIComponent(projectId)}/workflow-schedule-occurrences/${encodeURIComponent(occurrenceId)}/receipt`,
  );
}
