import { getApiBaseUrl } from "../../runtime";

export type ActiveLearningStrategy =
  "hybrid" | "uncertainty" | "rare_class" | "quality";

export interface ActiveLearningSelectionItem {
  image_id: string;
  queue_item_id: string;
  rank_position: number;
  score: number;
  input_checksum: string;
  reason_summary: string | null;
  score_breakdown?: Array<Record<string, unknown>>;
  signal_values?: Record<string, unknown>;
}

export interface ActiveLearningRoundRecord {
  id: string;
  project_id: string;
  dataset_version_id: string | null;
  review_queue_id: string;
  name: string;
  strategy: ActiveLearningStrategy | string;
  status: string;
  requested_size: number;
  selected_count: number;
  model_ids_json: string[];
  strategy_config_json: Record<string, unknown>;
  selection_manifest_json: Record<string, unknown>;
  selection_sha256: string;
  feedback_summary_json: Record<string, unknown>;
  created_by: string;
  created_at: string;
  completed_at: string | null;
}

export interface ActiveLearningFeedback {
  round_id: string;
  status: string;
  selected_count: number;
  pending_count: number;
  in_progress_count: number;
  completed_count: number;
  skipped_count: number;
  completion_fraction: number;
  prediction_review_counts: Record<string, number>;
  feedback_dataset_version_id: string | null;
  feedback_manifest_sha256: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Active-learning request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function activeLearningSelectionItems(
  round: ActiveLearningRoundRecord | undefined,
): ActiveLearningSelectionItem[] {
  if (!round) return [];
  const items = round.selection_manifest_json.items;
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is ActiveLearningSelectionItem => {
    if (!item || typeof item !== "object") return false;
    const record = item as Record<string, unknown>;
    return (
      typeof record.image_id === "string" &&
      typeof record.queue_item_id === "string" &&
      typeof record.rank_position === "number" &&
      typeof record.score === "number"
    );
  });
}

export function getActiveLearningRounds(
  projectId: string,
  signal?: AbortSignal,
): Promise<ActiveLearningRoundRecord[]> {
  return request<ActiveLearningRoundRecord[]>(
    `/projects/${encodeURIComponent(projectId)}/active-learning-rounds`,
    { signal },
  );
}

export function createActiveLearningRound(
  projectId: string,
  payload: {
    name: string;
    dataset_version_id?: string | null;
    strategy: ActiveLearningStrategy;
    requested_size: number;
    model_ids?: string[];
  },
): Promise<ActiveLearningRoundRecord> {
  return request<ActiveLearningRoundRecord>(
    `/projects/${encodeURIComponent(projectId)}/active-learning-rounds`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getActiveLearningFeedback(
  roundId: string,
  signal?: AbortSignal,
): Promise<ActiveLearningFeedback> {
  return request<ActiveLearningFeedback>(
    `/active-learning-rounds/${encodeURIComponent(roundId)}/feedback`,
    { signal },
  );
}

export function completeActiveLearningRound(
  roundId: string,
): Promise<ActiveLearningRoundRecord> {
  return request<ActiveLearningRoundRecord>(
    `/active-learning-rounds/${encodeURIComponent(roundId)}/complete`,
    { method: "POST" },
  );
}
