import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  createPoseActiveLearningRound,
  createPoseTrainingDataset,
  getPoseActiveLearningCandidates,
  getPoseActiveLearningRounds,
  poseActiveLearningRetrainingManifestUrl,
  poseTrainingDatasetExportUrl,
  poseTrainingDatasetNativePackageUrl,
  reviewPoseActiveLearningCandidate,
  type PoseActiveLearningCandidate,
  type PoseActiveLearningSelectionMode,
  type PoseActiveLearningSelectionUnit,
  type PoseTrainingDataset,
  type PoseTrainingExportFormat,
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
  const [selectionMode, setSelectionMode] =
    useState<PoseActiveLearningSelectionMode>("uncertainty");
  const [diversityWeight, setDiversityWeight] = useState(0.25);
  const [selectedRoundId, setSelectedRoundId] = useState("");
  const [frozenDataset, setFrozenDataset] =
    useState<PoseTrainingDataset | null>(null);
  const [trainingExportFormat, setTrainingExportFormat] =
    useState<PoseTrainingExportFormat>("coco");

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
        selection_mode: selectionMode,
        diversity_weight: diversityWeight,
      }),
    onSuccess: async (round) => {
      setSelectedRoundId(round.id);
      await queryClient.invalidateQueries({
        queryKey: ["pose-active-learning-rounds", projectId, videoId],
      });
    },
  });

  const freezeDatasetMutation = useMutation({
    mutationFn: (roundId: string) =>
      createPoseTrainingDataset(roundId, {
        created_by: "local_user",
      }),
    onSuccess: (dataset) => {
      setFrozenDataset(dataset);
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
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["pose-active-learning-candidates", candidate.round_id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["pose-active-learning-rounds", projectId, videoId],
        }),
      ]);
    },
  });

  const selectedRound = roundsQuery.data?.find(
    (item) => item.id === selectedRoundId,
  );

  const error =
    roundsQuery.error ??
    candidatesQuery.error ??
    createMutation.error ??
    freezeDatasetMutation.error ??
    startReviewMutation.error ??
    skipMutation.error;

  return (
    <section className="management-card" aria-label="Pose Active Learning">
      <p className="eyebrow">Pose Active Learning</p>
      <h3>Review the poses that teach the model the most</h3>
      <p className="annotation-helper">
        ReefVision ranks frames or clips using landmark confidence, visibility,
        temporal association uncertainty, repeated-landmark ambiguity, identity
        breaks, motion anomalies, cross-model disagreement, and provider-native
        uncertainty evidence when it is actually available. Selection never
        promotes a model prediction to verified ground truth.
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

        <label className="annotation-selection-row">
          Acquisition balance
          <select
            aria-label="Pose Active Learning acquisition balance"
            value={selectionMode}
            onChange={(event) =>
              setSelectionMode(
                event.target.value as PoseActiveLearningSelectionMode,
              )
            }
          >
            <option value="uncertainty">Highest uncertainty</option>
            <option value="uncertainty_diverse">
              Uncertainty + pose diversity
            </option>
          </select>
        </label>

        {selectionMode === "uncertainty_diverse" && (
          <>
            <label className="annotation-selection-row">
              Pose diversity weight
              <input
                aria-label="Pose Active Learning diversity weight"
                type="number"
                min={0}
                max={0.75}
                step={0.05}
                value={diversityWeight}
                onChange={(event) =>
                  setDiversityWeight(Number(event.target.value))
                }
              />
            </label>
            <p className="annotation-helper">
              Diversity uses a deterministic max-min comparison of canonical
              pose configurations. Repeated landmarks are compared without
              assuming occurrence-index identity.
            </p>
          </>
        )}
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
                {round.name} | {round.selected_count} selected | {round.status}
              </option>
            ))}
          </select>
        </label>
      )}

      {selectedRound && (
        <div className="workspace-guide compact">
          <div>
            <strong>
              {selectedRound.selection_unit} acquisition |{" "}
              {selectedRound.selected_count} candidates
            </strong>
            <p className="annotation-helper">
              Selection manifest {selectedRound.selection_sha256.slice(0, 12)}
              ...
            </p>
            <a href={poseActiveLearningRetrainingManifestUrl(selectedRound.id)}>
              Inspect retraining provenance manifest
            </a>

            <div className="workspace-actions">
              <button
                type="button"
                disabled={
                  selectedRound.status !== "complete" ||
                  freezeDatasetMutation.isPending
                }
                onClick={() => freezeDatasetMutation.mutate(selectedRound.id)}
              >
                {freezeDatasetMutation.isPending
                  ? "Freezing verified poses..."
                  : "Freeze verified training dataset"}
              </button>
            </div>

            {selectedRound.status !== "complete" && (
              <p className="annotation-helper">
                Finish or skip every acquisition candidate before freezing
                training truth.
              </p>
            )}
          </div>
        </div>
      )}

      {frozenDataset && (
        <div
          className="workspace-guide compact"
          data-testid="pose-training-dataset"
        >
          <div>
            <strong>
              Immutable pose dataset | {frozenDataset.item_count} verified
              {frozenDataset.item_count === 1 ? " pose" : " poses"}
            </strong>
            <p className="annotation-helper">
              Dataset manifest {frozenDataset.manifest_sha256.slice(0, 12)}... |
              schema {frozenDataset.pose_schema_id} revision{" "}
              {frozenDataset.pose_schema_revision}
            </p>
            <p className="annotation-helper">
              This snapshot contains scientist-verified pose truth only. Later
              edits to the live track do not mutate the frozen dataset.
            </p>
            <a href={poseTrainingDatasetNativePackageUrl(frozenDataset.id)}>
              Download immutable ReefVision pose dataset
            </a>

            <label className="annotation-selection-row">
              Retraining / interoperability format
              <select
                aria-label="Pose training export format"
                value={trainingExportFormat}
                onChange={(event) =>
                  setTrainingExportFormat(
                    event.target.value as PoseTrainingExportFormat,
                  )
                }
              >
                <option value="coco">COCO Keypoints</option>
                <option value="ultralytics_pose">Ultralytics Pose</option>
                <option value="dlc_csv">DeepLabCut CSV</option>
                <option value="slp">SLEAP .slp</option>
                <option value="nwb">NWB</option>
              </select>
            </label>

            <a
              href={poseTrainingDatasetExportUrl(
                frozenDataset.id,
                trainingExportFormat,
              )}
            >
              Download retraining-ready pose export
            </a>

            <p className="annotation-helper">
              External formats cannot represent every ReefVision scientific
              audit field. The export ZIP includes a conversion/loss manifest,
              exact source-frame PNGs, repeated-landmark mapping, and the full
              frozen review/acquisition provenance.
            </p>
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
              Frame {candidate.focus_frame} | uncertainty{" "}
              {(candidate.acquisition_score * 100).toFixed(1)}%
            </strong>

            {candidate.frame_start !== candidate.frame_end && (
              <p className="annotation-helper">
                Review clip {candidate.frame_start}-{candidate.frame_end}
              </p>
            )}

            <p className="annotation-helper">
              Reasons:{" "}
              {candidate.reason_codes_json.length > 0
                ? candidate.reason_codes_json.map(reasonLabel).join(" | ")
                : "composite score"}
            </p>

            <p className="annotation-helper">
              Landmark confidence risk{" "}
              {(
                (candidate.score_components_json.low_landmark_confidence ?? 0) *
                100
              ).toFixed(1)}
              % | repeated-landmark ambiguity{" "}
              {(
                (candidate.score_components_json.repeated_landmark_ambiguity ??
                  0) * 100
              ).toFixed(1)}
              % | identity-break signal{" "}
              {(
                (candidate.score_components_json.identity_break_signal ?? 0) *
                100
              ).toFixed(1)}
              %
            </p>

            <p className="annotation-helper">
              Model disagreement:{" "}
              {candidate.score_components_json.model_disagreement === undefined
                ? "not available"
                : `${(
                    candidate.score_components_json.model_disagreement * 100
                  ).toFixed(1)}%`}
              {" | "}Heatmap entropy:{" "}
              {candidate.score_components_json.heatmap_entropy === undefined
                ? "not exposed by this provider"
                : `${(
                    candidate.score_components_json.heatmap_entropy * 100
                  ).toFixed(1)}%`}
              {" | "}PAF ambiguity:{" "}
              {candidate.score_components_json.paf_ambiguity === undefined
                ? "not exposed by this provider"
                : `${(
                    candidate.score_components_json.paf_ambiguity * 100
                  ).toFixed(1)}%`}
            </p>

            <p className="annotation-helper">
              Provenance {candidate.provenance_sha256.slice(0, 12)}... | source
              track revision {candidate.source_track_revision} |{" "}
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
