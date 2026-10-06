import type { TrainingRun } from "../../api/client";

export const ACTIVE_TRAINING_RUN_STATUSES = [
  "queued",
  "preflight",
  "preparing_dataset",
  "training",
  "tuning",
  "running",
  "cancel_requested",
] as const;

const ACTIVE_TRAINING_RUN_STATUS_SET = new Set<string>(
  ACTIVE_TRAINING_RUN_STATUSES,
);

export function trainingRunIsActive(run: TrainingRun): boolean {
  return ACTIVE_TRAINING_RUN_STATUS_SET.has(run.status);
}

export function trainingRunsContainActive(
  runs: TrainingRun[] | undefined,
): boolean {
  return runs?.some(trainingRunIsActive) ?? false;
}
