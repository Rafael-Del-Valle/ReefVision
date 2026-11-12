import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  cancelPoseIdentityJob,
  createPoseIdentityCorrection,
  createPoseIdentityRun,
  getPoseIdentityCorrections,
  getPoseIdentityDecisions,
  getPoseIdentityIdentities,
  getPoseIdentityObservations,
  getPoseIdentityReviewQueue,
  listPoseIdentityRuns,
  poseIdentityExportUrl,
  type PoseIdentityCorrectionAction,
} from "./poseIdentityTrackingApi";
import {
  poseLandmarkSchemaFromMetadata,
  type VideoTrackRecord,
} from "./videoApi";

interface PoseIdentityReviewPanelProps {
  projectId: string;
  videoId: string;
  frameIndex: number;
  tracks: VideoTrackRecord[];
  onFrameChange: (frameIndex: number) => void;
}

function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function score(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(3);
}

export function PoseIdentityReviewPanel({
  projectId,
  videoId,
  frameIndex,
  tracks,
  onFrameChange,
}: PoseIdentityReviewPanelProps) {
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState("");
  const [submittedJobId, setSubmittedJobId] = useState<string | null>(null);
  const [submittedRunId, setSubmittedRunId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [action, setAction] =
    useState<PoseIdentityCorrectionAction>("reassign");
  const [targetId, setTargetId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [reason, setReason] = useState("");
  const [frameStart, setFrameStart] = useState("");
  const [frameEnd, setFrameEnd] = useState("");

  const runsQuery = useQuery({
    queryKey: ["pose-identity-runs", projectId],
    queryFn: ({ signal }) => listPoseIdentityRuns(projectId, signal),
    refetchInterval: 2000,
  });
  const runs = useMemo(
    () => (runsQuery.data ?? []).filter((run) => run.video_id === videoId),
    [runsQuery.data, videoId],
  );
  useEffect(() => {
    if (!selectedRunId && runs[0]) setSelectedRunId(runs[0].id);
  }, [runs, selectedRunId]);
  const selectedRun = runs.find((run) => run.id === selectedRunId);
  const persistedActiveJobId =
    selectedRun && ["queued", "running"].includes(selectedRun.status)
      ? selectedRun.source_job_id
      : null;
  const cancellableJobId =
    persistedActiveJobId ??
    (submittedRunId === selectedRunId ? submittedJobId : null);
  useEffect(() => {
    if (
      submittedJobId &&
      selectedRun?.source_job_id === submittedJobId &&
      ["completed", "failed", "cancelled"].includes(selectedRun.status)
    ) {
      setSubmittedJobId(null);
      setSubmittedRunId(null);
    }
  }, [selectedRun?.source_job_id, selectedRun?.status, submittedJobId]);
  const identitiesQuery = useQuery({
    queryKey: ["pose-identity-identities", selectedRunId],
    queryFn: ({ signal }) => getPoseIdentityIdentities(selectedRunId, signal),
    enabled: Boolean(selectedRunId),
  });
  const observationsQuery = useQuery({
    queryKey: ["pose-identity-observations", selectedRunId],
    queryFn: ({ signal }) => getPoseIdentityObservations(selectedRunId, signal),
    enabled: Boolean(selectedRunId),
  });
  const decisionsQuery = useQuery({
    queryKey: ["pose-identity-decisions", selectedRunId],
    queryFn: ({ signal }) => getPoseIdentityDecisions(selectedRunId, signal),
    enabled: Boolean(selectedRunId),
  });
  const reviewQuery = useQuery({
    queryKey: ["pose-identity-review", selectedRunId],
    queryFn: ({ signal }) => getPoseIdentityReviewQueue(selectedRunId, signal),
    enabled: Boolean(selectedRunId),
  });
  const correctionsQuery = useQuery({
    queryKey: ["pose-identity-corrections", selectedRunId],
    queryFn: ({ signal }) => getPoseIdentityCorrections(selectedRunId, signal),
    enabled: Boolean(selectedRunId),
  });
  useEffect(() => {
    if (!selectedRunId || selectedRun?.status !== "completed") return;
    void Promise.all(
      [
        "pose-identity-identities",
        "pose-identity-observations",
        "pose-identity-decisions",
        "pose-identity-review",
        "pose-identity-corrections",
      ].map((key) =>
        queryClient.invalidateQueries({ queryKey: [key, selectedRunId] }),
      ),
    );
  }, [queryClient, selectedRun?.status, selectedRunId]);

  const poseTracks = tracks.filter((track) =>
    Boolean(poseLandmarkSchemaFromMetadata(track.metadata_json)),
  );
  const schemas = poseTracks.map((track) =>
    poseLandmarkSchemaFromMetadata(track.metadata_json),
  );
  const firstSchema = schemas[0];
  const compatibleTracks = Boolean(
    firstSchema?.schema_id &&
    firstSchema.schema_revision &&
    firstSchema.content_hash &&
    schemas.every(
      (schema) =>
        schema?.schema_id === firstSchema.schema_id &&
        schema?.schema_revision === firstSchema.schema_revision &&
        schema?.content_hash === firstSchema.content_hash,
    ),
  );

  const invalidateRun = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["pose-identity-runs", projectId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-identity-identities", selectedRunId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-identity-observations", selectedRunId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-identity-decisions", selectedRunId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-identity-review", selectedRunId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["pose-identity-corrections", selectedRunId],
      }),
    ]);
  };

  const startMutation = useMutation({
    mutationFn: () => {
      if (
        !compatibleTracks ||
        !firstSchema?.schema_id ||
        !firstSchema.content_hash
      ) {
        throw new Error(
          "Pose tracks must share one complete landmark schema binding.",
        );
      }
      return createPoseIdentityRun(projectId, {
        video_id: videoId,
        source_track_ids: poseTracks.map((track) => track.id),
        pose_schema_id: firstSchema.schema_id,
        pose_schema_revision: firstSchema.schema_revision ?? 1,
        pose_schema_content_hash: firstSchema.content_hash,
        device: "auto",
        parameters: {
          max_gap_frames: 5,
          max_normalized_distance: 1.5,
          acceptance_threshold: 0.75,
          low_confidence_threshold: 0.6,
        },
      });
    },
    onSuccess: async (job) => {
      setSubmittedJobId(job.id);
      const runId = job.result_json?.run_id;
      if (runId) {
        setSubmittedRunId(runId);
        setSelectedRunId(runId);
      }
      setMessage(
        "Identity association queued; progress is persisted by the background job.",
      );
      await queryClient.invalidateQueries({
        queryKey: ["pose-identity-runs", projectId],
      });
    },
    onError: (error) =>
      setMessage(
        error instanceof Error ? error.message : "Association failed.",
      ),
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelPoseIdentityJob(cancellableJobId ?? ""),
    onSuccess: () => setMessage("Identity association cancellation requested."),
    onError: (error) =>
      setMessage(
        error instanceof Error ? error.message : "Cancellation failed.",
      ),
  });
  const correctionMutation = useMutation({
    mutationFn: (payload: {
      action: PoseIdentityCorrectionAction;
      target_type: "observation" | "identity" | "range";
      target_id: string;
      destination_identity_id: string | null;
      frame_start: number | null;
      frame_end: number | null;
      reason: string | null;
      actor: string;
    }) => createPoseIdentityCorrection(selectedRunId, payload),
    onSuccess: async (correction) => {
      setMessage(
        `Identity correction saved as revision ${correction.revision}.`,
      );
      await invalidateRun();
    },
    onError: (error) =>
      setMessage(error instanceof Error ? error.message : "Correction failed."),
  });

  const identities = identitiesQuery.data ?? [];
  const observations = observationsQuery.data ?? [];
  const observationsAtFrame = observations.filter(
    (item) => item.frame_index === frameIndex,
  );
  const selectedReviewObservation = reviewQuery.data?.[0];
  const selectedDecision = decisionsQuery.data?.find(
    (item) =>
      item.observation_id === selectedReviewObservation?.id && item.selected,
  );
  const correctionUsesObservation =
    action === "reassign" || action === "reject";
  const targetOptions = correctionUsesObservation ? observations : identities;

  function saveCorrection() {
    if (!targetId) {
      setMessage("Choose a correction target.");
      return;
    }
    const needsDestination = ["reassign", "merge", "swap"].includes(action);
    if (needsDestination && !destinationId) {
      setMessage("Choose a destination identity.");
      return;
    }
    correctionMutation.mutate({
      action,
      target_type: correctionUsesObservation ? "observation" : "identity",
      target_id: targetId,
      destination_identity_id: needsDestination ? destinationId : null,
      frame_start: frameStart === "" ? null : Number(frameStart),
      frame_end: frameEnd === "" ? null : Number(frameEnd),
      reason: reason.trim() || null,
      actor: "local_user",
    });
  }

  function quickReview(identityId: string, reviewAction: "accept" | "reject") {
    correctionMutation.mutate({
      action: reviewAction,
      target_type: "identity",
      target_id: identityId,
      destination_identity_id: null,
      frame_start: null,
      frame_end: null,
      reason: `${reviewAction}ed in Video Tracking Workspace`,
      actor: "local_user",
    });
  }

  return (
    <section
      className="workspace-guide"
      role="region"
      aria-label="Animal identity tracking"
    >
      <div>
        <strong>Multi-animal identity tracking</strong>
        <p className="annotation-helper">
          Provider poses remain immutable. Association and every scientist
          correction are stored as auditable revisions in source-image
          coordinates.
        </p>
      </div>
      <div className="toolbar-row">
        <button
          type="button"
          disabled={!compatibleTracks || startMutation.isPending}
          onClick={() => startMutation.mutate()}
        >
          Associate individuals
        </button>
        {cancellableJobId && (
          <button type="button" onClick={() => cancelMutation.mutate()}>
            Cancel association
          </button>
        )}
        <label>
          Identity run
          <select
            value={selectedRunId}
            onChange={(event) => setSelectedRunId(event.target.value)}
          >
            <option value="">Select a run</option>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {run.status} · revision {run.revision} · {run.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!compatibleTracks && (
        <p className="error-text">
          Pose tracks must share one compatible landmark schema.
        </p>
      )}
      {selectedRun && (
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>
              {selectedRun.pose_schema_id} · revision{" "}
              {selectedRun.pose_schema_revision}
            </strong>
            <span>
              {selectedRun.source_coordinate_space} · {selectedRun.source_width}{" "}
              × {selectedRun.source_height}
            </span>
          </div>
          <div className="annotation-selection-row">
            <span>
              {selectedRun.algorithm} {selectedRun.algorithm_version}
            </span>
            <span>
              run revision {selectedRun.revision} · {selectedRun.status}
            </span>
          </div>
          <div className="annotation-selection-row">
            <span>
              parameters {selectedRun.parameters_sha256.slice(0, 12)}…
            </span>
            <span>input {selectedRun.input_manifest_sha256.slice(0, 12)}…</span>
          </div>
        </div>
      )}
      <div className="annotation-selection-list">
        {identities.map((identity) => (
          <div className="annotation-selection-row" key={identity.id}>
            <button
              type="button"
              onClick={() => onFrameChange(identity.first_frame)}
            >
              {identity.stable_identity_key}
            </button>
            <span>{identity.display_name ?? "Unnamed animal"}</span>
            <span>
              {identity.origin === "scientist"
                ? "Scientist confirmed"
                : titleCase(identity.verification_state)}
            </span>
            <span>
              frames {identity.first_frame}–{identity.last_frame ?? "active"}
            </span>
            <button
              type="button"
              onClick={() => quickReview(identity.id, "accept")}
            >
              Accept
            </button>
            <button
              type="button"
              onClick={() => quickReview(identity.id, "reject")}
            >
              Reject
            </button>
          </div>
        ))}
      </div>
      <div className="pose-identity-skeletons">
        {observationsAtFrame.map((observation) => {
          const identity = identities.find(
            (item) => item.id === observation.animal_identity_id,
          );
          const visibleLandmarks = observation.landmarks_json.filter(
            (landmark) =>
              landmark.x != null &&
              landmark.y != null &&
              !["absent", "out_of_frame"].includes(landmark.visibility),
          );
          const landmarkById = new Map(
            visibleLandmarks.map((landmark) => [
              landmark.landmark_id,
              landmark,
            ]),
          );
          return (
            <svg
              key={observation.id}
              role="img"
              aria-label={`Animal ${identity?.stable_identity_key ?? "unresolved"} skeleton at frame ${frameIndex}`}
              viewBox={`0 0 ${selectedRun?.source_width ?? 1} ${selectedRun?.source_height ?? 1}`}
              width="220"
              height="124"
            >
              <rect
                x={observation.bbox_json[0]}
                y={observation.bbox_json[1]}
                width={observation.bbox_json[2]}
                height={observation.bbox_json[3]}
                fill="none"
                stroke="currentColor"
              />
              {(firstSchema?.edges ?? []).map((edge) => {
                const from = landmarkById.get(edge.from_id);
                const to = landmarkById.get(edge.to_id);
                return from?.x == null ||
                  from.y == null ||
                  to?.x == null ||
                  to.y == null ? null : (
                  <line
                    key={`${edge.from_id}-${edge.to_id}`}
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke="currentColor"
                  />
                );
              })}
              {visibleLandmarks.map((landmark) =>
                landmark.x == null || landmark.y == null ? null : (
                  <circle
                    key={landmark.landmark_id}
                    cx={landmark.x}
                    cy={landmark.y}
                    r="2"
                  />
                ),
              )}
              <text
                x={observation.bbox_json[0]}
                y={Math.max(8, observation.bbox_json[1] - 2)}
              >
                {identity?.stable_identity_key ?? "unresolved"}
              </text>
            </svg>
          );
        })}
      </div>
      <h5>Low-confidence review ({reviewQuery.data?.length ?? 0})</h5>
      {selectedReviewObservation && selectedDecision && (
        <div className="annotation-selection-list">
          <button
            type="button"
            onClick={() => onFrameChange(selectedReviewObservation.frame_index)}
          >
            Frame {selectedReviewObservation.frame_index} · confidence{" "}
            {score(selectedReviewObservation.association_confidence)}
          </button>
          <span>
            motion {score(selectedDecision.score_components_json.motion_cost)}
          </span>
          <span>
            proximity{" "}
            {score(selectedDecision.score_components_json.proximity_cost)}
          </span>
          <span>
            overlap {score(selectedDecision.score_components_json.overlap_cost)}
          </span>
          <span>
            landmark{" "}
            {score(selectedDecision.score_components_json.landmark_cost)}
          </span>
          <span>threshold {score(selectedDecision.acceptance_threshold)}</span>
        </div>
      )}
      <div className="form-grid two-column">
        <label>
          Correction action
          <select
            value={action}
            onChange={(event) =>
              setAction(event.target.value as PoseIdentityCorrectionAction)
            }
          >
            {(
              [
                "reassign",
                "split",
                "merge",
                "swap",
                "accept",
                "reject",
              ] as const
            ).map((value) => (
              <option key={value} value={value}>
                {titleCase(value)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {correctionUsesObservation
            ? "Observation to correct"
            : "Identity to correct"}
          <select
            aria-label={
              correctionUsesObservation
                ? "Observation to correct"
                : "Identity to correct"
            }
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
          >
            <option value="">Choose target</option>
            {targetOptions.map((item) => (
              <option key={item.id} value={item.id}>
                {"stable_identity_key" in item
                  ? item.stable_identity_key
                  : `Frame ${item.frame_index} · ${item.id.slice(0, 8)}`}
              </option>
            ))}
          </select>
        </label>
        <label>
          Destination identity
          <select
            value={destinationId}
            onChange={(event) => setDestinationId(event.target.value)}
          >
            <option value="">Choose identity</option>
            {identities.map((identity) => (
              <option key={identity.id} value={identity.id}>
                {identity.stable_identity_key}
              </option>
            ))}
          </select>
        </label>
        <label>
          Frame start
          <input
            type="number"
            min="0"
            value={frameStart}
            onChange={(event) => setFrameStart(event.target.value)}
          />
        </label>
        <label>
          Frame end
          <input
            type="number"
            min="0"
            value={frameEnd}
            onChange={(event) => setFrameEnd(event.target.value)}
          />
        </label>
        <label>
          Correction reason
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      </div>
      <button
        type="button"
        disabled={correctionMutation.isPending}
        onClick={saveCorrection}
      >
        Save identity correction
      </button>
      <div className="toolbar-row">
        {selectedRunId && (
          <a href={poseIdentityExportUrl(selectedRunId, "json")}>
            Export identity JSON
          </a>
        )}
        {selectedRunId && (
          <a href={poseIdentityExportUrl(selectedRunId, "csv")}>
            Export identity CSV
          </a>
        )}
      </div>
      <h5>Correction history ({correctionsQuery.data?.length ?? 0})</h5>
      {(correctionsQuery.data ?? []).map((correction) => (
        <p key={correction.id}>
          Revision {correction.revision} · {titleCase(correction.action)} ·{" "}
          {correction.actor}
        </p>
      ))}
      {message && <p role="status">{message}</p>}
      {(runsQuery.error ||
        identitiesQuery.error ||
        observationsQuery.error) && (
        <p className="error-text">
          Identity tracking data could not be loaded.
        </p>
      )}
    </section>
  );
}
