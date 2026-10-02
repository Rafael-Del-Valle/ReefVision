import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  buildTemporalPoseAssociations,
  correctTemporalPoseAssociation,
  createTemporalPoseIdentityBreak,
  getTemporalPoseSummary,
  temporalPoseExportUrl,
  type TemporalPoseAssociationDecision,
  type TemporalPoseObservation,
} from "./poseTemporalApi";

interface PoseTemporalReviewPanelProps {
  trackId: string;
  frameIndex: number;
  onFrameChange: (frameIndex: number) => void;
}

function latestObservations(
  observations: TemporalPoseObservation[],
): TemporalPoseObservation[] {
  const bySeries = new Map<string, TemporalPoseObservation>();
  for (const observation of observations) {
    const current = bySeries.get(observation.observation_series_id);
    if (!current || observation.revision > current.revision) {
      bySeries.set(observation.observation_series_id, observation);
    }
  }
  return [...bySeries.values()];
}

function latestDecisionMap(
  decisions: TemporalPoseAssociationDecision[],
): Map<string, TemporalPoseAssociationDecision> {
  const latest = new Map<string, TemporalPoseAssociationDecision>();
  for (const decision of decisions) {
    const current = latest.get(decision.observation_id);
    if (!current || decision.decision_revision > current.decision_revision) {
      latest.set(decision.observation_id, decision);
    }
  }
  return latest;
}

function shortIdentity(value: string | null): string {
  if (!value) return "unresolved";
  return value.length > 12 ? value.slice(0, 8) : value;
}

export function PoseTemporalReviewPanel({
  trackId,
  frameIndex,
  onFrameChange,
}: PoseTemporalReviewPanelProps) {
  const queryClient = useQueryClient();
  const [selectedIdentityByObservation, setSelectedIdentityByObservation] =
    useState<Record<string, string>>({});
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["pose-temporal-summary", trackId],
    queryFn: ({ signal }) => getTemporalPoseSummary(trackId, signal),
    enabled: Boolean(trackId),
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["pose-temporal-summary", trackId],
    });
  };

  const buildMutation = useMutation({
    mutationFn: (replaceExisting: boolean) =>
      buildTemporalPoseAssociations(trackId, {
        replace_existing: replaceExisting,
      }),
    onSuccess: async (result) => {
      setStatusMessage(
        "Built " +
          result.created_landmark_tracks +
          " landmark tracklets; " +
          result.unresolved_associations +
          " associations need review.",
      );
      await invalidate();
    },
    onError: (error) => {
      setStatusMessage(
        error instanceof Error ? error.message : "Temporal association failed.",
      );
    },
  });

  const correctionMutation = useMutation({
    mutationFn: (payload: {
      observationId: string;
      selectedTrackId: string | null;
      state: "confirmed" | "unresolved";
    }) =>
      correctTemporalPoseAssociation(payload.observationId, {
        selected_landmark_track_id: payload.selectedTrackId,
        association_state: payload.state,
        reason_code:
          payload.state === "unresolved"
            ? "scientist_marked_ambiguous"
            : "scientist_verified_identity",
      }),
    onSuccess: async () => {
      setStatusMessage("Temporal identity review saved.");
      await invalidate();
    },
    onError: (error) => {
      setStatusMessage(
        error instanceof Error ? error.message : "Identity review failed.",
      );
    },
  });

  const breakMutation = useMutation({
    mutationFn: (payload: {
      landmarkTrackId: string;
      observationId: string;
    }) =>
      createTemporalPoseIdentityBreak(payload.landmarkTrackId, {
        break_after_frame: frameIndex,
        reason: "ambiguous_crossing",
        note:
          "Identity continuity was manually broken while reviewing observation " +
          payload.observationId +
          ".",
      }),
    onSuccess: async () => {
      setStatusMessage("Identity break recorded and preserved in the audit trail.");
      await invalidate();
    },
    onError: (error) => {
      setStatusMessage(
        error instanceof Error ? error.message : "Identity break failed.",
      );
    },
  });

  const summary = summaryQuery.data;
  const observations = useMemo(
    () => latestObservations(summary?.observations ?? []),
    [summary?.observations],
  );
  const decisions = useMemo(
    () => latestDecisionMap(summary?.association_decisions ?? []),
    [summary?.association_decisions],
  );
  const availableFrames = useMemo(
    () =>
      [...new Set(observations.map((item) => item.frame_index))].sort(
        (first, second) => first - second,
      ),
    [observations],
  );
  const currentObservations = useMemo(
    () =>
      observations
        .filter((item) => item.frame_index === frameIndex)
        .sort(
          (first, second) =>
            first.semantic_label.localeCompare(second.semantic_label) ||
            first.occurrence_index - second.occurrence_index,
        ),
    [frameIndex, observations],
  );

  const currentFramePosition = availableFrames.findIndex(
    (frame) => frame === frameIndex,
  );
  const previousFrame =
    currentFramePosition > 0
      ? availableFrames[currentFramePosition - 1]
      : availableFrames.filter((frame) => frame < frameIndex).at(-1);
  const nextFrame =
    currentFramePosition >= 0
      ? availableFrames[currentFramePosition + 1]
      : availableFrames.find((frame) => frame > frameIndex);

  const unresolvedCount = [...decisions.values()].filter(
    (decision) => decision.association_state === "unresolved",
  ).length;

  return (
    <section className="management-card" aria-label="Temporal pose review">
      <p className="eyebrow">Temporal pose</p>
      <h3>Repeated-landmark identity review</h3>
      <p className="annotation-helper">
        Tracklet IDs describe temporal continuity, not anatomical numbering.
        Ambiguous identities remain unresolved until evidence or scientist review
        supports an assignment.
      </p>

      {summaryQuery.isLoading && <p>Loading temporal pose records…</p>}
      {summaryQuery.isError && (
        <p role="alert">
          {summaryQuery.error instanceof Error
            ? summaryQuery.error.message
            : "Temporal pose records could not be loaded."}
        </p>
      )}

      {summary && summary.observations.length === 0 && (
        <div className="workspace-guide compact">
          <div>
            <strong>No temporal identities yet</strong>
            <p className="annotation-helper">
              Build conservative tracklets from the persisted pose observations.
              Ambiguous crossings are left unresolved rather than forced.
            </p>
          </div>
          <button
            type="button"
            disabled={buildMutation.isPending}
            onClick={() => buildMutation.mutate(false)}
          >
            Build temporal identities
          </button>
        </div>
      )}

      {summary && summary.observations.length > 0 && (
        <>
          <div className="annotation-selection-list">
            <div className="annotation-selection-row">
              <strong>Landmark tracklets</strong>
              <span>{summary.landmark_tracks.length}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Unresolved associations</strong>
              <span>{unresolvedCount}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Identity breaks</strong>
              <span>{summary.identity_breaks.length}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Human corrections</strong>
              <span>{summary.corrections.length}</span>
            </div>
          </div>

          <div className="workspace-actions">
            <button
              type="button"
              disabled={previousFrame === undefined}
              onClick={() => {
                if (previousFrame !== undefined) onFrameChange(previousFrame);
              }}
            >
              Previous pose frame
            </button>
            <button
              type="button"
              disabled={nextFrame === undefined}
              onClick={() => {
                if (nextFrame !== undefined) onFrameChange(nextFrame);
              }}
            >
              Next pose frame
            </button>
            <a href={temporalPoseExportUrl(trackId, "csv")}>Export pose CSV</a>
            <a href={temporalPoseExportUrl(trackId, "json")}>
              Export pose audit JSON
            </a>
            <button
              type="button"
              disabled={buildMutation.isPending}
              onClick={() => buildMutation.mutate(true)}
            >
              Rebuild automatic associations
            </button>
          </div>

          <p className="annotation-helper">
            Frame {frameIndex} · {currentObservations.length} canonical landmark
            observations
          </p>

          {currentObservations.length === 0 ? (
            <p className="annotation-helper">
              No canonical pose observations are stored for this frame.
            </p>
          ) : (
            <div className="annotation-selection-list">
              {currentObservations.map((observation) => {
                const decision = decisions.get(observation.id);
                const compatibleTracks = summary.landmark_tracks.filter(
                  (track) =>
                    track.semantic_label === observation.semantic_label &&
                    track.pose_schema_id === observation.pose_schema_id &&
                    track.pose_schema_revision ===
                      observation.pose_schema_revision,
                );
                const selectedIdentity =
                  selectedIdentityByObservation[observation.id] ??
                  decision?.selected_landmark_track_id ??
                  "";
                const confidence =
                  decision?.association_confidence === null ||
                  decision?.association_confidence === undefined
                    ? "n/a"
                    : decision.association_confidence.toFixed(3);
                return (
                  <div
                    className="annotation-selection-row"
                    key={observation.id}
                  >
                    <div>
                      <strong>
                        {observation.semantic_label}{" "}
                        {observation.occurrence_index + 1}
                      </strong>
                      <div className="annotation-helper">
                        {observation.visibility_state} · landmark confidence{" "}
                        {observation.landmark_confidence === null
                          ? "n/a"
                          : observation.landmark_confidence.toFixed(3)}
                      </div>
                      <div className="annotation-helper">
                        {decision?.association_state ?? "unassociated"} ·
                        association confidence {confidence} ·{" "}
                        {decision?.verification_state ?? "unreviewed"}
                      </div>
                    </div>
                    <div>
                      <label>
                        Temporal identity
                        <select
                          aria-label={
                            "Temporal identity for " +
                            observation.semantic_label +
                            " " +
                            (observation.occurrence_index + 1)
                          }
                          value={selectedIdentity}
                          onChange={(event) =>
                            setSelectedIdentityByObservation((current) => ({
                              ...current,
                              [observation.id]: event.target.value,
                            }))
                          }
                        >
                          <option value="">Unresolved</option>
                          {compatibleTracks.map((track) => (
                            <option key={track.id} value={track.id}>
                              {track.semantic_label} · {shortIdentity(track.id)} ·{" "}
                              {track.lifecycle_state}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        disabled={
                          correctionMutation.isPending || !selectedIdentity
                        }
                        onClick={() =>
                          correctionMutation.mutate({
                            observationId: observation.id,
                            selectedTrackId: selectedIdentity || null,
                            state: "confirmed",
                          })
                        }
                      >
                        Confirm identity
                      </button>
                      <button
                        type="button"
                        disabled={correctionMutation.isPending}
                        onClick={() =>
                          correctionMutation.mutate({
                            observationId: observation.id,
                            selectedTrackId: null,
                            state: "unresolved",
                          })
                        }
                      >
                        Mark unresolved
                      </button>
                      {decision?.selected_landmark_track_id && (
                        <button
                          type="button"
                          disabled={breakMutation.isPending}
                          onClick={() =>
                            breakMutation.mutate({
                              landmarkTrackId:
                                decision.selected_landmark_track_id as string,
                              observationId: observation.id,
                            })
                          }
                        >
                          Break identity here
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {statusMessage && <p role="status">{statusMessage}</p>}
    </section>
  );
}
