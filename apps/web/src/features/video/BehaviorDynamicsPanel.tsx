import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  behaviorExportUrl,
  createBehaviorBout,
  createBehaviorEthogram,
  getBehaviorBouts,
  getBehaviorDynamics,
  getBehaviorEthograms,
  getBehaviorModels,
  getBehaviorPredictions,
  reviewBehaviorPrediction,
  runBehaviorPredictions,
  trainBehaviorModel,
  type BehaviorFeaturePreset,
  type BehaviorPrediction,
} from "./behaviorDynamicsApi";

interface BehaviorDynamicsPanelProps {
  projectId: string;
  trackId: string;
  frameIndex: number;
  onFrameChange?: (frameIndex: number) => void;
}

interface PredictionEdit {
  stateId: string;
  startFrame: number;
  endFrame: number;
}

function parseStates(
  text: string,
  channel: string,
): Array<{ code: string; label: string; channel: string }> {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [rawCode, ...labelParts] = line.split("=");
      const code = rawCode.trim();
      const label = labelParts.join("=").trim() || code;
      if (!code) throw new Error("Every behavior state needs a code");
      return { code, label, channel: channel.trim() };
    });
}

export function BehaviorDynamicsPanel({
  projectId,
  trackId,
  frameIndex,
  onFrameChange,
}: BehaviorDynamicsPanelProps) {
  const queryClient = useQueryClient();
  const [selectedEthogramId, setSelectedEthogramId] = useState("");
  const [ethogramName, setEthogramName] = useState("Behavior ethogram");
  const [ethogramChannel, setEthogramChannel] = useState("behavior");
  const [stateLines, setStateLines] = useState("rest=Rest\nactive=Active");
  const [selectedStateId, setSelectedStateId] = useState("");
  const [boutStart, setBoutStart] = useState(frameIndex);
  const [boutEnd, setBoutEnd] = useState(frameIndex);
  const [modelName, setModelName] = useState("Behavior centroid model");
  const [featurePreset, setFeaturePreset] =
    useState<BehaviorFeaturePreset>("track_only");
  const [selectedModelId, setSelectedModelId] = useState("");
  const [windowFrames, setWindowFrames] = useState(30);
  const [strideFrames, setStrideFrames] = useState(30);
  const [predictionEdits, setPredictionEdits] = useState<
    Record<string, PredictionEdit>
  >({});
  const [validationError, setValidationError] = useState<string | null>(null);

  const ethogramsQuery = useQuery({
    queryKey: ["behavior-ethograms", projectId],
    queryFn: ({ signal }) => getBehaviorEthograms(projectId, signal),
  });
  const selectedEthogram = ethogramsQuery.data?.find(
    (item) => item.id === selectedEthogramId,
  );
  const boutsQuery = useQuery({
    queryKey: ["behavior-bouts", trackId, selectedEthogramId],
    queryFn: ({ signal }) =>
      getBehaviorBouts(trackId, selectedEthogramId, signal),
    enabled: Boolean(trackId && selectedEthogramId),
  });
  const dynamicsQuery = useQuery({
    queryKey: ["behavior-dynamics", trackId, selectedEthogramId],
    queryFn: ({ signal }) =>
      getBehaviorDynamics(trackId, selectedEthogramId, signal),
    enabled: Boolean(trackId && selectedEthogramId),
  });
  const modelsQuery = useQuery({
    queryKey: ["behavior-models", projectId, selectedEthogramId],
    queryFn: ({ signal }) =>
      getBehaviorModels(projectId, selectedEthogramId, signal),
    enabled: Boolean(selectedEthogramId),
  });
  const predictionsQuery = useQuery({
    queryKey: ["behavior-predictions", trackId, selectedModelId],
    queryFn: ({ signal }) =>
      getBehaviorPredictions(trackId, selectedModelId || undefined, signal),
    enabled: Boolean(trackId && selectedModelId),
  });

  useEffect(() => {
    if (!selectedEthogramId && ethogramsQuery.data?.[0]) {
      setSelectedEthogramId(ethogramsQuery.data[0].id);
    }
  }, [ethogramsQuery.data, selectedEthogramId]);

  useEffect(() => {
    setSelectedStateId(selectedEthogram?.states[0]?.id ?? "");
  }, [selectedEthogram?.id]);

  useEffect(() => {
    if (!selectedModelId && modelsQuery.data?.[0]) {
      setSelectedModelId(modelsQuery.data[0].id);
    }
  }, [modelsQuery.data, selectedModelId]);

  useEffect(() => {
    setBoutStart(frameIndex);
    setBoutEnd(frameIndex);
  }, [frameIndex]);

  const selectedModel = modelsQuery.data?.find(
    (item) => item.id === selectedModelId,
  );
  const selectedChannel =
    selectedEthogram?.states.find((item) => item.id === selectedStateId)
      ?.channel ??
    selectedEthogram?.states[0]?.channel ??
    "";

  const pendingPredictions = useMemo(
    () =>
      (predictionsQuery.data ?? []).filter(
        (prediction) => prediction.review_status === "pending",
      ),
    [predictionsQuery.data],
  );

  const createEthogramMutation = useMutation({
    mutationFn: () => {
      const channel = ethogramChannel.trim();
      if (!ethogramName.trim()) throw new Error("Ethogram name is required");
      if (!channel) throw new Error("Behavior channel is required");
      const states = parseStates(stateLines, channel);
      if (states.length < 2) {
        throw new Error("Enter at least two behavior states");
      }
      return createBehaviorEthogram(projectId, {
        name: ethogramName.trim(),
        states,
      });
    },
    onSuccess: async (ethogram) => {
      await queryClient.invalidateQueries({
        queryKey: ["behavior-ethograms", projectId],
      });
      setSelectedEthogramId(ethogram.id);
      setSelectedModelId("");
    },
  });

  const createBoutMutation = useMutation({
    mutationFn: () => {
      if (!selectedEthogramId || !selectedStateId) {
        throw new Error("Choose an ethogram and behavior state");
      }
      if (boutEnd < boutStart) {
        throw new Error("Bout end frame must be at or after the start frame");
      }
      return createBehaviorBout(trackId, {
        ethogram_revision_id: selectedEthogramId,
        behavior_state_id: selectedStateId,
        start_frame: boutStart,
        end_frame: boutEnd,
        source: "manual",
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["behavior-bouts", trackId, selectedEthogramId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["behavior-dynamics", trackId, selectedEthogramId],
        }),
      ]);
    },
  });

  const trainMutation = useMutation({
    mutationFn: () => {
      if (!selectedEthogram) throw new Error("Choose an ethogram first");
      if (!selectedChannel) throw new Error("Choose a behavior channel");
      if (!modelName.trim()) throw new Error("Model name is required");
      return trainBehaviorModel(projectId, {
        ethogram_revision_id: selectedEthogram.id,
        channel: selectedChannel,
        display_name: modelName.trim(),
        feature_preset: featurePreset,
        track_ids: [],
      });
    },
    onSuccess: async (model) => {
      await queryClient.invalidateQueries({
        queryKey: ["behavior-models", projectId, selectedEthogramId],
      });
      setSelectedModelId(model.id);
    },
  });

  const predictMutation = useMutation({
    mutationFn: () => {
      if (!selectedModelId) throw new Error("Choose a behavior model");
      if (windowFrames < 1 || strideFrames < 1) {
        throw new Error("Window and stride must be at least one frame");
      }
      return runBehaviorPredictions(trackId, {
        model_id: selectedModelId,
        window_frames: windowFrames,
        stride_frames: strideFrames,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["behavior-predictions", trackId, selectedModelId],
      });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: ({
      prediction,
      action,
      edit,
    }: {
      prediction: BehaviorPrediction;
      action: "accept" | "edit_and_accept" | "reject";
      edit?: PredictionEdit;
    }) =>
      reviewBehaviorPrediction(prediction.id, {
        action,
        ...(action === "edit_and_accept" && edit
          ? {
              behavior_state_id: edit.stateId,
              start_frame: edit.startFrame,
              end_frame: edit.endFrame,
            }
          : {}),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["behavior-predictions", trackId, selectedModelId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["behavior-bouts", trackId, selectedEthogramId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["behavior-dynamics", trackId, selectedEthogramId],
        }),
      ]);
    },
  });

  const runAction = (action: () => void) => {
    try {
      setValidationError(null);
      action();
    } catch (error) {
      setValidationError(
        error instanceof Error ? error.message : "Behavior settings are invalid",
      );
    }
  };

  const mutationError =
    createEthogramMutation.error ??
    createBoutMutation.error ??
    trainMutation.error ??
    predictMutation.error ??
    reviewMutation.error;

  return (
    <section className="management-card" aria-label="Behavior dynamics">
      <p className="eyebrow">Behavior dynamics</p>
      <h3>Ethogram, dynamics, and model-assisted review</h3>
      <p className="annotation-helper">
        Manual bouts are canonical ground truth. Model predictions remain
        separate until explicitly accepted by a scientist.
      </p>

      <label>
        Ethogram
        <select
          aria-label="Behavior ethogram"
          value={selectedEthogramId}
          onChange={(event) => {
            setSelectedEthogramId(event.target.value);
            setSelectedModelId("");
          }}
        >
          <option value="">Choose an ethogram</option>
          {(ethogramsQuery.data ?? []).map((ethogram) => (
            <option key={ethogram.id} value={ethogram.id}>
              {ethogram.name} · revision {ethogram.revision}
            </option>
          ))}
        </select>
      </label>

      <details>
        <summary>Create ethogram</summary>
        <label>
          Ethogram name
          <input
            aria-label="Behavior ethogram name"
            value={ethogramName}
            onChange={(event) => setEthogramName(event.target.value)}
          />
        </label>
        <label>
          Channel
          <input
            aria-label="Behavior ethogram channel"
            value={ethogramChannel}
            onChange={(event) => setEthogramChannel(event.target.value)}
          />
        </label>
        <label>
          States, one code=label per line
          <textarea
            aria-label="Behavior ethogram states"
            value={stateLines}
            onChange={(event) => setStateLines(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={createEthogramMutation.isPending}
          onClick={() => runAction(() => createEthogramMutation.mutate())}
        >
          Create ethogram
        </button>
      </details>

      {selectedEthogram && (
        <>
          <div className="workspace-guide compact">
            <div>
              <strong>
                {selectedEthogram.name} · revision {selectedEthogram.revision}
              </strong>
              <p className="annotation-helper">
                Definition {selectedEthogram.definition_sha256.slice(0, 12)}…
              </p>
            </div>
          </div>

          <h4>Manual behavior bout</h4>
          <label>
            State
            <select
              aria-label="Manual behavior state"
              value={selectedStateId}
              onChange={(event) => setSelectedStateId(event.target.value)}
            >
              {selectedEthogram.states.map((state) => (
                <option key={state.id} value={state.id}>
                  {state.channel} · {state.label}
                </option>
              ))}
            </select>
          </label>
          <div className="annotation-selection-list">
            <label className="annotation-selection-row">
              Start frame
              <input
                aria-label="Manual behavior start frame"
                type="number"
                min={0}
                value={boutStart}
                onChange={(event) => setBoutStart(Number(event.target.value))}
              />
            </label>
            <label className="annotation-selection-row">
              End frame
              <input
                aria-label="Manual behavior end frame"
                type="number"
                min={0}
                value={boutEnd}
                onChange={(event) => setBoutEnd(Number(event.target.value))}
              />
            </label>
          </div>
          <button
            type="button"
            disabled={createBoutMutation.isPending}
            onClick={() => runAction(() => createBoutMutation.mutate())}
          >
            Add verified manual bout
          </button>

          {(boutsQuery.data ?? []).length > 0 && (
            <div className="annotation-selection-list">
              {(boutsQuery.data ?? []).map((bout) => (
                <div className="annotation-selection-row" key={bout.id}>
                  <strong>
                    {bout.behavior_label} · frames {bout.start_frame}–
                    {bout.end_frame}
                  </strong>
                  <span className="annotation-helper">
                    {bout.source} · {bout.review_status}
                    {bout.stale_against_track ? " · stale" : ""}
                  </span>
                </div>
              ))}
            </div>
          )}

          {dynamicsQuery.data && (
            <>
              {dynamicsQuery.data.provenance_warning && (
                <p role="alert" className="form-error">
                  {dynamicsQuery.data.provenance_warning}
                </p>
              )}
              <h4>Behavior summary</h4>
              {dynamicsQuery.data.channels.map((channel) => (
                <div className="workspace-guide compact" key={channel.channel}>
                  <div>
                    <strong>{channel.channel}</strong>
                    <p className="annotation-helper">
                      {(channel.coverage_fraction * 100).toFixed(1)}% labeled ·{" "}
                      {channel.labeled_seconds.toFixed(2)} s labeled ·{" "}
                      {channel.unlabeled_seconds.toFixed(2)} s unlabeled
                    </p>
                    {channel.states.map((state) => (
                      <p className="annotation-helper" key={state.behavior_state_id}>
                        {state.behavior_label}: {state.dwell_seconds.toFixed(2)} s ·{" "}
                        {state.bout_count} bout
                        {state.bout_count === 1 ? "" : "s"}
                      </p>
                    ))}
                    {channel.transitions.map((transition) => (
                      <p
                        className="annotation-helper"
                        key={`${transition.from_behavior_state_id}-${transition.to_behavior_state_id}`}
                      >
                        {transition.from_behavior_code} →{" "}
                        {transition.to_behavior_code}: {transition.count} ·{" "}
                        {(transition.probability_from_state * 100).toFixed(1)}%
                      </p>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}

          <h4>Transparent behavior model</h4>
          <p className="annotation-helper">
            Training uses verified manual bouts only. Scores are normalized
            inverse centroid distances, not calibrated probabilities.
          </p>
          <label>
            Model name
            <input
              aria-label="Behavior model name"
              value={modelName}
              onChange={(event) => setModelName(event.target.value)}
            />
          </label>
          <label>
            Feature preset
            <select
              aria-label="Behavior model feature preset"
              value={featurePreset}
              onChange={(event) =>
                setFeaturePreset(event.target.value as BehaviorFeaturePreset)
              }
            >
              <option value="track_only">Track kinematics</option>
              <option value="track_pose_geometry">
                Track + pose geometry
              </option>
              <option value="track_pose_identity">
                Track + persistent pose identity
              </option>
            </select>
          </label>
          <button
            type="button"
            disabled={trainMutation.isPending}
            onClick={() => runAction(() => trainMutation.mutate())}
          >
            Train from verified manual bouts
          </button>

          {(modelsQuery.data ?? []).length > 0 && (
            <>
              <label>
                Behavior model
                <select
                  aria-label="Behavior model"
                  value={selectedModelId}
                  onChange={(event) => setSelectedModelId(event.target.value)}
                >
                  {(modelsQuery.data ?? []).map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.display_name} · {model.training_sample_count} samples
                    </option>
                  ))}
                </select>
              </label>
              {selectedModel && (
                <p className="annotation-helper">
                  {selectedModel.algorithm} {selectedModel.algorithm_version} ·{" "}
                  {selectedModel.feature_preset} · manifest{" "}
                  {selectedModel.training_manifest_sha256.slice(0, 12)}…
                </p>
              )}

              <div className="annotation-selection-list">
                <label className="annotation-selection-row">
                  Window frames
                  <input
                    aria-label="Behavior prediction window frames"
                    type="number"
                    min={1}
                    value={windowFrames}
                    onChange={(event) =>
                      setWindowFrames(Number(event.target.value))
                    }
                  />
                </label>
                <label className="annotation-selection-row">
                  Stride frames
                  <input
                    aria-label="Behavior prediction stride frames"
                    type="number"
                    min={1}
                    value={strideFrames}
                    onChange={(event) =>
                      setStrideFrames(Number(event.target.value))
                    }
                  />
                </label>
              </div>
              <button
                type="button"
                disabled={!selectedModelId || predictMutation.isPending}
                onClick={() => runAction(() => predictMutation.mutate())}
              >
                Run behavior predictions
              </button>
            </>
          )}

          {pendingPredictions.length > 0 && (
            <>
              <h4>Prediction review</h4>
              {pendingPredictions.map((prediction) => {
                const edit = predictionEdits[prediction.id] ?? {
                  stateId: prediction.behavior_state_id,
                  startFrame: prediction.start_frame,
                  endFrame: prediction.end_frame,
                };
                return (
                  <div className="workspace-guide compact" key={prediction.id}>
                    <div>
                      <strong>
                        {prediction.behavior_label} · frames{" "}
                        {prediction.start_frame}–{prediction.end_frame}
                      </strong>
                      <p className="annotation-helper">
                        score {prediction.prediction_score.toFixed(3)} ·
                        normalized inverse distance, not calibrated
                        {prediction.stale_against_track ? " · STALE" : ""}
                      </p>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => onFrameChange?.(prediction.start_frame)}
                      >
                        Go to frame
                      </button>
                      <div className="annotation-selection-list">
                        <label className="annotation-selection-row">
                          Corrected state
                          <select
                            aria-label={`Corrected behavior state ${prediction.id}`}
                            value={edit.stateId}
                            onChange={(event) =>
                              setPredictionEdits((current) => ({
                                ...current,
                                [prediction.id]: {
                                  ...edit,
                                  stateId: event.target.value,
                                },
                              }))
                            }
                          >
                            {selectedEthogram.states
                              .filter(
                                (state) => state.channel === prediction.channel,
                              )
                              .map((state) => (
                                <option key={state.id} value={state.id}>
                                  {state.label}
                                </option>
                              ))}
                          </select>
                        </label>
                        <label className="annotation-selection-row">
                          Corrected start
                          <input
                            aria-label={`Corrected behavior start ${prediction.id}`}
                            type="number"
                            min={0}
                            value={edit.startFrame}
                            onChange={(event) =>
                              setPredictionEdits((current) => ({
                                ...current,
                                [prediction.id]: {
                                  ...edit,
                                  startFrame: Number(event.target.value),
                                },
                              }))
                            }
                          />
                        </label>
                        <label className="annotation-selection-row">
                          Corrected end
                          <input
                            aria-label={`Corrected behavior end ${prediction.id}`}
                            type="number"
                            min={0}
                            value={edit.endFrame}
                            onChange={(event) =>
                              setPredictionEdits((current) => ({
                                ...current,
                                [prediction.id]: {
                                  ...edit,
                                  endFrame: Number(event.target.value),
                                },
                              }))
                            }
                          />
                        </label>
                      </div>
                      <div className="workspace-actions">
                        <button
                          type="button"
                          disabled={
                            prediction.stale_against_track ||
                            reviewMutation.isPending
                          }
                          onClick={() =>
                            reviewMutation.mutate({
                              prediction,
                              action: "accept",
                            })
                          }
                        >
                          Accept
                        </button>
                        <button
                          type="button"
                          disabled={
                            prediction.stale_against_track ||
                            reviewMutation.isPending
                          }
                          onClick={() =>
                            reviewMutation.mutate({
                              prediction,
                              action: "edit_and_accept",
                              edit,
                            })
                          }
                        >
                          Edit & accept
                        </button>
                        <button
                          type="button"
                          className="danger-ghost"
                          disabled={reviewMutation.isPending}
                          onClick={() =>
                            reviewMutation.mutate({
                              prediction,
                              action: "reject",
                            })
                          }
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </>
          )}

          <div className="workspace-actions">
            <a
              href={behaviorExportUrl(
                trackId,
                selectedEthogram.id,
                "json",
                selectedModelId || undefined,
              )}
            >
              Export behavior JSON
            </a>
            <a
              href={behaviorExportUrl(
                trackId,
                selectedEthogram.id,
                "bouts_csv",
                selectedModelId || undefined,
              )}
            >
              Export canonical bouts CSV
            </a>
            <a
              href={behaviorExportUrl(
                trackId,
                selectedEthogram.id,
                "predictions_csv",
                selectedModelId || undefined,
              )}
            >
              Export predictions CSV
            </a>
          </div>
        </>
      )}

      {validationError && <p className="form-error">{validationError}</p>}
      {mutationError instanceof Error && (
        <p className="form-error">{mutationError.message}</p>
      )}
    </section>
  );
}
