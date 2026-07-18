import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { imageThumbnailUrl, type Project } from "../../api/client";
import {
  createClassificationDataset,
  createClassificationInferenceJob,
  createClassificationTrainingJob,
  getClassificationDatasets,
  getClassificationImages,
  getClassificationPredictions,
  getClassificationVersions,
  getClassifierModels,
  getImageClassificationLabels,
  replaceImageClassificationLabels,
  reviewClassificationPrediction,
} from "./classificationApi";

interface ClassificationWorkspaceProps {
  project: Project;
}

export function ClassificationWorkspace({ project }: ClassificationWorkspaceProps) {
  const queryClient = useQueryClient();
  const [selectedImageId, setSelectedImageId] = useState("");
  const [labelSet, setLabelSet] = useState("species");
  const [selectedClassIds, setSelectedClassIds] = useState<string[]>([]);
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [datasetMode, setDatasetMode] = useState<
    "image" | "box_crop" | "mask_crop"
  >("image");
  const [trainingDatasetId, setTrainingDatasetId] = useState("");
  const [architecture, setArchitecture] = useState("yolo11n-cls.pt");
  const [epochs, setEpochs] = useState(50);
  const [classifierId, setClassifierId] = useState("");

  const imagesQuery = useQuery({
    queryKey: ["classification-images", project.id],
    queryFn: ({ signal }) => getClassificationImages(project.id, signal),
  });
  const versionsQuery = useQuery({
    queryKey: ["classification-versions", project.id],
    queryFn: ({ signal }) => getClassificationVersions(project.id, signal),
  });
  const datasetsQuery = useQuery({
    queryKey: ["classification-datasets", project.id],
    queryFn: ({ signal }) => getClassificationDatasets(project.id, signal),
  });
  const modelsQuery = useQuery({
    queryKey: ["classification-models", project.id],
    queryFn: ({ signal }) => getClassifierModels(project.id, signal),
  });
  const labelsQuery = useQuery({
    queryKey: ["classification-labels", selectedImageId, labelSet],
    queryFn: ({ signal }) =>
      getImageClassificationLabels(selectedImageId, labelSet, signal),
    enabled: Boolean(selectedImageId),
  });
  const predictionsQuery = useQuery({
    queryKey: ["classification-predictions", project.id, selectedImageId],
    queryFn: ({ signal }) =>
      getClassificationPredictions(project.id, selectedImageId, signal),
    enabled: Boolean(selectedImageId),
    refetchInterval: 2500,
  });

  useEffect(() => {
    if (!selectedImageId && imagesQuery.data?.items[0]) {
      setSelectedImageId(imagesQuery.data.items[0].id);
    }
  }, [imagesQuery.data?.items, selectedImageId]);
  useEffect(() => {
    setSelectedClassIds(
      labelsQuery.data?.map((label) => label.label_class_id) ?? [],
    );
  }, [labelsQuery.data]);
  useEffect(() => {
    if (!datasetVersionId && versionsQuery.data?.[0]) {
      setDatasetVersionId(versionsQuery.data[0].id);
    }
  }, [datasetVersionId, versionsQuery.data]);
  useEffect(() => {
    if (!trainingDatasetId && datasetsQuery.data?.[0]) {
      setTrainingDatasetId(datasetsQuery.data[0].id);
    }
  }, [datasetsQuery.data, trainingDatasetId]);
  useEffect(() => {
    if (!classifierId && modelsQuery.data?.[0]) {
      setClassifierId(modelsQuery.data[0].id);
    }
  }, [classifierId, modelsQuery.data]);

  const selectedImage = useMemo(
    () => imagesQuery.data?.items.find((image) => image.id === selectedImageId),
    [imagesQuery.data?.items, selectedImageId],
  );
  const classNames = useMemo(
    () => Object.fromEntries(project.label_classes.map((item) => [item.id, item.name])),
    [project.label_classes],
  );

  const labelMutation = useMutation({
    mutationFn: () =>
      replaceImageClassificationLabels(
        selectedImageId,
        labelSet.trim() || "default",
        selectedClassIds,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["classification-labels", selectedImageId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["classification-images", project.id],
      });
    },
  });
  const datasetMutation = useMutation({
    mutationFn: () =>
      createClassificationDataset(project.id, {
        dataset_version_id: datasetVersionId,
        mode: datasetMode,
        label_set: labelSet.trim() || "default",
        minimum_crop_pixels: 16,
      }),
    onSuccess: async (dataset) => {
      setTrainingDatasetId(dataset.id);
      await queryClient.invalidateQueries({
        queryKey: ["classification-datasets", project.id],
      });
    },
  });
  const trainingMutation = useMutation({
    mutationFn: () =>
      createClassificationTrainingJob(project.id, {
        classification_dataset_id: trainingDatasetId,
        architecture,
        run_name: `${labelSet || "default"} classifier`,
        epochs,
        image_size: 224,
        batch: 16,
        device: "auto",
      }),
  });
  const inferenceMutation = useMutation({
    mutationFn: () =>
      createClassificationInferenceJob(project.id, {
        model_id: classifierId,
        image_ids: [selectedImageId],
        label_set: labelSet.trim() || "default",
        top_k: 5,
        device: "auto",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["classification-predictions", project.id, selectedImageId],
      });
    },
  });
  const reviewMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "accept" | "reject" }) =>
      reviewClassificationPrediction(id, action),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["classification-predictions", project.id, selectedImageId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["classification-labels", selectedImageId],
        }),
      ]);
    },
  });

  const error =
    labelMutation.error ??
    datasetMutation.error ??
    trainingMutation.error ??
    inferenceMutation.error ??
    reviewMutation.error;

  return (
    <div className="management-grid" data-testid="classification-workspace">
      <section className="management-card">
        <p className="eyebrow">Phase 5</p>
        <h3>Image classification labels</h3>
        <label>
          Image
          <select
            value={selectedImageId}
            onChange={(event) => setSelectedImageId(event.target.value)}
          >
            {(imagesQuery.data?.items ?? []).map((image) => (
              <option key={image.id} value={image.id}>
                {image.original_filename}
              </option>
            ))}
          </select>
        </label>
        <label>
          Label set
          <input value={labelSet} onChange={(event) => setLabelSet(event.target.value)} />
        </label>
        {selectedImage && (
          <img
            src={imageThumbnailUrl(selectedImage.id)}
            alt={selectedImage.original_filename}
            style={{ width: "100%", maxHeight: 280, objectFit: "contain" }}
          />
        )}
        <div className="annotation-class-list">
          {project.label_classes.map((labelClass) => (
            <label key={labelClass.id} className="annotation-class-row">
              <input
                type="checkbox"
                checked={selectedClassIds.includes(labelClass.id)}
                onChange={(event) =>
                  setSelectedClassIds((current) =>
                    event.target.checked
                      ? [...current, labelClass.id]
                      : current.filter((id) => id !== labelClass.id),
                  )
                }
              />
              <span>{labelClass.name}</span>
            </label>
          ))}
        </div>
        <button
          type="button"
          disabled={!selectedImageId || labelMutation.isPending}
          onClick={() => labelMutation.mutate()}
        >
          {labelMutation.isPending ? "Saving..." : "Save image labels"}
        </button>
      </section>

      <section className="management-card">
        <p className="eyebrow">Immutable data</p>
        <h3>Classification dataset</h3>
        <label>
          Dataset version
          <select
            value={datasetVersionId}
            onChange={(event) => setDatasetVersionId(event.target.value)}
          >
            {(versionsQuery.data ?? []).map((version) => (
              <option key={version.id} value={version.id}>
                v{version.version_number} — {version.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sample mode
          <select
            value={datasetMode}
            onChange={(event) =>
              setDatasetMode(
                event.target.value as "image" | "box_crop" | "mask_crop",
              )
            }
          >
            <option value="image">Whole image</option>
            <option value="box_crop">Bounding-box crops</option>
            <option value="mask_crop">Mask-bound crops</option>
          </select>
        </label>
        <button
          type="button"
          disabled={!datasetVersionId || datasetMutation.isPending}
          onClick={() => datasetMutation.mutate()}
        >
          {datasetMutation.isPending ? "Materializing..." : "Create dataset"}
        </button>
        <ul>
          {(datasetsQuery.data ?? []).map((dataset) => (
            <li key={dataset.id}>
              <strong>{dataset.mode}</strong> — {dataset.sample_count} samples
            </li>
          ))}
        </ul>
      </section>

      <section className="management-card">
        <p className="eyebrow">Training</p>
        <h3>Ultralytics classifier</h3>
        <label>
          Dataset
          <select
            value={trainingDatasetId}
            onChange={(event) => setTrainingDatasetId(event.target.value)}
          >
            {(datasetsQuery.data ?? []).map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.mode} — {dataset.sample_count} samples
              </option>
            ))}
          </select>
        </label>
        <label>
          Architecture
          <input
            value={architecture}
            onChange={(event) => setArchitecture(event.target.value)}
          />
        </label>
        <label>
          Epochs
          <input
            type="number"
            min={1}
            value={epochs}
            onChange={(event) => setEpochs(Number(event.target.value))}
          />
        </label>
        <button
          type="button"
          disabled={!trainingDatasetId || trainingMutation.isPending}
          onClick={() => trainingMutation.mutate()}
        >
          {trainingMutation.isPending ? "Queuing..." : "Launch classification training"}
        </button>
        {trainingMutation.data && (
          <p className="annotation-helper">
            Job {trainingMutation.data.id.slice(0, 8)} queued. Completed checkpoints are
            registered automatically.
          </p>
        )}
      </section>

      <section className="management-card">
        <p className="eyebrow">Inference review</p>
        <h3>Top-k predictions</h3>
        <label>
          Classifier
          <select
            value={classifierId}
            onChange={(event) => setClassifierId(event.target.value)}
          >
            {(modelsQuery.data ?? []).map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!classifierId || !selectedImageId || inferenceMutation.isPending}
          onClick={() => inferenceMutation.mutate()}
        >
          {inferenceMutation.isPending ? "Queuing..." : "Classify selected image"}
        </button>
        <div className="annotation-selection-list">
          {(predictionsQuery.data ?? []).map((prediction) => (
            <div key={prediction.id} className="annotation-selection-row">
              <span>
                #{prediction.rank} {classNames[prediction.label_class_id] ?? "Unknown"}{" "}
                {(prediction.confidence * 100).toFixed(1)}%
              </span>
              <span>{prediction.status}</span>
              {prediction.status === "pending" && (
                <div className="annotation-editor-inline-actions">
                  <button
                    type="button"
                    onClick={() =>
                      reviewMutation.mutate({ id: prediction.id, action: "accept" })
                    }
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      reviewMutation.mutate({ id: prediction.id, action: "reject" })
                    }
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {error instanceof Error && <p className="form-error">{error.message}</p>}
    </div>
  );
}
