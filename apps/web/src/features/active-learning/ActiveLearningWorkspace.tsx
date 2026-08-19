import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  getDatasetVersions,
  getModels,
  type Project,
} from "../../api/client";
import { AdvancedProviderWorkspace } from "../advanced-providers/AdvancedProviderWorkspace";
import { InteroperabilityWorkspace } from "../interoperability/InteroperabilityWorkspace";
import { WorkflowGraphWorkspace } from "../workflow-graphs/WorkflowGraphWorkspace";
import {
  activeLearningSelectionItems,
  completeActiveLearningRound,
  createActiveLearningRound,
  getActiveLearningFeedback,
  getActiveLearningRounds,
  type ActiveLearningStrategy,
} from "./activeLearningApi";

interface ActiveLearningWorkspaceProps {
  project: Project;
  onOpenReviewQueue?: () => void;
}

const strategyDescriptions: Record<ActiveLearningStrategy, string> = {
  hybrid:
    "Balances uncertainty, model disagreement, rare-class presence, quality-control risk, and review state.",
  uncertainty:
    "Prioritizes images whose model proposals have low confidence or disagreement and therefore need human review.",
  rare_class:
    "Raises images containing classes that are underrepresented in the current reviewed annotation pool.",
  quality:
    "Prioritizes unresolved quality-control issues, incomplete provenance, disagreement, and other review risks.",
};

export function ActiveLearningWorkspace({
  project,
  onOpenReviewQueue,
}: ActiveLearningWorkspaceProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("Active learning round");
  const [strategy, setStrategy] = useState<ActiveLearningStrategy>("hybrid");
  const [requestedSize, setRequestedSize] = useState(50);
  const [selectedRoundId, setSelectedRoundId] = useState("");
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [selectedModelIds, setSelectedModelIds] = useState<string[]>([]);

  const roundsQuery = useQuery({
    queryKey: ["active-learning-rounds", project.id],
    queryFn: ({ signal }) => getActiveLearningRounds(project.id, signal),
  });
  const datasetVersionsQuery = useQuery({
    queryKey: ["dataset_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const modelsQuery = useQuery({
    queryKey: ["models", project.id, "active-learning"],
    queryFn: ({ signal }) => getModels(project.id, undefined, signal),
  });
  const selectedRound = roundsQuery.data?.find(
    (round) => round.id === selectedRoundId,
  );
  const selectionItems = useMemo(
    () => activeLearningSelectionItems(selectedRound),
    [selectedRound],
  );
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

  const createMutation = useMutation({
    mutationFn: () =>
      createActiveLearningRound(project.id, {
        name,
        dataset_version_id: datasetVersionId || null,
        strategy,
        requested_size: requestedSize,
        model_ids: selectedModelIds,
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
        queryClient.invalidateQueries({
          queryKey: ["dataset_versions", project.id],
        }),
      ]);
    },
  });

  function toggleModel(modelId: string) {
    setSelectedModelIds((current) =>
      current.includes(modelId)
        ? current.filter((item) => item !== modelId)
        : [...current, modelId],
    );
  }

  return (
    <section className="feature-workspace" data-testid="active-learning-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 7</p>
          <h3>Active learning</h3>
          <p>
            Freeze an explainable acquisition batch, review it through the existing
            queue, and turn verified human feedback into the next immutable dataset
            version.
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
            Input dataset
            <select
              value={datasetVersionId}
              onChange={(event) => setDatasetVersionId(event.target.value)}
            >
              <option value="">Current project state</option>
              {(datasetVersionsQuery.data ?? [])
                .filter((version) => version.status === "complete")
                .map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} · {version.name}
                  </option>
                ))}
            </select>
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
            </select>
          </label>
          <p className="annotation-helper">{strategyDescriptions[strategy]}</p>
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
          <fieldset>
            <legend>Model filter</legend>
            <p className="annotation-helper">
              Leave every model unchecked to use all available model signals.
            </p>
            {(modelsQuery.data ?? []).length === 0 ? (
              <p className="annotation-helper">No registered models are available.</p>
            ) : (
              (modelsQuery.data ?? []).map((model) => (
                <label key={model.id}>
                  <input
                    type="checkbox"
                    checked={selectedModelIds.includes(model.id)}
                    onChange={() => toggleModel(model.id)}
                  />{" "}
                  {model.display_name} · {model.task}
                </label>
              ))
            )}
          </fieldset>
          <button type="submit" disabled={createMutation.isPending || !name.trim()}>
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
            <>
              <dl className="metric-list">
                <div>
                  <dt>Selected</dt>
                  <dd>{selectedRound.selected_count}</dd>
                </div>
                <div>
                  <dt>Input dataset</dt>
                  <dd>
                    {selectedRound.dataset_version_id ? (
                      <code>{selectedRound.dataset_version_id.slice(0, 12)}</code>
                    ) : (
                      "Current project"
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Models</dt>
                  <dd>
                    {selectedRound.model_ids_json.length > 0
                      ? selectedRound.model_ids_json.length
                      : "All"}
                  </dd>
                </div>
                <div>
                  <dt>Review queue</dt>
                  <dd>
                    <code>{selectedRound.review_queue_id.slice(0, 12)}</code>
                  </dd>
                </div>
                <div>
                  <dt>Manifest</dt>
                  <dd>
                    <code>{selectedRound.selection_sha256.slice(0, 12)}</code>
                  </dd>
                </div>
              </dl>
              <p className="annotation-helper">
                Completing the round creates a new reviewed dataset snapshot. Queue
                items marked completed must also be marked Reviewed in the annotation
                workspace; skipped items do not enter the feedback requirement.
              </p>
            </>
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
              Complete round + snapshot feedback
            </button>
          </div>
          {completeMutation.error && (
            <p className="form-error">{completeMutation.error.message}</p>
          )}
        </div>

        <div className="panel-card">
          <h4>Why these images?</h4>
          {selectionItems.length > 0 ? (
            <div className="annotation-selection-list">
              {selectionItems.map((item, index) => (
                <div key={item.queue_item_id} className="annotation-selection-row">
                  <div>
                    <strong>#{index + 1}</strong>
                    <p className="annotation-helper">
                      {item.reason_summary || "Selected by the active-learning score."}
                    </p>
                    <small>Image {item.image_id.slice(0, 12)}</small>
                  </div>
                  <span>{item.score.toFixed(3)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p>Select a round to inspect its acquisition explanations.</p>
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
              {feedbackQuery.data.feedback_dataset_version_id && (
                <div className="annotation-selection-list">
                  <div className="annotation-selection-row">
                    <strong>Feedback dataset</strong>
                    <code>
                      {feedbackQuery.data.feedback_dataset_version_id.slice(0, 12)}
                    </code>
                  </div>
                  {feedbackQuery.data.feedback_manifest_sha256 && (
                    <div className="annotation-selection-row">
                      <strong>Dataset manifest</strong>
                      <code>
                        {feedbackQuery.data.feedback_manifest_sha256.slice(0, 12)}
                      </code>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <p>Select a round to inspect its human-feedback progress.</p>
          )}
        </div>
      </div>

      <details className="panel-card">
        <summary>
          <strong>Phase 8 · Advanced Provider Lab</strong>
        </summary>
        <AdvancedProviderWorkspace project={project} />
      </details>
      <details className="panel-card">
        <summary>
          <strong>Phase 9 · Project Interoperability</strong>
        </summary>
        <InteroperabilityWorkspace project={project} />
      </details>
      <details className="panel-card">
        <summary>
          <strong>Phase 10 · Workflow Graphs</strong>
        </summary>
        <WorkflowGraphWorkspace project={project} />
      </details>
    </section>
  );
}
