import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { Project } from "../../api/client";
import { AdvancedProviderWorkspace } from "../advanced-providers/AdvancedProviderWorkspace";
import {
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

export function ActiveLearningWorkspace({
  project,
  onOpenReviewQueue,
}: ActiveLearningWorkspaceProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("Active learning round");
  const [strategy, setStrategy] = useState<ActiveLearningStrategy>("hybrid");
  const [requestedSize, setRequestedSize] = useState(50);
  const [selectedRoundId, setSelectedRoundId] = useState("");

  const roundsQuery = useQuery({
    queryKey: ["active-learning-rounds", project.id],
    queryFn: ({ signal }) => getActiveLearningRounds(project.id, signal),
  });
  const selectedRound = roundsQuery.data?.find(
    (round) => round.id === selectedRoundId,
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
        strategy,
        requested_size: requestedSize,
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
            queue, and measure how much human feedback the round produced.
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
            </select>
          </label>
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
            <dl className="metric-list">
              <div><dt>Selected</dt><dd>{selectedRound.selected_count}</dd></div>
              <div><dt>Review queue</dt><dd><code>{selectedRound.review_queue_id}</code></dd></div>
              <div><dt>Manifest</dt><dd><code>{selectedRound.selection_sha256.slice(0, 12)}</code></dd></div>
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
          <h4>Feedback progress</h4>
          {feedbackQuery.data ? (
            <>
              <progress max={1} value={feedbackQuery.data.completion_fraction} />
              <p>{(feedbackQuery.data.completion_fraction * 100).toFixed(1)}% terminal</p>
              <dl className="metric-list">
                <div><dt>Pending</dt><dd>{feedbackQuery.data.pending_count}</dd></div>
                <div><dt>In progress</dt><dd>{feedbackQuery.data.in_progress_count}</dd></div>
                <div><dt>Completed</dt><dd>{feedbackQuery.data.completed_count}</dd></div>
                <div><dt>Skipped</dt><dd>{feedbackQuery.data.skipped_count}</dd></div>
              </dl>
            </>
          ) : (
            <p>Select a round to inspect its human-feedback progress.</p>
          )}
        </div>
      </div>

      <details className="panel-card">
        <summary><strong>Phase 8 · Advanced Provider Lab</strong></summary>
        <AdvancedProviderWorkspace project={project} />
      </details>
    </section>
  );
}
