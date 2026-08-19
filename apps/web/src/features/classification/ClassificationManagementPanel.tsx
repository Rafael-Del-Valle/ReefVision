import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  bulkReviewClassificationPredictions,
  classificationScientificDownloadUrl,
  compareClassificationModels,
  createClassificationDatasetSnapshot,
  createClassificationLabelSet,
  listClassificationDatasetSnapshots,
  listClassificationLabelSets,
  listPendingClassificationPredictions,
  trainClassificationDatasetSnapshot,
  updateClassificationLabelSet,
  type ClassificationDatasetSnapshot,
  type ClassificationLabelSet,
} from "./classificationManagementApi";

const TARGETS = ["annotation", "image", "mask", "fragment"] as const;

export function ClassificationManagementPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [targetKind, setTargetKind] = useState<(typeof TARGETS)[number]>(
    "annotation",
  );
  const [cardinality, setCardinality] = useState<"single" | "multi">(
    "single",
  );
  const [allowedClassIds, setAllowedClassIds] = useState<string[]>([]);
  const [isActive, setIsActive] = useState(true);
  const [selectedPredictionIds, setSelectedPredictionIds] = useState<string[]>(
    [],
  );
  const [bulkLabelSetId, setBulkLabelSetId] = useState("");
  const [comparisonTask, setComparisonTask] = useState("");
  const [snapshotName, setSnapshotName] = useState("");
  const [snapshotLabelSetId, setSnapshotLabelSetId] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const labelSets = useQuery({
    queryKey: ["classification_label_sets", project.id],
    queryFn: ({ signal }) => listClassificationLabelSets(project.id, signal),
  });
  const predictions = useQuery({
    queryKey: ["pending_classification_predictions", project.id],
    queryFn: ({ signal }) =>
      listPendingClassificationPredictions(project.id, signal),
  });
  const snapshots = useQuery({
    queryKey: ["classification_dataset_snapshots", project.id],
    queryFn: ({ signal }) =>
      listClassificationDatasetSnapshots(project.id, signal),
  });
  const comparison = useQuery({
    queryKey: ["classification_model_comparison", project.id, comparisonTask],
    queryFn: () => compareClassificationModels(project.id, comparisonTask),
    enabled: false,
  });

  const saveLabelSet = useMutation({
    mutationFn: () => {
      const payload = {
        key: key.trim(),
        name: name.trim(),
        description: description.trim() || null,
        target_kind: targetKind,
        cardinality,
        allowed_class_ids: allowedClassIds,
        replaces_primary_class: false,
        is_active: isActive,
      };
      return editingId
        ? updateClassificationLabelSet(editingId, payload)
        : createClassificationLabelSet(project.id, payload);
    },
    onSuccess: (saved) => {
      setMessage(`${saved.name} saved.`);
      setEditingId(null);
      setKey("");
      setName("");
      setDescription("");
      setAllowedClassIds([]);
      void queryClient.invalidateQueries({
        queryKey: ["classification_label_sets", project.id],
      });
    },
  });

  const bulkReview = useMutation({
    mutationFn: (action: "accept" | "reject") =>
      bulkReviewClassificationPredictions(project.id, {
        prediction_ids: selectedPredictionIds,
        action,
        ...(action === "accept" && bulkLabelSetId
          ? { label_set_id: bulkLabelSetId }
          : {}),
      }),
    onSuccess: (result) => {
      setMessage(
        `Bulk review: ${result.accepted_count} accepted, ${result.rejected_count} rejected, ${result.failed_count} failed.`,
      );
      setSelectedPredictionIds([]);
      void queryClient.invalidateQueries({
        queryKey: ["pending_classification_predictions", project.id],
      });
    },
  });

  const createSnapshot = useMutation({
    mutationFn: () =>
      createClassificationDatasetSnapshot(project.id, {
        name: snapshotName.trim(),
        label_set_id: snapshotLabelSetId,
      }),
    onSuccess: (result) => {
      setMessage(
        `${result.snapshot.name} frozen with ${result.snapshot.sample_count} samples.`,
      );
      setSnapshotName("");
      void queryClient.invalidateQueries({
        queryKey: ["classification_dataset_snapshots", project.id],
      });
    },
  });

  const trainSnapshot = useMutation({
    mutationFn: (snapshot: ClassificationDatasetSnapshot) =>
      trainClassificationDatasetSnapshot(project.id, snapshot.id, {
        run_name: `${snapshot.name} classifier`,
      }),
    onSuccess: (result, snapshot) => {
      setMessage(
        `${snapshot.name} training queued as run ${result.training_run_id.slice(0, 8)}…`,
      );
      void queryClient.invalidateQueries({ queryKey: ["training_runs"] });
    },
  });

  const datasetLabelSets = useMemo(
    () =>
      labelSets.data?.filter((item) =>
        ["image", "mask", "fragment"].includes(item.target_kind),
      ) ?? [],
    [labelSets.data],
  );

  function editLabelSet(item: ClassificationLabelSet) {
    setEditingId(item.id);
    setKey(item.key);
    setName(item.name);
    setDescription(item.description ?? "");
    setTargetKind(item.target_kind);
    setCardinality(item.cardinality);
    setAllowedClassIds(item.allowed_class_ids_json);
    setIsActive(item.is_active);
  }

  function toggleClass(classId: string) {
    setAllowedClassIds((current) =>
      current.includes(classId)
        ? current.filter((item) => item !== classId)
        : [...current, classId],
    );
  }

  function togglePrediction(predictionId: string) {
    setSelectedPredictionIds((current) =>
      current.includes(predictionId)
        ? current.filter((item) => item !== predictionId)
        : [...current, predictionId],
    );
  }

  const error =
    labelSets.error ??
    predictions.error ??
    snapshots.error ??
    comparison.error ??
    saveLabelSet.error ??
    bulkReview.error ??
    createSnapshot.error ??
    trainSnapshot.error;

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Classification management</p>
          <h3>Tasks, review, comparison, and immutable datasets</h3>
          <span>
            Keep independent biological questions separate, support multiple
            labels when appropriate, and freeze reviewed targets before training.
          </span>
        </div>
      </div>
      {message && <p className="form-success">{message}</p>}
      {error && <p className="form-error">{error.message}</p>}

      <div className="dashboard-grid">
        <article className="dashboard-card">
          <p className="eyebrow">Label-set editor</p>
          <h4>{editingId ? "Edit classification task" : "New classification task"}</h4>
          <label>
            Stable task key
            <input value={key} onChange={(event) => setKey(event.target.value)} />
          </label>
          <label>
            Display name
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            Description
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label>
            Target
            <select
              value={targetKind}
              onChange={(event) =>
                setTargetKind(event.target.value as (typeof TARGETS)[number])
              }
            >
              {TARGETS.map((target) => (
                <option key={target} value={target}>
                  {target.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Cardinality
            <select
              value={cardinality}
              onChange={(event) =>
                setCardinality(event.target.value as "single" | "multi")
              }
            >
              <option value="single">Single label</option>
              <option value="multi">Multiple independent labels</option>
            </select>
          </label>
          <fieldset>
            <legend>Allowed classes</legend>
            {project.label_classes.map((labelClass) => (
              <label key={labelClass.id} className="toggle-row">
                <input
                  type="checkbox"
                  checked={allowedClassIds.includes(labelClass.id)}
                  onChange={() => toggleClass(labelClass.id)}
                />
                {labelClass.name}
              </label>
            ))}
          </fieldset>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(event) => setIsActive(event.target.checked)}
            />
            Active task
          </label>
          <button
            type="button"
            disabled={!key.trim() || !name.trim() || saveLabelSet.isPending}
            onClick={() => saveLabelSet.mutate()}
          >
            {saveLabelSet.isPending ? "Saving..." : "Save classification task"}
          </button>
        </article>

        <article className="dashboard-card">
          <p className="eyebrow">Existing tasks</p>
          <h4>{labelSets.data?.length ?? 0} label sets</h4>
          <div className="dashboard-list">
            {labelSets.data?.map((item) => (
              <div key={item.id} className="dashboard-row">
                <div>
                  <strong>{item.name}</strong>
                  <p>
                    {item.key} · {item.target_kind} · {item.cardinality}
                  </p>
                  <small>
                    {item.allowed_class_ids_json.length} allowed classes · {item.is_active ? "active" : "inactive"}
                  </small>
                </div>
                <button type="button" className="secondary" onClick={() => editLabelSet(item)}>
                  Edit
                </button>
              </div>
            ))}
          </div>
        </article>
      </div>

      <article className="dashboard-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Bulk review</p>
            <h4>{predictions.data?.items.length ?? 0} pending predictions</h4>
          </div>
          <span>{selectedPredictionIds.length} selected</span>
        </div>
        <label>
          Accept into task
          <select
            value={bulkLabelSetId}
            onChange={(event) => setBulkLabelSetId(event.target.value)}
          >
            <option value="">Use each prediction&apos;s task</option>
            {labelSets.data?.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <div className="dashboard-list">
          {predictions.data?.items.map((item) => (
            <label key={item.id} className="annotation-selection-row">
              <input
                type="checkbox"
                checked={selectedPredictionIds.includes(item.id)}
                onChange={() => togglePrediction(item.id)}
              />
              <span>
                <strong>{item.predicted_label}</strong>
                <small>
                  {item.label_set} · {item.target_kind} · {item.target_key}
                </small>
              </span>
              <small>{(item.confidence * 100).toFixed(1)}%</small>
            </label>
          ))}
        </div>
        <div className="version-actions">
          <button
            type="button"
            disabled={!selectedPredictionIds.length || bulkReview.isPending}
            onClick={() => bulkReview.mutate("accept")}
          >
            Accept selected
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!selectedPredictionIds.length || bulkReview.isPending}
            onClick={() => bulkReview.mutate("reject")}
          >
            Reject selected
          </button>
        </div>
      </article>

      <div className="dashboard-grid">
        <article className="dashboard-card">
          <p className="eyebrow">Model comparison</p>
          <h4>Competing classifiers</h4>
          <label>
            Task key
            <input
              value={comparisonTask}
              onChange={(event) => setComparisonTask(event.target.value)}
              placeholder="Leave empty for every task"
            />
          </label>
          <button type="button" onClick={() => void comparison.refetch()}>
            Compare models
          </button>
          {comparison.data && (
            <p>
              {comparison.data.target_count} targets · {comparison.data.agreement_count} agreements · {comparison.data.disagreement_count} disagreements
            </p>
          )}
          <div className="dashboard-list">
            {comparison.data?.targets.map((target) => (
              <div
                key={`${target.label_set}-${target.target_key}`}
                className="dashboard-row"
              >
                <div>
                  <strong>{target.target_key}</strong>
                  <p>
                    {target.label_set} · {target.model_count} models · {target.agreement ? "agreement" : "disagreement"}
                  </p>
                  <small>
                    {target.predictions
                      .map(
                        (item) =>
                          `${item.model_name}: ${item.predicted_label} (${(
                            item.confidence * 100
                          ).toFixed(1)}%)`,
                      )
                      .join(" · ")}
                  </small>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="dashboard-card">
          <p className="eyebrow">Immutable training dataset</p>
          <h4>Freeze reviewed targets</h4>
          <label>
            Dataset name
            <input
              value={snapshotName}
              onChange={(event) => setSnapshotName(event.target.value)}
            />
          </label>
          <label>
            Image, mask, or fragment task
            <select
              value={snapshotLabelSetId}
              onChange={(event) => setSnapshotLabelSetId(event.target.value)}
            >
              <option value="">Choose a task</option>
              {datasetLabelSets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.target_kind}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={
              !snapshotName.trim() ||
              !snapshotLabelSetId ||
              createSnapshot.isPending
            }
            onClick={() => createSnapshot.mutate()}
          >
            {createSnapshot.isPending ? "Freezing..." : "Create immutable snapshot"}
          </button>
          <div className="dashboard-list">
            {snapshots.data?.map((item) => {
              const trainable = item.cardinality === "single" && item.class_count >= 2;
              return (
                <div key={item.id} className="dashboard-row">
                  <div>
                    <strong>{item.name}</strong>
                    <p>
                      {item.target_kind} · {item.cardinality} · {item.sample_count} samples
                    </p>
                    <small>{item.manifest_sha256.slice(0, 16)}…</small>
                    {!trainable && (
                      <small>
                        Multi-label or single-class snapshots remain exportable, but this
                        Ultralytics training path requires at least two single-label classes.
                      </small>
                    )}
                  </div>
                  <button
                    type="button"
                    className="secondary"
                    disabled={!trainable || trainSnapshot.isPending}
                    onClick={() => trainSnapshot.mutate(item)}
                  >
                    {trainSnapshot.isPending ? "Queueing..." : "Train classifier"}
                  </button>
                </div>
              );
            })}
          </div>
        </article>
      </div>

      <article className="dashboard-card">
        <p className="eyebrow">Scientific assignment export</p>
        <h4>Download joined classification data</h4>
        <div className="version-actions">
          <a
            className="button-link"
            href={classificationScientificDownloadUrl(project.id, "csv")}
          >
            Download CSV
          </a>
          <a
            className="button-link"
            href={classificationScientificDownloadUrl(project.id, "npz")}
          >
            Download compressed NumPy
          </a>
        </div>
      </article>
    </section>
  );
}
