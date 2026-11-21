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
  const boundSchema =
    metadata.pose_landmark_schema &&
    typeof metadata.pose_landmark_schema === "object"
      ? (metadata.pose_landmark_schema as Record<string, unknown>)
      : {};
  return (
    model.task === "pose" &&
    dataset.status === "complete" &&
    (metadata.source_pose_schema_id ?? boundSchema.schema_id) ===
      dataset.pose_schema_id &&
    (metadata.source_pose_schema_revision ?? boundSchema.schema_revision) ===
      dataset.pose_schema_revision &&
    (metadata.source_pose_schema_content_hash ?? boundSchema.content_hash) ===
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

type Availability = Record<
  string,
  { available?: boolean; reason?: string | null }
>;

function metricText(
  availability: Availability,
  key: string,
  value: unknown,
): string {
  if (availability[key]?.available === false) {
    return `Not available: ${availability[key]?.reason ?? "unspecified reason"}`;
  }
  return typeof value === "object"
    ? JSON.stringify(value ?? {})
    : String(value ?? "N/A");
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
  const activeJobs = jobs.filter((job) =>
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
      </div>
      {createMutation.error && (
        <p className="form-error">{createMutation.error.message}</p>
      )}
      {activeJobs.map((active) => (
        <div className="job-progress-card" key={active.id}>
          <strong>Status: {active.status}</strong>
          <progress
            value={active.progress_current}
            max={active.progress_total || 1}
          />
          <span>
            {active.progress_current} / {active.progress_total}
          </span>
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
        </div>
      ))}
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
          {reportModels(job).length > 0 && (
            <table aria-label={`Comparative pose metrics for ${job.id}`}>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Provider</th>
                  <th>NME</th>
                  <th>PCK</th>
                  <th>Visibility</th>
                  <th>OKS</th>
                  <th>Latency (ms)</th>
                  <th>Images/s</th>
                </tr>
              </thead>
              <tbody>
                {reportModels(job).map((result) => {
                  const metrics = (result.metrics ?? {}) as Record<
                    string,
                    unknown
                  >;
                  const performance = (result.performance ?? {}) as Record<
                    string,
                    unknown
                  >;
                  const availability = (result.metric_availability ??
                    {}) as Availability;
                  return (
                    <tr key={`summary-${String(result.model_id)}`}>
                      <td>{String(result.display_name ?? result.model_id)}</td>
                      <td>{String(result.provider_name)}</td>
                      <td>{metricText(availability, "nme", metrics.nme)}</td>
                      <td>{metricText(availability, "pck", metrics.pck)}</td>
                      <td>
                        {metricText(
                          availability,
                          "visibility",
                          metrics.visibility,
                        )}
                      </td>
                      <td>{metricText(availability, "oks", metrics.oks)}</td>
                      <td>
                        {String(performance.inference_latency_ms ?? "N/A")}
                      </td>
                      <td>{String(performance.images_per_second ?? "N/A")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
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
              const availability = (result.metric_availability ??
                {}) as Availability;
              const performance = (result.performance ?? {}) as Record<
                string,
                unknown
              >;
              const perLandmark = (metrics.per_landmark ?? {}) as Record<
                string,
                Record<string, unknown>
              >;
              const reliabilityBins = Array.isArray(
                calibration.reliability_bins,
              )
                ? (calibration.reliability_bins as Array<
                    Record<string, unknown>
                  >)
                : [];
              const maxLandmarkError = Math.max(
                1,
                ...Object.values(perLandmark).map((values) =>
                  Number(values.mean_euclidean_error ?? 0),
                ),
              );
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
                    {metricText(
                      availability,
                      "euclidean_error",
                      metrics.mean_euclidean_error,
                    )}
                  </span>
                  <span>
                    PCK: {metricText(availability, "pck", metrics.pck)}
                  </span>
                  <span>
                    OKS: {metricText(availability, "oks", metrics.oks)}
                  </span>
                  <span>
                    Visibility:{" "}
                    {metricText(availability, "visibility", metrics.visibility)}
                  </span>
                  <span>
                    Latency:{" "}
                    {String(
                      performance.inference_latency_ms ?? "Not available",
                    )}{" "}
                    ms · throughput:{" "}
                    {String(performance.images_per_second ?? "Not available")}{" "}
                    images/s
                  </span>
                  {availability.nme?.available !== false &&
                    binCounts.length > 0 && (
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
                  {availability.calibration?.available !== false &&
                    calibration.expected_calibration_error !== undefined && (
                      <span>
                        Calibration ECE:{" "}
                        {String(calibration.expected_calibration_error)}
                      </span>
                    )}
                  {availability.calibration?.available === false && (
                    <small>{availability.calibration.reason}</small>
                  )}
                  {availability.calibration?.available !== false &&
                    reliabilityBins.length > 0 && (
                      <div
                        className="pose-distribution-chart"
                        role="img"
                        aria-label={`Confidence reliability for ${String(result.display_name ?? result.model_id)}`}
                      >
                        {reliabilityBins.map((bin, index) => (
                          <span
                            key={index}
                            title={`Confidence ${String(bin.mean_confidence)}: empirical accuracy ${String(bin.accuracy)}, n=${String(bin.sample_count)}`}
                            style={{
                              height: `${Math.max(6, Number(bin.accuracy ?? 0) * 100)}%`,
                            }}
                          />
                        ))}
                      </div>
                    )}
                  {availability.euclidean_error?.available !== false &&
                    Object.values(perLandmark).some(
                      (values) =>
                        typeof values.mean_euclidean_error === "number",
                    ) && (
                      <>
                        <div
                          className="pose-distribution-chart"
                          role="img"
                          aria-label={`Per-landmark error chart for ${String(result.display_name ?? result.model_id)}`}
                        >
                          {Object.entries(perLandmark)
                            .filter(
                              ([, values]) =>
                                typeof values.mean_euclidean_error === "number",
                            )
                            .map(([landmarkId, values]) => (
                              <span
                                key={landmarkId}
                                title={`${String(values.name ?? landmarkId)}: ${String(values.mean_euclidean_error ?? "N/A")}`}
                                style={{
                                  height: `${Math.max(6, (Number(values.mean_euclidean_error ?? 0) / maxLandmarkError) * 100)}%`,
                                }}
                              />
                            ))}
                        </div>
                        <table
                          aria-label={`Per-landmark performance for ${String(result.display_name ?? result.model_id)}`}
                        >
                          <thead>
                            <tr>
                              <th>Landmark</th>
                              <th>NME</th>
                              <th>Mean error</th>
                              <th>Coverage</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(perLandmark).map(
                              ([landmarkId, values]) => (
                                <tr key={landmarkId}>
                                  <td>{String(values.name ?? landmarkId)}</td>
                                  <td>{String(values.nme ?? "N/A")}</td>
                                  <td>
                                    {String(
                                      values.mean_euclidean_error ?? "N/A",
                                    )}
                                  </td>
                                  <td>
                                    {String(
                                      values.localization_coverage ?? "N/A",
                                    )}
                                  </td>
                                </tr>
                              ),
                            )}
                          </tbody>
                        </table>
                      </>
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
