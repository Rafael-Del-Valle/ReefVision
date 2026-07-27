import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  createClassificationExport,
  createClassificationInference,
  createClassificationTraining,
  getClassificationPredictions,
  getDatasetVersions,
  getImages,
  getModels,
  getTrainingRuns,
  previewClassification,
  registerClassifier,
  reviewClassificationPrediction,
  type ClassificationPrediction,
} from "../phase456/api";

type ClassificationMode = "multiclass" | "binary_state";
type ClassificationTargetKind = "annotation" | "image" | "mask" | "fragment";

export function ClassificationDashboard({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [mode, setMode] = useState<ClassificationMode>("multiclass");
  const [minimumCropSize, setMinimumCropSize] = useState(10);
  const [paddingFraction, setPaddingFraction] = useState(0);
  const [runName, setRunName] = useState("Coral crop classifier");
  const [architecture, setArchitecture] = useState("yolov8n-cls.yaml");
  const [initialCheckpointModelId, setInitialCheckpointModelId] = useState("");
  const [epochs, setEpochs] = useState(50);
  const [batch, setBatch] = useState(16);
  const [imgsz, setImgsz] = useState(224);
  const [classifierId, setClassifierId] = useState("");
  const [inferenceTargetKind, setInferenceTargetKind] =
    useState<ClassificationTargetKind>("annotation");
  const [maskBackground, setMaskBackground] = useState<"black" | "keep">(
    "black",
  );
  const [classificationTaskKey, setClassificationTaskKey] = useState(
    "annotation-crop-state",
  );
  const [selectedImageIds, setSelectedImageIds] = useState<string[]>([]);
  const [reviewClassByPrediction, setReviewClassByPrediction] = useState<
    Record<string, string>
  >({});
  const [lastMessage, setLastMessage] = useState<string | null>(null);

  const versions = useQuery({
    queryKey: ["phase5_versions", project.id],
    queryFn: ({ signal }) => getDatasetVersions(project.id, signal),
  });
  const models = useQuery({
    queryKey: ["phase5_models", project.id],
    queryFn: ({ signal }) => getModels(project.id, signal),
  });
  const runs = useQuery({
    queryKey: ["phase5_runs", project.id],
    queryFn: ({ signal }) => getTrainingRuns(project.id, signal),
    refetchInterval: 5000,
  });
  const images = useQuery({
    queryKey: ["phase5_images", project.id],
    queryFn: ({ signal }) => getImages(project.id, signal),
  });
  const predictions = useQuery({
    queryKey: ["phase5_predictions", project.id],
    queryFn: ({ signal }) => getClassificationPredictions(project.id, signal),
    refetchInterval: 5000,
  });

  const classifiers = useMemo(
    () =>
      models.data?.filter(
        (model) => model.purpose === "classifier" && model.task === "classify",
      ) ?? [],
    [models.data],
  );
  const classificationRuns = useMemo(
    () => runs.data?.filter((run) => run.task === "classify") ?? [],
    [runs.data],
  );
  const completedUnregisteredRuns = useMemo(
    () =>
      classificationRuns.filter(
        (run) =>
          run.status === "completed" &&
          run.result_checkpoint_path &&
          !classifiers.some(
            (model) => model.metadata_json.source_training_run_id === run.id,
          ),
      ),
    [classificationRuns, classifiers],
  );

  useEffect(() => {
    if (!datasetVersionId) {
      const first = versions.data?.find(
        (version) => version.status === "complete",
      );
      if (first) setDatasetVersionId(first.id);
    }
  }, [datasetVersionId, versions.data]);

  useEffect(() => {
    if (!classifierId && classifiers.length) {
      setClassifierId(classifiers[0].id);
    }
  }, [classifierId, classifiers]);

  const preview = useMutation({
    mutationFn: () =>
      previewClassification(project.id, {
        dataset_version_id: datasetVersionId,
        mode,
        minimum_crop_size_px: minimumCropSize,
        padding_fraction: paddingFraction,
      }),
  });
  const exportDataset = useMutation({
    mutationFn: () =>
      createClassificationExport(datasetVersionId, {
        format:
          mode === "binary_state"
            ? "classification_binary_state"
            : "classification_multiclass",
        minimum_crop_size_px: minimumCropSize,
        padding_fraction: paddingFraction,
      }),
    onSuccess: (result) =>
      setLastMessage(`Classification export queued as job ${result.job.id}.`),
  });
  const train = useMutation({
    mutationFn: () =>
      createClassificationTraining(project.id, {
        dataset_version_id: datasetVersionId,
        mode,
        minimum_crop_size_px: minimumCropSize,
        padding_fraction: paddingFraction,
        run_name: runName,
        architecture,
        initial_checkpoint_model_id: initialCheckpointModelId || null,
        epochs,
        batch,
        imgsz,
        device: "auto",
        precision: "amp",
      }),
    onSuccess: async (run) => {
      setLastMessage(`Classification training queued as ${run.run_name}.`);
      await queryClient.invalidateQueries({
        queryKey: ["phase5_runs", project.id],
      });
    },
  });
  const register = useMutation({
    mutationFn: (runId: string) => registerClassifier(project.id, runId),
    onSuccess: async (model) => {
      setLastMessage(`Registered classifier ${model.display_name}.`);
      await queryClient.invalidateQueries({
        queryKey: ["phase5_models", project.id],
      });
    },
  });
  const infer = useMutation({
    mutationFn: () =>
      createClassificationInference(project.id, {
        model_id: classifierId,
        target_kind: inferenceTargetKind,
        image_ids: selectedImageIds,
        minimum_crop_size_px: minimumCropSize,
        padding_fraction: paddingFraction,
        mask_background: maskBackground,
        device: "auto",
        label_set: classificationTaskKey.trim(),
      }),
    onSuccess: (job) =>
      setLastMessage(
        `Classification task ${classificationTaskKey.trim()} queued as job ${job.id}.`,
      ),
  });
  const review = useMutation({
    mutationFn: ({
      prediction,
      action,
    }: {
      prediction: ClassificationPrediction;
      action: "accept" | "reject";
    }) =>
      reviewClassificationPrediction(
        prediction.id,
        action,
        action === "accept"
          ? reviewClassByPrediction[prediction.id] ||
              prediction.label_class_id ||
              undefined
          : undefined,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["phase5_predictions", project.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["project", project.id],
      });
    },
  });

  const settingsInvalid =
    !datasetVersionId ||
    minimumCropSize < 1 ||
    minimumCropSize > 4096 ||
    paddingFraction < 0 ||
    paddingFraction > 1;
  const classificationTaskKeyValid =
    classificationTaskKey.length > 0 &&
    classificationTaskKey.length <= 100 &&
    /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(classificationTaskKey);

  function toggleImage(imageId: string) {
    setSelectedImageIds((current) =>
      current.includes(imageId)
        ? current.filter((item) => item !== imageId)
        : [...current, imageId],
    );
  }

  const actionError =
    preview.error ??
    exportDataset.error ??
    train.error ??
    register.error ??
    infer.error ??
    review.error;

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 5</p>
          <h3>Classification</h3>
          <span>
            Immutable crops → train → register → infer → independent assignments
          </span>
        </div>
        <span>{classifiers.length} registered classifiers</span>
      </div>

      {lastMessage && <p className="form-success">{lastMessage}</p>}
      {actionError && <p className="form-error">{actionError.message}</p>}

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <div className="dashboard-card">
            <p className="eyebrow">Dataset</p>
            <h4>Build crop dataset</h4>
            <label>
              Immutable dataset version
              <select
                value={datasetVersionId}
                onChange={(event) => setDatasetVersionId(event.target.value)}
              >
                <option value="">Choose a complete version</option>
                {versions.data
                  ?.filter((version) => version.status === "complete")
                  .map((version) => (
                    <option key={version.id} value={version.id}>
                      v{version.version_number} · {version.name} ·{" "}
                      {version.annotation_count} boxes
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Classification target
              <select
                value={mode}
                onChange={(event) =>
                  setMode(event.target.value as ClassificationMode)
                }
              >
                <option value="multiclass">Six species/state classes</option>
                <option value="binary_state">Open versus closed</option>
              </select>
            </label>
            <div className="dashboard-grid compact-grid">
              <label>
                Minimum crop pixels
                <input
                  type="number"
                  min="1"
                  max="4096"
                  value={minimumCropSize}
                  onChange={(event) =>
                    setMinimumCropSize(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Padding fraction
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={paddingFraction}
                  onChange={(event) =>
                    setPaddingFraction(Number(event.target.value))
                  }
                />
              </label>
            </div>
            <p>
              Crops smaller than {minimumCropSize}×{minimumCropSize} pixels are
              removed during preprocessing and reported in the manifest.
            </p>
            <div className="version-actions">
              <button
                type="button"
                disabled={settingsInvalid || preview.isPending}
                onClick={() => preview.mutate()}
              >
                {preview.isPending ? "Checking..." : "Preview crops"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={settingsInvalid || exportDataset.isPending}
                onClick={() => exportDataset.mutate()}
              >
                Export dataset
              </button>
            </div>
          </div>

          <div className="dashboard-card">
            <p className="eyebrow">Training</p>
            <h4>Train classifier</h4>
            <label>
              Run name
              <input
                value={runName}
                onChange={(event) => setRunName(event.target.value)}
              />
            </label>
            <label>
              Scratch architecture
              <input
                value={architecture}
                disabled={Boolean(initialCheckpointModelId)}
                onChange={(event) => setArchitecture(event.target.value)}
              />
            </label>
            <label>
              Optional local pretrained classifier
              <select
                value={initialCheckpointModelId}
                onChange={(event) =>
                  setInitialCheckpointModelId(event.target.value)
                }
              >
                <option value="">Scratch training</option>
                {classifiers.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name}
                  </option>
                ))}
              </select>
            </label>
            <div className="dashboard-grid compact-grid">
              <label>
                Epochs
                <input
                  type="number"
                  min="1"
                  value={epochs}
                  onChange={(event) => setEpochs(Number(event.target.value))}
                />
              </label>
              <label>
                Batch
                <input
                  type="number"
                  min="1"
                  value={batch}
                  onChange={(event) => setBatch(Number(event.target.value))}
                />
              </label>
              <label>
                Image size
                <input
                  type="number"
                  min="32"
                  value={imgsz}
                  onChange={(event) => setImgsz(Number(event.target.value))}
                />
              </label>
            </div>
            <button
              type="button"
              disabled={settingsInvalid || !runName.trim() || train.isPending}
              onClick={() => train.mutate()}
            >
              {train.isPending ? "Queuing..." : "Start classification training"}
            </button>
          </div>
        </div>

        <div className="dashboard-main">
          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Preprocessing preview</p>
                <h4>
                  {preview.data
                    ? `${preview.data.eligible_crop_count} eligible crops`
                    : "Preview an immutable version"}
                </h4>
              </div>
              {preview.data && (
                <span>
                  {preview.data.removed_during_preprocessing_count} removed
                  during preprocessing
                </span>
              )}
            </div>
            {preview.data?.warnings.map((warning) => (
              <p key={warning} className="form-warning">
                {warning}
              </p>
            ))}
            <div className="dashboard-grid compact-grid">
              {preview.data?.classes.map((item) => (
                <article key={item.key} className="dashboard-card">
                  <strong>{item.label}</strong>
                  <span>{item.crop_count} crops</span>
                </article>
              ))}
            </div>
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Training runs</p>
                <h4>{classificationRuns.length} classification experiments</h4>
              </div>
            </div>
            <div className="dashboard-list">
              {classificationRuns.map((run) => (
                <article key={run.id} className="dashboard-row">
                  <div>
                    <strong>{run.run_name}</strong>
                    <p>
                      {run.status} · {run.stage}
                    </p>
                    <small>{new Date(run.created_at).toLocaleString()}</small>
                  </div>
                  {completedUnregisteredRuns.some(
                    (item) => item.id === run.id,
                  ) && (
                    <button
                      type="button"
                      disabled={register.isPending}
                      onClick={() => register.mutate(run.id)}
                    >
                      Register classifier
                    </button>
                  )}
                </article>
              ))}
            </div>
          </div>

          <div className="dashboard-card">
            <p className="eyebrow">Inference</p>
            <h4>Classify project targets</h4>
            <label>
              Classifier
              <select
                value={classifierId}
                onChange={(event) => setClassifierId(event.target.value)}
              >
                <option value="">Choose a classifier</option>
                {classifiers.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Target scope
              <select
                value={inferenceTargetKind}
                onChange={(event) =>
                  setInferenceTargetKind(
                    event.target.value as ClassificationTargetKind,
                  )
                }
              >
                <option value="annotation">Bounding boxes</option>
                <option value="image">Whole images</option>
                <option value="mask">Verified polygon/raster masks</option>
                <option value="fragment">Verified fragment masks</option>
              </select>
            </label>
            {(inferenceTargetKind === "mask" ||
              inferenceTargetKind === "fragment") && (
              <label>
                Pixels outside mask
                <select
                  value={maskBackground}
                  onChange={(event) =>
                    setMaskBackground(event.target.value as "black" | "keep")
                  }
                >
                  <option value="black">Replace with black</option>
                  <option value="keep">Keep surrounding crop</option>
                </select>
              </label>
            )}
            <label>
              Classification task key
              <input
                value={classificationTaskKey}
                aria-invalid={!classificationTaskKeyValid}
                onChange={(event) =>
                  setClassificationTaskKey(event.target.value.trimStart())
                }
                placeholder="species, health, condition"
              />
            </label>
            <p>
              Results with the same task key replace only that task&apos;s prior
              assignment. Different task keys and classifiers can coexist on the
              same target without changing its detection or mask class.
            </p>
            {!classificationTaskKeyValid && (
              <p className="form-warning">
                Use letters, numbers, periods, underscores, or hyphens,
                beginning with a letter or number.
              </p>
            )}
            <div className="version-actions">
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  setSelectedImageIds(
                    images.data?.items.map((image) => image.id) ?? [],
                  )
                }
              >
                Select loaded images
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelectedImageIds([])}
              >
                Clear
              </button>
              <button
                type="button"
                disabled={
                  !classifierId ||
                  !classificationTaskKeyValid ||
                  !selectedImageIds.length ||
                  infer.isPending
                }
                onClick={() => infer.mutate()}
              >
                {infer.isPending
                  ? "Queuing..."
                  : `Classify ${selectedImageIds.length} images`}
              </button>
            </div>
            <div className="annotation-selection-list">
              {images.data?.items.map((image) => (
                <label key={image.id} className="annotation-selection-row">
                  <input
                    type="checkbox"
                    checked={selectedImageIds.includes(image.id)}
                    onChange={() => toggleImage(image.id)}
                  />
                  <span>{image.original_filename}</span>
                  <small>{image.annotation_count} boxes</small>
                </label>
              ))}
            </div>
          </div>

          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Prediction review</p>
                <h4>{predictions.data?.total ?? 0} predictions</h4>
              </div>
            </div>
            <p>
              Accepted classifier results are stored as independent assignments.
              They do not replace the target&apos;s primary detection or mask
              class.
            </p>
            <div className="dashboard-list">
              {predictions.data?.items.map((prediction) => (
                <article key={prediction.id} className="dashboard-row">
                  <div>
                    <strong>{prediction.predicted_label}</strong>
                    <p>
                      Confidence {(prediction.confidence * 100).toFixed(1)}% ·{" "}
                      {prediction.review_status}
                    </p>
                    <small>
                      Image {prediction.image_id} · {prediction.target_kind}{" "}
                      target {prediction.target_key}
                    </small>
                    {prediction.review_status === "pending" && (
                      <label>
                        Accept as assignment class
                        <select
                          value={
                            reviewClassByPrediction[prediction.id] ??
                            prediction.label_class_id ??
                            ""
                          }
                          onChange={(event) =>
                            setReviewClassByPrediction((current) => ({
                              ...current,
                              [prediction.id]: event.target.value,
                            }))
                          }
                        >
                          <option value="">Choose class</option>
                          {project.label_classes
                            .filter((item) => item.is_active)
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name}
                              </option>
                            ))}
                        </select>
                      </label>
                    )}
                  </div>
                  {prediction.review_status === "pending" && (
                    <div className="dashboard-actions">
                      <button
                        type="button"
                        disabled={
                          review.isPending ||
                          !(
                            reviewClassByPrediction[prediction.id] ||
                            prediction.label_class_id
                          )
                        }
                        onClick={() =>
                          review.mutate({ prediction, action: "accept" })
                        }
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        disabled={review.isPending}
                        onClick={() =>
                          review.mutate({ prediction, action: "reject" })
                        }
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
