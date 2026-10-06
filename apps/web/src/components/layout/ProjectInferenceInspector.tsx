import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  cancelJob,
  createInferenceJob,
  getJob,
  getModels,
  type JobRecord,
} from "../../api/client";

const TERMINAL_JOB_STATES = ["succeeded", "failed", "cancelled"];

export function ProjectInferenceInspector({
  projectId,
  selectedImageIds,
  onOpenModelHub,
  onOpenAdvancedProviders,
}: {
  projectId: string;
  selectedImageIds: string[];
  onOpenModelHub: () => void;
  onOpenAdvancedProviders: () => void;
}) {
  const queryClient = useQueryClient();

  const [selectedModelId, setSelectedModelId] = useState("");
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.25");
  const [device, setDevice] = useState("cpu");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const detectorModels = useQuery({
    queryKey: ["models", projectId, "detector"],
    queryFn: ({ signal }) => getModels(projectId, "detector", signal),
  });

  const activeJob = useQuery({
    queryKey: ["job", activeJobId],
    queryFn: ({ signal }) => getJob(activeJobId as string, signal),
    enabled: activeJobId !== null,
    refetchInterval: (query) => {
      const state = query.state.data as JobRecord | undefined;

      return state && TERMINAL_JOB_STATES.includes(state.status) ? false : 1000;
    },
  });

  const inference = useMutation({
    mutationFn: () =>
      createInferenceJob(projectId, {
        model_id: selectedModelId,
        image_ids: selectedImageIds,
        confidence_threshold: Number(confidenceThreshold),
        device,
      }),
    onSuccess: (job) => {
      setActiveJobId(job.id);
    },
  });

  const cancelInference = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: (job) => {
      queryClient.setQueryData(["job", job.id], job);
    },
  });

  useEffect(() => {
    const models = detectorModels.data ?? [];

    if (!models.some((model) => model.id === selectedModelId)) {
      setSelectedModelId(models[0]?.id ?? "");
    }
  }, [detectorModels.data, selectedModelId]);

  useEffect(() => {
    setActiveJobId(null);
  }, [projectId]);

  const selectedModel =
    detectorModels.data?.find((model) => model.id === selectedModelId) ?? null;

  const confidence = Number(confidenceThreshold);
  const confidenceValid =
    Number.isFinite(confidence) && confidence >= 0 && confidence <= 1;

  const displayedJob = activeJob.data ?? inference.data ?? null;
  const jobRunning =
    displayedJob != null && !TERMINAL_JOB_STATES.includes(displayedJob.status);

  const runDisabled =
    detectorModels.isPending ||
    !selectedModel ||
    selectedImageIds.length === 0 ||
    !confidenceValid ||
    inference.isPending ||
    jobRunning;

  return (
    <section
      className="rv-inspector-card rv-inference-inspector"
      aria-label="Model inference controls"
    >
      <div className="rv-inspector-card-heading">
        <strong>Model inference</strong>
        <span>
          {selectedImageIds.length}{" "}
          {selectedImageIds.length === 1 ? "image" : "images"} selected
        </span>
      </div>

      <p>
        Run a registered project detector against the current Gallery batch.
        Results remain provisional model proposals until scientist review.
      </p>

      {detectorModels.isPending && (
        <p className="annotation-helper">Loading detector models…</p>
      )}

      {detectorModels.error && (
        <p className="form-error" role="alert">
          Detector models could not be loaded: {detectorModels.error.message}
        </p>
      )}

      {!detectorModels.isPending &&
        !detectorModels.error &&
        (detectorModels.data?.length ?? 0) === 0 && (
          <div className="rv-inspector-empty-control">
            <strong>No detector models registered</strong>
            <p>
              Register or train a compatible detector in Model Hub before
              running batch inference.
            </p>
            <button
              type="button"
              className="secondary"
              onClick={onOpenModelHub}
            >
              Open Model Hub
            </button>
          </div>
        )}

      {(detectorModels.data?.length ?? 0) > 0 && (
        <>
          <div className="rv-inference-summary">
            <span>
              {detectorModels.data?.length ?? 0}{" "}
              {detectorModels.data?.length === 1 ? "detector" : "detectors"}{" "}
              registered
            </span>
            <span>
              {selectedImageIds.length === 0
                ? "Select Gallery images to enable inference"
                : "Batch ready for configuration"}
            </span>
          </div>

          <label>
            Detector model
            <select
              value={selectedModelId}
              onChange={(event) => setSelectedModelId(event.target.value)}
            >
              {detectorModels.data?.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.display_name}
                </option>
              ))}
            </select>
          </label>

          {selectedModel && (
            <div className="rv-inference-model-meta">
              <span>{selectedModel.framework}</span>
              <span>{selectedModel.task}</span>
              <span>{selectedModel.provider_name}</span>
            </div>
          )}

          <label>
            Confidence threshold
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={confidenceThreshold}
              aria-invalid={!confidenceValid}
              onChange={(event) => setConfidenceThreshold(event.target.value)}
            />
          </label>

          {!confidenceValid && (
            <p className="form-error" role="alert">
              Confidence threshold must be between 0 and 1.
            </p>
          )}

          <label>
            Device
            <select
              value={device}
              onChange={(event) => setDevice(event.target.value)}
            >
              <option value="auto">Auto</option>
              <option value="cuda">CUDA</option>
              <option value="cpu">CPU</option>
            </select>
          </label>

          <div className="rv-inference-actions">
            <button
              type="button"
              disabled={runDisabled}
              onClick={() => inference.mutate()}
            >
              {inference.isPending
                ? "Queueing model…"
                : "Run model on selected images"}
            </button>

            {jobRunning && displayedJob && (
              <button
                type="button"
                className="secondary"
                disabled={cancelInference.isPending}
                onClick={() => cancelInference.mutate(displayedJob.id)}
              >
                {cancelInference.isPending ? "Cancelling…" : "Cancel job"}
              </button>
            )}
          </div>

          {selectedImageIds.length === 0 && (
            <p className="annotation-helper">
              Use the Gallery checkboxes, Select all visible, or Add to batch
              from the focused-image viewer.
            </p>
          )}

          {inference.error && (
            <p className="form-error" role="alert">
              {inference.error.message}
            </p>
          )}

          {cancelInference.error && (
            <p className="form-error" role="alert">
              {cancelInference.error.message}
            </p>
          )}

          {activeJob.error && (
            <p className="form-error" role="alert">
              Model job status could not be loaded: {activeJob.error.message}
            </p>
          )}

          {displayedJob && (
            <div
              className="rv-inference-job"
              aria-live="polite"
              data-job-status={displayedJob.status}
            >
              <div>
                <span>Model job</span>
                <strong>{displayedJob.status}</strong>
              </div>

              <div>
                <span>Progress</span>
                <strong>
                  {displayedJob.progress_current}/{displayedJob.progress_total}
                </strong>
              </div>

              {displayedJob.error_message && (
                <p className="form-error">{displayedJob.error_message}</p>
              )}
            </div>
          )}
        </>
      )}

      <div className="rv-inference-boundary">
        <strong>Scientist review required</strong>
        <p>
          Inference creates reviewable machine output. It does not change
          verified annotations automatically.
        </p>
      </div>

      <div className="rv-inspector-actions">
        <button type="button" className="secondary" onClick={onOpenModelHub}>
          <strong>Model Hub</strong>
          <small>Register, inspect, install, or train compatible models.</small>
        </button>

        <button
          type="button"
          className="secondary"
          onClick={onOpenAdvancedProviders}
        >
          <strong>Advanced Provider Lab</strong>
          <small>
            Open prompted detection, segmentation, depth, OCR, and VLM tools.
          </small>
        </button>
      </div>
    </section>
  );
}
