import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  cancelJob,
  createPoseEvaluationComparison,
  getPoseEvaluationComparisons,
  type JobRecord,
  type ModelRegistration,
  poseEvaluationComparisonExportUrl,
} from "../../api/client";
import type { PoseTrainingDataset } from "../video/poseActiveLearningApi";

function modelMatchesDataset(
  model: ModelRegistration,
  dataset: PoseTrainingDataset,
): boolean {
  const metadata = model.metadata_json;
  const forbiddenIds = new Set(
    [
      metadata.source_pose_training_dataset_id,
      metadata.source_pose_validation_dataset_id,
    ].filter((value): value is string => typeof value === "string"),
  );
  const forbiddenHashes = new Set(
    [
      metadata.source_pose_training_dataset_manifest_sha256,
      metadata.source_pose_validation_dataset_manifest_sha256,
    ].filter((value): value is string => typeof value === "string"),
  );
  return (
    model.task === "pose" &&
    dataset.status === "complete" &&
    metadata.source_pose_schema_id === dataset.pose_schema_id &&
    metadata.source_pose_schema_revision === dataset.pose_schema_revision &&
    metadata.source_pose_schema_content_hash ===
      dataset.pose_schema_content_hash &&
    !forbiddenIds.has(dataset.id) &&
    !forbiddenHashes.has(dataset.manifest_sha256)
  );
}

function reportModels(job: JobRecord): Array<Record<string, unknown>> {
  const value = job.result_json?.models;
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

export function PoseEvaluationComparisonPanel({
  projectId,
  models,
  datasets,
}: {
  projectId: string;
  models: ModelRegistration[];
  datasets: PoseTrainingDataset[];
}) {
  const queryClient = useQueryClient();
  const [datasetId, setDatasetId] = useState("");
  const [modelIds, setModelIds] = useState<string[]>([]);
  const [device, setDevice] = useState("auto");
  const selectedDataset = datasets.find((item) => item.id === datasetId);
  const poseModels = useMemo(
    () =>
      models.filter(
        (model) =>
          model.task === "pose" &&
          ["reefpose", "ultralytics", "sleap_nn"].includes(model.provider_name),
      ),
    [models],
  );
  const comparisons = useQuery({
    queryKey: ["pose-evaluation-comparisons", projectId],
    queryFn: ({ signal }) => getPoseEvaluationComparisons(projectId, signal),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) =>
        ["queued", "running", "cancel_requested"].includes(job.status),
      )
        ? 1000
        : false,
  });
  const createMutation = useMutation({
    mutationFn: () =>
      createPoseEvaluationComparison(projectId, {
        model_ids: modelIds,
        evaluation_dataset_id: datasetId,
        device,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["pose-evaluation-comparisons", projectId],
      });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["pose-evaluation-comparisons", projectId],
      });
    },
  });
  const jobs = comparisons.data?.items ?? [];
  const active = jobs.find((job) =>
    ["queued", "running", "cancel_requested"].includes(job.status),
  );

  function toggleModel(modelId: string): void {
    setModelIds((current) =>
      current.includes(modelId)
        ? current.filter((value) => value !== modelId)
        : [...current, modelId],
    );
  }

  return (
    <section className="panel-card pose-comparison-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Scientific evaluation</p>
          <h3>Pose model comparison</h3>
          <p>
            Compare compatible registered providers on immutable,
            scientist-verified held-out truth. Synthetic fixtures validate
            engineering behavior only, not biological accuracy.
          </p>
        </div>
      </div>
      <div className="workflow-parameter-grid">
        <label>
          Held-out evaluation dataset
          <select
            aria-label="Held-out evaluation dataset"
            value={datasetId}
            onChange={(event) => {
              setDatasetId(event.target.value);
              setModelIds([]);
            }}
          >
            <option value="">Choose frozen verified data</option>
            {datasets
              .filter((dataset) => dataset.status === "complete")
              .map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name} · revision {dataset.pose_schema_revision} ·{" "}
                  {dataset.item_count} items
                </option>
              ))}
          </select>
        </label>
        <label>
          Device
          <select
            value={device}
            onChange={(event) => setDevice(event.target.value)}
          >
            <option value="auto">Automatic</option>
            <option value="cpu">CPU</option>
            <option value="cuda">CUDA</option>
          </select>
        </label>
      </div>
      <fieldset className="annotation-selection-list">
        <legend>Compatible registered pose models</legend>
        {poseModels.map((model) => {
          const compatible = Boolean(
            selectedDataset && modelMatchesDataset(model, selectedDataset),
          );
          return (
            <label key={model.id}>
              <input
                type="checkbox"
                checked={modelIds.includes(model.id)}
                disabled={!compatible}
                onChange={() => toggleModel(model.id)}
              />
              {model.display_name} · {model.provider_name}
              {!compatible && selectedDataset
                ? " · incompatible schema or leakage"
                : ""}
            </label>
          );
        })}
      </fieldset>
      <div className="inline-actions">
        <button
          type="button"
          disabled={
            !datasetId || modelIds.length === 0 || createMutation.isPending
          }
          onClick={() => createMutation.mutate()}
        >
          {createMutation.isPending ? "Queueing…" : "Start comparison"}
        </button>
        {active && (
          <button
            type="button"
            className="secondary-button"
            disabled={
              cancelMutation.isPending || active.status === "cancel_requested"
            }
            onClick={() => cancelMutation.mutate(active.id)}
          >
            Cancel comparison
          </button>
        )}
      </div>
      {createMutation.error && (
        <p className="form-error">{createMutation.error.message}</p>
      )}
      {active && (
        <div className="job-progress-card">
          <strong>Status: {active.status}</strong>
          <progress
            value={active.progress_current}
            max={active.progress_total || 1}
          />
          <span>
            {active.progress_current} / {active.progress_total}
          </span>
        </div>
      )}
      {comparisons.error && (
        <p className="form-error">{comparisons.error.message}</p>
      )}
      {jobs.map((job) => (
        <article className="pose-comparison-result" key={job.id}>
          <div className="image-card-topline">
            <strong>{job.status}</strong>
            <span title={String(job.result_json?.report_sha256 ?? "")}>
              Report{" "}
              {String(job.result_json?.report_sha256 ?? "pending").slice(0, 12)}
            </span>
          </div>
          <div className="pose-comparison-metrics">
            {reportModels(job).map((result) => {
              const metrics = (result.metrics ?? {}) as Record<string, unknown>;
              const distribution = (metrics.normalized_error_distribution ??
                {}) as Record<string, unknown>;
              const binCounts = Array.isArray(distribution.bin_counts)
                ? distribution.bin_counts.map(Number)
                : [];
              const maxBinCount = Math.max(1, ...binCounts);
              const calibration = (metrics.calibration ?? {}) as Record<
                string,
                unknown
              >;
              const availability = (result.metric_availability ?? {}) as Record<
                string,
                { available?: boolean; reason?: string | null }
              >;
              return (
                <div key={String(result.model_id)} className="metric-card">
                  <strong>
                    {String(result.display_name ?? result.model_id)}
                  </strong>
                  <span>Provider: {String(result.provider_name)}</span>
                  <span>
                    NME:{" "}
                    {availability.nme?.available === false
                      ? "Not available"
                      : String(metrics.nme)}
                  </span>
                  {availability.nme?.available === false && (
                    <small>{availability.nme.reason}</small>
                  )}
                  <span>
                    Mean error:{" "}
                    {String(metrics.mean_euclidean_error ?? "Not available")}
                  </span>
                  {binCounts.length > 0 && (
                    <div
                      className="pose-distribution-chart"
                      role="img"
                      aria-label={`Normalized error distribution for ${String(result.display_name ?? result.model_id)}`}
                    >
                      {binCounts.map((count, index) => (
                        <span
                          key={index}
                          title={`Bin ${index + 1}: ${count}`}
                          style={{
                            height: `${Math.max(6, (count / maxBinCount) * 100)}%`,
                          }}
                        />
                      ))}
                    </div>
                  )}
                  {calibration.expected_calibration_error !== undefined && (
                    <span>
                      Calibration ECE:{" "}
                      {String(calibration.expected_calibration_error)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {Array.isArray(job.result_json?.exclusions) &&
            job.result_json.exclusions.map((item, index) => {
              const exclusion = item as Record<string, unknown>;
              return (
                <p className="form-error" key={`${job.id}-exclusion-${index}`}>
                  {String(exclusion.provider_name)}: {String(exclusion.reason)}
                </p>
              );
            })}
          {Array.isArray(job.result_json?.warnings) &&
            job.result_json.warnings.map((warning) => (
              <p className="annotation-helper" key={String(warning)}>
                {String(warning)}
              </p>
            ))}
          {Boolean(job.result_json?.report_sha256) && (
            <div className="inline-actions">
              <a href={poseEvaluationComparisonExportUrl(job.id, "json")}>
                Export JSON
              </a>
              <a href={poseEvaluationComparisonExportUrl(job.id, "csv")}>
                Export CSV
              </a>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}
