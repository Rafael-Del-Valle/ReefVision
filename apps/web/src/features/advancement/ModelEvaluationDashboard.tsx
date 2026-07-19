import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { Project } from "../../api/client";
import { getImages, getModels } from "../phase456/api";
import {
  evaluateClassification,
  evaluateSegmentation,
  listEmbeddings,
  selectEmbeddingDiversity,
} from "./api";

function percentage(value: number | null): string {
  return value === null ? "Unavailable" : `${(value * 100).toFixed(2)}%`;
}

export function ModelEvaluationDashboard({ project }: { project: Project }) {
  const [segmentationModelId, setSegmentationModelId] = useState("");
  const [classificationModelId, setClassificationModelId] = useState("");
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.25);
  const [matchIouThreshold, setMatchIouThreshold] = useState(0.5);
  const [embeddingModelId, setEmbeddingModelId] = useState("");
  const [diversityWeight, setDiversityWeight] = useState(0.7);
  const [maximumItems, setMaximumItems] = useState(25);
  const [maximumPerGroup, setMaximumPerGroup] = useState("");
  const [baseScoresJson, setBaseScoresJson] = useState("{}");
  const [parseError, setParseError] = useState<string | null>(null);

  const models = useQuery({
    queryKey: ["advancement_models", project.id],
    queryFn: ({ signal }) => getModels(project.id, signal),
  });
  const images = useQuery({
    queryKey: ["advancement_images", project.id],
    queryFn: ({ signal }) => getImages(project.id, signal),
  });
  const embeddings = useQuery({
    queryKey: ["advancement_embeddings", project.id, embeddingModelId],
    queryFn: () => listEmbeddings(project.id, embeddingModelId || undefined),
  });

  const segmenters = useMemo(
    () =>
      models.data?.filter(
        (model) =>
          model.task === "segment" || model.task === "semantic_segment",
      ) ?? [],
    [models.data],
  );
  const classifiers = useMemo(
    () => models.data?.filter((model) => model.task === "classify") ?? [],
    [models.data],
  );
  const knownEmbeddingModels = useMemo(
    () =>
      [
        ...new Set(
          embeddings.data?.map((item) => item.embedding_model_id) ?? [],
        ),
      ].sort(),
    [embeddings.data],
  );
  const classNameById = useMemo(
    () =>
      Object.fromEntries(
        project.label_classes.map((labelClass) => [
          labelClass.id,
          labelClass.name,
        ]),
      ),
    [project.label_classes],
  );

  const segmentation = useMutation({
    mutationFn: () =>
      evaluateSegmentation(project.id, {
        model_id: segmentationModelId,
        image_ids: images.data?.items.map((image) => image.id) ?? [],
        confidence_threshold: confidenceThreshold,
        match_iou_threshold: matchIouThreshold,
        include_accepted_predictions: true,
        include_pending_predictions: true,
      }),
  });
  const classification = useMutation({
    mutationFn: () =>
      evaluateClassification(project.id, {
        model_id: classificationModelId,
        image_ids: images.data?.items.map((image) => image.id) ?? [],
        review_statuses: ["pending"],
        confidence_threshold: confidenceThreshold,
        calibration_bin_count: 10,
      }),
  });
  const diversity = useMutation({
    mutationFn: () => {
      try {
        const parsed = JSON.parse(baseScoresJson) as Record<string, number>;
        setParseError(null);
        return selectEmbeddingDiversity(project.id, {
          embedding_model_id: embeddingModelId,
          candidate_image_ids:
            images.data?.items.map((image) => image.id) ?? [],
          maximum_items: maximumItems,
          diversity_weight: diversityWeight,
          base_scores: parsed,
          maximum_items_per_group: maximumPerGroup
            ? Number(maximumPerGroup)
            : null,
        });
      } catch (error) {
        setParseError(
          error instanceof Error ? error.message : "Base score JSON is invalid",
        );
        throw error;
      }
    },
  });

  const actionError =
    segmentation.error ?? classification.error ?? diversity.error;

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phases 3, 5, and 7</p>
          <h3>Model evaluation and active-learning diversity</h3>
          <span>
            Quantify segmentation, classification, calibration, and visual
            novelty before accepting or retraining models.
          </span>
        </div>
        <span>{images.data?.total ?? 0} loaded images</span>
      </div>

      {(parseError || actionError) && (
        <p className="form-error">{parseError ?? actionError?.message}</p>
      )}

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <p className="eyebrow">Shared thresholds</p>
            <div className="dashboard-grid compact-grid">
              <label>
                Confidence
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={confidenceThreshold}
                  onChange={(event) =>
                    setConfidenceThreshold(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Match IoU
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={matchIouThreshold}
                  onChange={(event) =>
                    setMatchIouThreshold(Number(event.target.value))
                  }
                />
              </label>
            </div>
          </article>

          <article className="dashboard-card">
            <p className="eyebrow">Phase 3</p>
            <h4>Segmentation evaluation</h4>
            <label>
              Segmentation model
              <select
                value={segmentationModelId}
                onChange={(event) => setSegmentationModelId(event.target.value)}
              >
                <option value="">Choose segmenter</option>
                {segmenters.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name} · {model.task}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!segmentationModelId || segmentation.isPending}
              onClick={() => segmentation.mutate()}
            >
              {segmentation.isPending
                ? "Evaluating..."
                : "Evaluate segmentation"}
            </button>
          </article>

          <article className="dashboard-card">
            <p className="eyebrow">Phase 5</p>
            <h4>Classification evaluation</h4>
            <label>
              Classifier
              <select
                value={classificationModelId}
                onChange={(event) =>
                  setClassificationModelId(event.target.value)
                }
              >
                <option value="">Choose classifier</option>
                {classifiers.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!classificationModelId || classification.isPending}
              onClick={() => classification.mutate()}
            >
              {classification.isPending
                ? "Evaluating..."
                : "Evaluate classification"}
            </button>
          </article>

          <article className="dashboard-card">
            <p className="eyebrow">Phase 7</p>
            <h4>Embedding diversity batch</h4>
            <label>
              Embedding model ID
              <input
                list="embedding-model-options"
                value={embeddingModelId}
                onChange={(event) => setEmbeddingModelId(event.target.value)}
                placeholder="e.g. dinov3-vitb16"
              />
              <datalist id="embedding-model-options">
                {knownEmbeddingModels.map((modelId) => (
                  <option key={modelId} value={modelId} />
                ))}
              </datalist>
            </label>
            <div className="dashboard-grid compact-grid">
              <label>
                Maximum items
                <input
                  type="number"
                  min="1"
                  max="5000"
                  value={maximumItems}
                  onChange={(event) =>
                    setMaximumItems(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Diversity weight
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={diversityWeight}
                  onChange={(event) =>
                    setDiversityWeight(Number(event.target.value))
                  }
                />
              </label>
              <label>
                Maximum per group
                <input
                  type="number"
                  min="1"
                  value={maximumPerGroup}
                  placeholder="No cap"
                  onChange={(event) => setMaximumPerGroup(event.target.value)}
                />
              </label>
            </div>
            <label>
              Optional base scores by image ID
              <textarea
                rows={7}
                value={baseScoresJson}
                onChange={(event) => setBaseScoresJson(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!embeddingModelId || diversity.isPending}
              onClick={() => diversity.mutate()}
            >
              {diversity.isPending ? "Selecting..." : "Select diverse batch"}
            </button>
            <p>
              {embeddings.data?.length ?? 0} stored embeddings match the filter.
            </p>
          </article>
        </div>

        <div className="dashboard-main">
          {segmentation.data && (
            <article className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Segmentation result</p>
                  <h4>Mean IoU {percentage(segmentation.data.mean_iou)}</h4>
                </div>
                <span>Dice {percentage(segmentation.data.mean_dice)}</span>
              </div>
              <div className="version-preview-metrics">
                <span>
                  Precision {percentage(segmentation.data.instance_precision)}
                </span>
                <span>
                  Recall {percentage(segmentation.data.instance_recall)}
                </span>
                <span>{segmentation.data.matched_count} matches</span>
                <span>
                  {segmentation.data.false_positive_count} false positives
                </span>
                <span>
                  {segmentation.data.false_negative_count} false negatives
                </span>
              </div>
              {segmentation.data.warnings.map((warning) => (
                <p key={warning} className="form-warning">
                  {warning}
                </p>
              ))}
              <div className="dashboard-list">
                {segmentation.data.per_class.map((item) => (
                  <div
                    key={item.label_class_id ?? "unmapped"}
                    className="dashboard-row"
                  >
                    <div>
                      <strong>
                        {item.label_class_id
                          ? (classNameById[item.label_class_id] ??
                            item.label_class_id)
                          : "Unmapped"}
                      </strong>
                      <p>
                        IoU {percentage(item.mean_iou)} · Dice{" "}
                        {percentage(item.mean_dice)}
                      </p>
                    </div>
                    <span>
                      P {percentage(item.instance_precision)} · R{" "}
                      {percentage(item.instance_recall)}
                    </span>
                  </div>
                ))}
              </div>
            </article>
          )}

          {classification.data && (
            <article className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Classification result</p>
                  <h4>Accuracy {percentage(classification.data.accuracy)}</h4>
                </div>
                <span>{classification.data.sample_count} samples</span>
              </div>
              <div className="version-preview-metrics">
                <span>Macro F1 {percentage(classification.data.macro_f1)}</span>
                <span>
                  Weighted F1 {percentage(classification.data.weighted_f1)}
                </span>
                <span>
                  Calibration error{" "}
                  {percentage(classification.data.expected_calibration_error)}
                </span>
                <span>
                  Brier{" "}
                  {classification.data.top_label_brier_score?.toFixed(4) ??
                    "Unavailable"}
                </span>
              </div>
              {classification.data.warnings.map((warning) => (
                <p key={warning} className="form-warning">
                  {warning}
                </p>
              ))}
              <div className="dashboard-list">
                {classification.data.per_class.map((item) => (
                  <div key={item.label_class_id} className="dashboard-row">
                    <div>
                      <strong>
                        {classNameById[item.label_class_id] ??
                          item.label_class_id}
                      </strong>
                      <p>
                        Precision {percentage(item.precision)} · Recall{" "}
                        {percentage(item.recall)} · F1 {percentage(item.f1)}
                      </p>
                    </div>
                    <span>{item.support} reference samples</span>
                  </div>
                ))}
              </div>
            </article>
          )}

          {diversity.data && (
            <article className="dashboard-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Diversity selection</p>
                  <h4>{diversity.data.selected_count} images selected</h4>
                </div>
                <span>
                  {diversity.data.skipped_missing_embedding_count} missing
                  embeddings
                </span>
              </div>
              {diversity.data.warnings.map((warning) => (
                <p key={warning} className="form-warning">
                  {warning}
                </p>
              ))}
              <div className="dashboard-list">
                {diversity.data.selections.map((item) => (
                  <div key={item.image_id} className="dashboard-row">
                    <div>
                      <strong>
                        #{item.rank} · {item.image_id}
                      </strong>
                      <p>
                        Selection {item.selection_score.toFixed(4)} · novelty{" "}
                        {item.novelty_score.toFixed(4)} · base{" "}
                        {item.normalized_base_score.toFixed(4)}
                      </p>
                      <small>
                        Group {item.group_key ?? "ungrouped"} · nearest{" "}
                        {item.nearest_selected_image_id ?? "none"}
                      </small>
                    </div>
                  </div>
                ))}
              </div>
            </article>
          )}

          {!segmentation.data && !classification.data && !diversity.data && (
            <div className="empty-state">
              <h4>No evaluation result yet</h4>
              <p>
                Choose a model or embedding source to quantify its behavior on
                the current project.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
