import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  getTrainingDraft,
  getTrainingRuns,
  getTrainingWorkspaceBootstrap,
  type Project,
  type TrainingDraft,
  updateTrainingDraft,
} from "../../api/client";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

const defaultSearchSpace = JSON.stringify(
  {
    lr0: [0.0001, 0.01],
    lrf: [0.01, 1.0],
    momentum: [0.6, 0.98],
    weight_decay: [0.0, 0.001],
    warmup_epochs: [0.0, 5.0],
    box: [1.0, 12.0],
    cls: [0.2, 4.0],
    dfl: [0.5, 3.0],
    degrees: [0.0, 20.0],
    translate: [0.0, 0.4],
    scale: [0.0, 0.9],
    mosaic: [0.0, 1.0],
    mixup: [0.0, 0.4],
  },
  null,
  2,
);

export function TuningDashboard({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [draftId, setDraftId] = useState("");
  const [iterations, setIterations] = useState(10);
  const [epochsPerTrial, setEpochsPerTrial] = useState(10);
  const [optimizer, setOptimizer] = useState("AdamW");
  const [trainBest, setTrainBest] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [searchSpaceJson, setSearchSpaceJson] = useState(defaultSearchSpace);
  const [parseError, setParseError] = useState<string | null>(null);

  const bootstrap = useQuery({
    queryKey: ["tuning_workspace_bootstrap", project.id],
    queryFn: ({ signal }) => getTrainingWorkspaceBootstrap(project.id, signal),
  });
  const draft = useQuery({
    queryKey: ["training_draft", draftId],
    queryFn: ({ signal }) => getTrainingDraft(draftId, signal),
    enabled: draftId.length > 0,
  });
  const runs = useQuery({
    queryKey: ["tuning_runs", project.id],
    queryFn: ({ signal }) => getTrainingRuns(project.id, signal),
    refetchInterval: 3000,
  });

  useEffect(() => {
    const summaries = bootstrap.data?.draft_summaries ?? [];
    if (!draftId && summaries.length > 0) setDraftId(summaries[0].id);
  }, [bootstrap.data?.draft_summaries, draftId]);

  useEffect(() => {
    const selected = draft.data;
    if (!selected) return;
    const config = asRecord(selected.tuning_config);
    const mode = typeof config.mode === "string" ? config.mode : "disabled";
    setEnabled(mode === "ultralytics");
    setIterations(numberValue(config.iterations, 10));
    setEpochsPerTrial(numberValue(config.epochs_per_trial, 10));
    setOptimizer(
      typeof config.optimizer === "string" ? config.optimizer : "AdamW",
    );
    setTrainBest(booleanValue(config.train_best, true));
    const space = asRecord(config.search_space);
    setSearchSpaceJson(
      Object.keys(space).length > 0
        ? JSON.stringify(space, null, 2)
        : defaultSearchSpace,
    );
    setParseError(null);
  }, [draft.data]);

  const update = useMutation({
    mutationFn: async () => {
      if (!draft.data) throw new Error("Choose a training draft");
      let searchSpace: Record<string, unknown> = {};
      if (enabled) {
        try {
          const parsed = JSON.parse(searchSpaceJson) as unknown;
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            throw new Error("Search space must be a JSON object");
          }
          searchSpace = parsed as Record<string, unknown>;
          setParseError(null);
        } catch (error) {
          const message =
            error instanceof Error
              ? error.message
              : "Invalid search-space JSON";
          setParseError(message);
          throw new Error(message);
        }
      }
      return updateTrainingDraft(draft.data.id, {
        tuning_config: {
          mode: enabled ? "ultralytics" : "disabled",
          iterations,
          epochs_per_trial: epochsPerTrial,
          optimizer,
          train_best: trainBest,
          search_space: searchSpace,
        },
      });
    },
    onSuccess: (saved: TrainingDraft) => {
      queryClient.setQueryData(["training_draft", saved.id], saved);
      void queryClient.invalidateQueries({
        queryKey: ["training_workspace_bootstrap", project.id],
      });
    },
  });

  const tuningRuns = useMemo(
    () =>
      (runs.data ?? []).filter((run) => {
        const config = asRecord(run.tuning_config_json);
        return (
          config.mode === "ultralytics" ||
          asRecord(run.artifact_manifest_json).tuning
        );
      }),
    [runs.data],
  );

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Ultralytics model development</p>
          <h3>Hyperparameter tuning</h3>
          <span>
            Configure reproducible trials, preserve fitness history and plots,
            then train the final model with the best accepted parameters.
          </span>
        </div>
        <span>{tuningRuns.length} tuning runs</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <h4>Training draft</h4>
            <label>
              Draft
              <select
                value={draftId}
                onChange={(event) => setDraftId(event.target.value)}
              >
                <option value="">Choose a draft</option>
                {bootstrap.data?.draft_summaries.map((summary) => (
                  <option key={summary.id} value={summary.id}>
                    {summary.name} · {summary.task ?? "task unselected"}
                  </option>
                ))}
              </select>
            </label>
            {draft.data && (
              <div className="annotation-selection-list">
                <div className="annotation-selection-row">
                  <strong>Provider</strong>
                  <span>{draft.data.provider_id ?? "Unselected"}</span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Task</strong>
                  <span>{draft.data.task ?? "Unselected"}</span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Dataset</strong>
                  <span>{draft.data.dataset_version_id ?? "Unselected"}</span>
                </div>
              </div>
            )}
          </article>

          <article className="dashboard-card">
            <h4>Trial budget</h4>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              Run Ultralytics tuning before final training
            </label>
            <label>
              Trials
              <input
                type="number"
                min="1"
                max="300"
                value={iterations}
                disabled={!enabled}
                onChange={(event) => setIterations(Number(event.target.value))}
              />
            </label>
            <label>
              Epochs per trial
              <input
                type="number"
                min="1"
                max="500"
                value={epochsPerTrial}
                disabled={!enabled}
                onChange={(event) =>
                  setEpochsPerTrial(Number(event.target.value))
                }
              />
            </label>
            <label>
              Tuning optimizer
              <select
                value={optimizer}
                disabled={!enabled}
                onChange={(event) => setOptimizer(event.target.value)}
              >
                <option value="AdamW">AdamW</option>
                <option value="Adam">Adam</option>
                <option value="SGD">SGD</option>
                <option value="NAdam">NAdam</option>
                <option value="RAdam">RAdam</option>
              </select>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={trainBest}
                disabled={!enabled}
                onChange={(event) => setTrainBest(event.target.checked)}
              />
              Apply the best parameters to final training
            </label>
            <p>
              Total tuning epochs: {enabled ? iterations * epochsPerTrial : 0}
            </p>
          </article>
        </div>

        <div className="dashboard-main">
          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Search ranges</p>
                <h4>Ultralytics parameter space</h4>
              </div>
            </div>
            <p>
              Two-number arrays define continuous ranges. Longer arrays define
              discrete choices. Remove parameters that should retain their draft
              values.
            </p>
            <textarea
              rows={24}
              value={searchSpaceJson}
              disabled={!enabled}
              onChange={(event) => setSearchSpaceJson(event.target.value)}
              aria-label="Hyperparameter search space"
            />
            <button
              type="button"
              disabled={!draft.data || update.isPending}
              onClick={() => update.mutate()}
            >
              {update.isPending ? "Saving..." : "Save tuning configuration"}
            </button>
            {(parseError || update.error) && (
              <p className="form-error">
                {parseError ?? update.error?.message}
              </p>
            )}
            {update.isSuccess && (
              <p>Tuning configuration saved to the draft.</p>
            )}
          </article>

          <article className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Completed and active trials</p>
                <h4>Tuning history</h4>
              </div>
            </div>
            {tuningRuns.length === 0 ? (
              <p>No tuning runs have been launched from this project.</p>
            ) : (
              <div className="dashboard-list">
                {tuningRuns.map((run) => {
                  const tuning = asRecord(
                    asRecord(run.artifact_manifest_json).tuning,
                  );
                  return (
                    <div key={run.id} className="dashboard-row">
                      <div>
                        <strong>{run.run_name}</strong>
                        <p>
                          {run.status} · {run.stage} · {run.architecture}
                        </p>
                        <small>
                          Best fitness:{" "}
                          {typeof tuning.best_fitness === "number"
                            ? tuning.best_fitness.toFixed(5)
                            : "pending"}
                        </small>
                      </div>
                      <span>
                        {typeof tuning.trial_count === "number"
                          ? `${tuning.trial_count} trials`
                          : "not summarized"}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </article>
        </div>
      </div>
    </section>
  );
}
