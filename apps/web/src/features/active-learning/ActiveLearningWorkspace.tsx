import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  completeActiveLearningRound,
  createActiveLearningRound,
  getActiveLearningFeedback,
  getActiveLearningModels,
  getActiveLearningRounds,
  type ActiveLearningRoundRecord,
  type ActiveLearningStrategy,
} from "./activeLearningApi";

interface ActiveLearningWorkspaceProps {
  project: Project;
  onOpenReviewQueue?: () => void;
}

interface SelectionReason {
  imageId: string;
  reason: string;
  score: number | null;
}

function selectionReasons(
  round: ActiveLearningRoundRecord | undefined,
): SelectionReason[] {
  const items = round?.selection_manifest_json.items;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const imageId = typeof record.image_id === "string" ? record.image_id : "Unknown image";
    const reason =
      typeof record.reason_summary === "string" && record.reason_summary.trim()
        ? record.reason_summary
        : "Selected by the configured acquisition strategy.";
    const score = typeof record.score === "number" ? record.score : null;
    return [{ imageId, reason, score }];
  });
}

export function ActiveLearningWorkspace({
  project,
  onOpenReviewQueue,
}: ActiveLearningWorkspaceProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("Active learning round");
  const [strategy, setStrategy] = useState<ActiveLearningStrategy>("hybrid");
  const [requestedSize, setRequestedSize] = useState(50);
  const [randomSeed, setRandomSeed] = useState(0);
  const [selectedModelIds, setSelectedModelIds] = useState<string[]>([]);
  const [selectedRoundId, setSelectedRoundId] = useState("");

  const roundsQuery = useQuery({
    queryKey: ["active-learning-rounds", project.id],
    queryFn: ({ signal }) => getActiveLearningRounds(project.id, signal),
  });
  const modelsQuery = useQuery({
    queryKey: ["active-learning-models", project.id],
    queryFn: ({ signal }) => getActiveLearningModels(project.id, signal),
  });
  const detectorModels = useMemo(
    () =>
      (modelsQuery.data ?? []).filter(
        (model) => model.purpose === "detector" && model.task === "detect",
      ),
    [modelsQuery.data],
  );
  const selectedRound = roundsQuery.data?.find(
    (round) => round.id === selectedRoundId,
  );
  const reasons = selectionReasons(selectedRound);
  const feedbackQuery = useQuery({
    queryKey: ["active-learning-feedback", selectedRoundId],
    queryFn: ({ signal }) => getActiveLearningFeedback(selectedRoundId, signal),
    enabled: Boolean(selectedRoundId),
    refetchInterval: selectedRound?.status === "complete" ? false : 3000,
  });

  useEffect(() => {
    if (!selectedRoundId && roundsQuery.data?.[0]) {
      setSelectedRoundId(roundsQuery.data[0].id);
    }
  }, [roundsQuery.data, selectedRoundId]);

  function toggleModel(modelId: string): void {
    setSelectedModelIds((current) =>
      current.includes(modelId)
        ? current.filter((value) => value !== modelId)
        : [...current, modelId],
    );
  }

  const committeeReady = strategy !== "committee" || selectedModelIds.length >= 2;
  const createMutation = useMutation({
    mutationFn: () =>
      createActiveLearningRound(project.id, {
        name,
        strategy,
        requested_size: requestedSize,
        model_ids: selectedModelIds,
        random_seed: randomSeed,
      }),
    onSuccess: async (round) => {
      setSelectedRoundId(round.id);
      await queryClient.invalidateQueries({
        queryKey: ["active-learning-rounds", project.id],
      });
    },
  });
  const completeMutation = useMutation({
    mutationFn: () => completeActiveLearningRound(selectedRoundId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["active-learning-rounds", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["active-learning-feedback", selectedRoundId],
        }),
      ]);
    },
  });

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 7</p>
          <h3>Active learning</h3>
          <p>
            Freeze an explainable acquisition batch, review it through the existing
            queue, and measure how much human feedback the round produced. Committee
            rounds compare independent detector outputs directly; random baseline rounds
            provide a reproducible control for scientific comparisons.
          </p>
        </div>
      </div>

      <div className="feature-grid">
        <form
          className="panel-card"
          onSubmit={(event) => {
            event.preventDefault();
            createMutation.mutate();
          }}
        >
          <h4>Create acquisition round</h4>
          <label>
            Round name
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            Strategy
            <select
              value={strategy}
              onChange={(event) =>
                setStrategy(event.target.value as ActiveLearningStrategy)
              }
            >
              <option value="hybrid">Hybrid</option>
              <option value="uncertainty">Uncertainty</option>
              <option value="rare_class">Rare class</option>
              <option value="quality">Quality risk</option>
              <option value="committee">Multi-model committee</option>
              <option value="random">Random baseline</option>
            </select>
          </label>

          <fieldset>
            <legend>Acquisition models</legend>
            <p className="muted-copy">
              Model filtering is optional for most strategies. Committee mode requires
              at least two independent detectors; three is the recommended default for a
              useful 2-of-3-style comparison, but ReefVision supports larger committees.
            </p>
            {detectorModels.length ? (
              <div className="annotation-selection-list">
                {detectorModels.map((model) => (
                  <label key={model.id} className="annotation-selection-row">
                    <input
                      type="checkbox"
                      checked={selectedModelIds.includes(model.id)}
                      onChange={() => toggleModel(model.id)}
                    />
                    <span>
                      <strong>{model.display_name}</strong>
                      <br />
                      <small>
                        {model.provider_name} · {model.task} · {model.sha256.slice(0, 10)}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <p>No registered detection models are available for this project.</p>
            )}
            {strategy === "committee" && selectedModelIds.length < 2 && (
              <p className="form-error">
                Select at least two registered detectors for committee acquisition.
              </p>
            )}
          </fieldset>

          {strategy === "random" && (
            <label>
              Random seed
              <input
                type="number"
                min={0}
                max={2147483647}
                value={randomSeed}
                onChange={(event) => setRandomSeed(Number(event.target.value))}
              />
            </label>
          )}
          <label>
            Review budget
            <input
              type="number"
              min={1}
              max={5000}
              value={requestedSize}
              onChange={(event) => setRequestedSize(Number(event.target.value))}
            />
          </label>
          <button
            type="submit"
            disabled={createMutation.isPending || !name.trim() || !committeeReady}
          >
            {createMutation.isPending ? "Creating..." : "Create round"}
          </button>
          {createMutation.error && (
            <p className="form-error">{createMutation.error.message}</p>
          )}
        </form>

        <div className="panel-card">
          <h4>Rounds</h4>
          <select
            value={selectedRoundId}
            onChange={(event) => setSelectedRoundId(event.target.value)}
          >
            <option value="">Select a round</option>
            {roundsQuery.data?.map((round) => (
              <option key={round.id} value={round.id}>
                {round.name} · {round.strategy} · {round.status}
              </option>
            ))}
          </select>
          {selectedRound && (
            <dl className="metric-list">
              <div>
                <dt>Selected</dt>
                <dd>{selectedRound.selected_count}</dd>
              </div>
              <div>
                <dt>Models</dt>
                <dd>{selectedRound.model_ids_json.length || "All available"}</dd>
              </div>
              <div>
                <dt>Review queue</dt>
                <dd>
                  <code>{selectedRound.review_queue_id}</code>
                </dd>
              </div>
              <div>
                <dt>Manifest</dt>
                <dd>
                  <code>{selectedRound.selection_sha256.slice(0, 12)}</code>
                </dd>
              </div>
              {selectedRound.strategy === "committee" && (
                <div>
                  <dt>Committee formula</dt>
                  <dd>
                    {String(
                      selectedRound.strategy_config_json.committee_formula_id ??
                        "detection_committee_disagreement_v1",
                    )}
                  </dd>
                </div>
              )}
              {selectedRound.strategy === "random" && (
                <div>
                  <dt>Random seed</dt>
                  <dd>{String(selectedRound.strategy_config_json.random_seed ?? 0)}</dd>
                </div>
              )}
            </dl>
          )}
          <div className="button-row">
            <button type="button" className="secondary" onClick={onOpenReviewQueue}>
              Open Review Queue
            </button>
            <button
              type="button"
              onClick={() => completeMutation.mutate()}
              disabled={!selectedRoundId || selectedRound?.status === "complete"}
            >
              Complete round
            </button>
          </div>
          {completeMutation.error && (
            <p className="form-error">{completeMutation.error.message}</p>
          )}
        </div>

        <div className="panel-card">
          <h4>Why these images?</h4>
          {reasons.length ? (
            <ol>
              {reasons.map((item) => (
                <li key={item.imageId}>
                  <strong>{item.imageId}</strong>
                  {item.score !== null && <> · score {item.score.toFixed(2)}</>}
                  <br />
                  {item.reason}
                </li>
              ))}
            </ol>
          ) : (
            <p>Select a round to inspect the frozen selection reasons.</p>
          )}
        </div>

        <div className="panel-card">
          <h4>Feedback progress</h4>
          {feedbackQuery.data ? (
            <>
              <progress max={1} value={feedbackQuery.data.completion_fraction} />
              <p>
                {(feedbackQuery.data.completion_fraction * 100).toFixed(1)}% terminal
              </p>
              <dl className="metric-list">
                <div>
                  <dt>Pending</dt>
                  <dd>{feedbackQuery.data.pending_count}</dd>
                </div>
                <div>
                  <dt>In progress</dt>
                  <dd>{feedbackQuery.data.in_progress_count}</dd>
                </div>
                <div>
                  <dt>Completed</dt>
                  <dd>{feedbackQuery.data.completed_count}</dd>
                </div>
                <div>
                  <dt>Skipped</dt>
                  <dd>{feedbackQuery.data.skipped_count}</dd>
                </div>
              </dl>
            </>
          ) : (
            <p>Select a round to inspect its human-feedback progress.</p>
          )}
        </div>
      </div>
    </section>
  );
}
