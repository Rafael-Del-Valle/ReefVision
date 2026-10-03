import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  createPoseActiveLearningRound,
  getPoseActiveLearningCandidates,
  getPoseActiveLearningRounds,
  poseActiveLearningRetrainingManifestUrl,
  reviewPoseActiveLearningCandidate,
  type PoseActiveLearningCandidate,
  type PoseActiveLearningSelectionUnit,
} from "./poseActiveLearningApi";

interface PoseActiveLearningPanelProps {
  projectId: string;
  videoId: string;
  activeCandidateId?: string | null;
  onOpenCandidate: (candidate: PoseActiveLearningCandidate) => void;
}

function reasonLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export function PoseActiveLearningPanel({
  projectId,
  videoId,
  activeCandidateId = null,
  onOpenCandidate,
}: PoseActiveLearningPanelProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("Pose uncertainty review");
  const [selectionUnit, setSelectionUnit] =
    useState<PoseActiveLearningSelectionUnit>("frame");
  const [requestedSize, setRequestedSize] = useState(50);
  const [clipRadiusFrames, setClipRadiusFrames] = useState(5);
  const [minimumFrameSpacing, setMinimumFrameSpacing] = useState(5);
  const [selectedRoundId, setSelectedRoundId] = useState("");

  const roundsQuery = useQuery({
    queryKey: ["pose-active-learning-rounds", projectId, videoId],
    queryFn: ({ signal }) =>
      getPoseActiveLearningRounds(projectId, videoId, signal),
    enabled: Boolean(projectId && videoId),
  });

  useEffect(() => {
    if (!selectedRoundId && roundsQuery.data?.[0]) {
      setSelectedRoundId(roundsQuery.data[0].id);
    }
  }, [roundsQuery.data, selectedRoundId]);

  const candidatesQuery = useQuery({
    queryKey: ["pose-active-learning-candidates", selectedRoundId],
    queryFn: ({ signal }) =>
      getPoseActiveLearningCandidates(selectedRoundId, signal),
    enabled: Boolean(selectedRoundId),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createPoseActiveLearningRound(projectId, {
        name: name.trim() || "Pose uncertainty review",
        video_id: videoId,
        selection_unit: selectionUnit,
        requested_size: requestedSize,
        clip_radius_frames: clipRadiusFrames,
        minimum_frame_spacing: minimumFrameSpacing,
      }),
    onSuccess: async (round) => {
      setSelectedRoundId(round.id);
      await queryClient.invalidateQueries({
        queryKey: ["pose-active-learning-rounds", projectId, videoId],
      });
    },
  });

  const startReviewMutation = useMutation({
    mutationFn: (candidate: PoseActiveLearningCandidate) =>
      reviewPoseActiveLearningCandidate(candidate.id, {
        action: "start_review",
        reviewed_by: "local_user",
      }),
    onSuccess: async (candidate) => {
      await queryClient.invalidateQueries({
        queryKey: ["pose-active-learning-candidates", candidate.round_id],
      });
      onOpenCandidate(candidate);
    },
  });

  const skipMutation = useMutation({
    mutationFn: (candidate: PoseActiveLearningCandidate) =>
      reviewPoseActiveLearningCandidate(candidate.id, {
        action: "skip",
        reviewed_by: "local_user",
      }),
    onSuccess: async (candidate) => {
      await queryClient.invalidateQueries({
        queryKey: ["pose-active-learning-candidates", candidate.round_id],
      });
    },
  });

  const selectedRound = roundsQuery.data?.find(
    (item) => item.id === selectedRoundId,
  );

  const error =
    roundsQuery.error ??
    candidatesQuery.error ??
    createMutation.error ??
    startReviewMutation.error ??
    skipMutation.error;

  return (
    <section className="management-card" aria-label="Pose Active Learning">
      <p className="eyebrow">Pose Active Learning</p>
      <h3>Review the poses that teach the model the most</h3>
      <p className="annotation-helper">
        ReefVision ranks frames or clips using landmark confidence, visibility,
        temporal association uncertainty, repeated-landmark ambiguity, identity
        breaks, and motion anomalies. Selection never promotes a model
        prediction to verified ground truth.
      </p>

      <div className="annotation-selection-list">
        <label className="annotation-selection-row">
          Round name
          <input
            aria-label="Pose Active Learning round name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        <label className="annotation-selection-row">
          Selection unit
          <select
            aria-label="Pose Active Learning selection unit"
            value={selectionUnit}
            onChange={(event) =>
              setSelectionUnit(
                event.target.value as PoseActiveLearningSelectionUnit,
              )
            }
          >
            <option value="frame">Frame</option>
            <option value="clip">Short clip</option>
          </select>
        </label>

        <label className="annotation-selection-row">
          Review budget
          <input
            aria-label="Pose Active Learning review budget"
            type="number"
            min={1}
            max={1000}
            value={requestedSize}
            onChange={(event) => setRequestedSize(Number(event.target.value))}
          />
        </label>

        {selectionUnit === "clip" && (
          <label className="annotation-selection-row">
            Clip radius in frames
            <input
              aria-label="Pose Active Learning clip radius"
              type="number"
              min={0}
              value={clipRadiusFrames}
              onChange={(event) =>
                setClipRadiusFrames(Number(event.target.value))
              }
            />
          </label>
        )}

        <label className="annotation-selection-row">
          Minimum frame spacing
          <input
            aria-label="Pose Active Learning minimum frame spacing"
            type="number"
            min={0}
            value={minimumFrameSpacing}
            onChange={(event) =>
              setMinimumFrameSpacing(Number(event.target.value))
            }
          />
        </label>
      </div>

      <button
        type="button"
        disabled={createMutation.isPending}
        onClick={() => createMutation.mutate()}
      >
        {createMutation.isPending
          ? "Selecting pose review candidates..."
          : "Create pose acquisition round"}
      </button>

      {(roundsQuery.data ?? []).length > 0 && (
        <label>
          Acquisition round
          <select
            aria-label="Pose Active Learning round"
            value={selectedRoundId}
            onChange={(event) => setSelectedRoundId(event.target.value)}
          >
            {(roundsQuery.data ?? []).map((round) => (
              <option key={round.id} value={round.id}>
                {round.name} ? {round.selected_count} selected ? {round.status}
              </option>
            ))}
          </select>
        </label>
      )}

      {selectedRound && (
        <div className="workspace-guide compact">
          <div>
            <strong>
              {selectedRound.selection_unit} acquisition ?{" "}
              {selectedRound.selected_count} candidates
            </strong>
            <p className="annotation-helper">
              Selection manifest {selectedRound.selection_sha256.slice(0, 12)}?
            </p>
            <a href={poseActiveLearningRetrainingManifestUrl(selectedRound.id)}>
              Inspect retraining provenance manifest
            </a>
          </div>
        </div>
      )}

      {(candidatesQuery.data ?? []).map((candidate) => (
        <div
          className="workspace-guide compact"
          key={candidate.id}
          data-testid={`pose-al-candidate-${candidate.id}`}
        >
          <div>
            <strong>
              Frame {candidate.focus_frame} ? uncertainty{" "}
              {(candidate.acquisition_score * 100).toFixed(1)}%
            </strong>

            {candidate.frame_start !== candidate.frame_end && (
              <p className="annotation-helper">
                Review clip {candidate.frame_start}?{candidate.frame_end}
              </p>
            )}

            <p className="annotation-helper">
              Reasons:{" "}
              {candidate.reason_codes_json.length > 0
                ? candidate.reason_codes_json.map(reasonLabel).join(" ? ")
                : "composite score"}
            </p>

            <p className="annotation-helper">
              Landmark confidence risk{" "}
              {(
                (candidate.score_components_json.low_landmark_confidence ?? 0) *
                100
              ).toFixed(1)}
              % ? repeated-landmark ambiguity{" "}
              {(
                (candidate.score_components_json.repeated_landmark_ambiguity ??
                  0) * 100
              ).toFixed(1)}
              % ? identity-break signal{" "}
              {(
                (candidate.score_components_json.identity_break_signal ?? 0) *
                100
              ).toFixed(1)}
              %
            </p>

            <p className="annotation-helper">
              Provenance {candidate.provenance_sha256.slice(0, 12)}? ? source
              track revision {candidate.source_track_revision} ?{" "}
              {candidate.review_status}
            </p>

            {candidate.id === activeCandidateId && (
              <p role="status">
                Open in Pose Annotation Editor. Saving the reviewed pose
                verifies this candidate.
              </p>
            )}

            <div className="workspace-actions">
              {candidate.review_status !== "verified" &&
                candidate.review_status !== "skipped" && (
                  <button
                    type="button"
                    disabled={startReviewMutation.isPending}
                    onClick={() => startReviewMutation.mutate(candidate)}
                  >
                    Review in Pose Annotation Editor
                  </button>
                )}

              {candidate.review_status !== "verified" &&
                candidate.review_status !== "skipped" && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={skipMutation.isPending}
                    onClick={() => skipMutation.mutate(candidate)}
                  >
                    Skip candidate
                  </button>
                )}
            </div>
          </div>
        </div>
      ))}

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </section>
  );
}
