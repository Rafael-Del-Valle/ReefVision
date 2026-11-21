import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { imageContentUrl, request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { PairPlot } from "./ScientificComparisonPanel";
import {
  staticComparisonPath,
  staticLineageLabels,
  type StaticComparisonRecord,
  type StaticStatistics,
} from "./staticComparisonApi";

const pageSize = 25;
const number = (value: number | null) =>
  value === null
    ? "Unavailable"
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(
        value,
      );
const interval = (value: [number, number] | null) =>
  value ? value.map(number).join(" to ") : "Unavailable";
const outcomeLabels: Record<string, string> = {
  scored: "Scored",
  class_not_mapped: "Class missing from model mapping",
  output_class_mismatch: "Output class mismatch",
  inference_failed: "Inference failed",
  prediction_missing: "Missing prediction",
  excluded_image: "Excluded image",
  unreviewed_image: "Image lacks review",
};

function Statistics({
  value,
  icc,
}: {
  value: StaticStatistics;
  icc: string | null;
}) {
  return (
    <dl className="scientific-comparison-stats">
      <div>
        <dt>Scored images</dt>
        <dd>{value.observation_count}</dd>
      </div>
      <div>
        <dt>Distinct frozen groups</dt>
        <dd>{value.frozen_group_count}</dd>
      </div>
      <div>
        <dt>Ungrouped images</dt>
        <dd>{value.ungrouped_observation_count}</dd>
      </div>
      <div>
        <dt>Bias (counts)</dt>
        <dd>{number(value.bias)}</dd>
      </div>
      <div>
        <dt>Mean absolute error (counts)</dt>
        <dd>{number(value.mean_absolute_error)}</dd>
      </div>
      <div>
        <dt>RMSE (counts)</dt>
        <dd>{number(value.root_mean_squared_error)}</dd>
      </div>
      <div>
        <dt>Mean signed percentage error</dt>
        <dd>{number(value.mean_signed_percentage_error)}</dd>
      </div>
      <div>
        <dt>Mean absolute percentage error</dt>
        <dd>{number(value.mean_absolute_percentage_error)}</dd>
      </div>
      <div>
        <dt>Percentage denominator</dt>
        <dd>
          {value.percentage_denominator} images · {value.zero_reference_count}{" "}
          zero references excluded
        </dd>
      </div>
      <div>
        <dt>95% bias interval</dt>
        <dd>{interval(value.bias_ci95)}</dd>
      </div>
      <div>
        <dt>95% MAE interval</dt>
        <dd>{interval(value.mae_ci95)}</dd>
      </div>
      <div>
        <dt>Agreement limits (counts)</dt>
        <dd>{interval(value.limits_of_agreement)}</dd>
      </div>
      {icc && (
        <div>
          <dt>ICC({icc})</dt>
          <dd>{number(value.icc)}</dd>
        </div>
      )}
    </dl>
  );
}

export function StaticComparisonResult({
  projectId,
  record,
  onOpenImage,
}: {
  projectId: string;
  record: StaticComparisonRecord;
  onOpenImage?: (imageId: string) => void;
}) {
  const cache = useQueryClient();
  const [modelId, setModelId] = useState(record.snapshot.evidence.models[0].id);
  const [classId, setClassId] = useState("");
  const [offset, setOffset] = useState(0);
  const [figure, setFigure] = useState("identity_scatter");
  const [title, setTitle] = useState("");
  const [style, setStyle] = useState("grayscale");
  const snapshot = record.snapshot;
  const { evidence } = snapshot;
  const model =
    evidence.models.find((row) => row.id === modelId) ?? evidence.models[0];
  const outcome =
    snapshot.results.find((row) => row.model_id === model.id) ??
    snapshot.results[0];
  const statistics = classId
    ? outcome.class_statistics[classId]
    : outcome.total_statistics;
  const paired = classId
    ? snapshot.class_model_differences[classId]
    : snapshot.total_model_difference;
  const names = new Map(evidence.classes.map((row) => [row.id, row.name]));
  const images = new Map(evidence.images.map((row) => [row.id, row]));
  const countRows = outcome.images.map((row) => ({
    ...row,
    counts: classId
      ? row.counts.filter((count) => count.class_id === classId)
      : row.counts,
  }));
  const pairs = countRows.flatMap((row) =>
    row.counts.every((count) => count.prediction !== null)
      ? [
          {
            individual_id: images.get(row.image_id)?.name ?? row.image_id,
            reference: row.counts.reduce(
              (total, count) => total + count.reference,
              0,
            ),
            estimate: row.counts.reduce(
              (total, count) => total + (count.prediction ?? 0),
              0,
            ),
          },
        ]
      : [],
  );
  const exports = `${getApiBaseUrl()}${staticComparisonPath(projectId)}/${record.id}/export`;
  const figureBase = `/projects/${projectId}/research-reports`;
  const publication = useMutation({
    mutationFn: () =>
      request<{ id: string }>(figureBase, {
        method: "POST",
        body: JSON.stringify({
          source_kind: "static_comparison",
          source_id: record.id,
          figure,
          title: title.trim(),
          style,
        }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["research-reports", projectId],
      });
    },
  });
  return (
    <section aria-label="Static count comparison result" aria-live="polite">
      <h3>{evidence.reference_name}</h3>
      <p>
        <strong>{staticLineageLabels[snapshot.evaluation_status]}</strong>
      </p>
      {record.stale && (
        <p role="status">
          Local evidence changed. Downloads contain the historical result.
        </p>
      )}
      <p>
        {evidence.images.length} frozen images ·{" "}
        {evidence.outside_split_image_count} outside the selected split.
      </p>
      <div className="form-row">
        <label>
          Inspect detector
          <select
            value={modelId}
            onChange={(event) => {
              setModelId(event.target.value);
              setOffset(0);
            }}
          >
            {evidence.models.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Inspect class
          <select
            value={classId}
            onChange={(event) => {
              setClassId(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Total across selected classes</option>
            {evidence.classes.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p>
        {model.name} · {staticLineageLabels[model.lineage.status]}
      </p>
      {model.lineage.reasons.length > 0 && (
        <ul>
          {model.lineage.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <Statistics value={statistics} icc={evidence.options.icc} />
      {paired && (
        <p>
          Paired absolute-error change (second minus first){" "}
          {number(paired.absolute_error_change)} counts
          {" · "}
          {paired.observation_count} common images in{" "}
          {paired.frozen_group_count} frozen groups
          {" · "}95% interval {interval(paired.absolute_error_change_ci95)}.
        </p>
      )}
      {pairs.length > 0 && (
        <div className="scientific-comparison-plots">
          <PairPlot
            modelName={model.name}
            pairs={pairs}
            unit="count"
            difference={false}
            bias={statistics.bias ?? 0}
            limits={null}
          />
          <PairPlot
            modelName={model.name}
            pairs={pairs}
            unit="count"
            difference
            bias={statistics.bias ?? 0}
            limits={statistics.limits_of_agreement}
          />
        </div>
      )}
      <details>
        <summary>Image counts and exclusions</summary>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Source image</th>
                <th scope="col">Group</th>
                <th scope="col">Class</th>
                <th scope="col">Reference</th>
                <th scope="col">Model</th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {countRows.slice(offset, offset + pageSize).flatMap((row) => {
                const image = images.get(row.image_id);
                const localId =
                  record.source_id_map[row.image_id] ?? row.image_id;
                return row.counts.map((count) => (
                  <tr key={`${row.image_id}-${count.class_id}`}>
                    <td>
                      {onOpenImage ? (
                        <button
                          type="button"
                          onClick={() => onOpenImage(localId)}
                        >
                          {image?.name ?? localId}
                        </button>
                      ) : (
                        <a
                          href={imageContentUrl(localId)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {image?.name ?? localId}
                        </a>
                      )}
                    </td>
                    <td>{image?.group_key || "Ungrouped"}</td>
                    <td>{names.get(count.class_id) ?? count.class_id}</td>
                    <td>{count.reference}</td>
                    <td>{count.prediction ?? "—"}</td>
                    <td>
                      {outcomeLabels[count.status] ?? count.status}
                      {row.message && <p>{row.message}</p>}
                    </td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </div>
        <nav className="pagination" aria-label="Static comparison image pages">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(offset - pageSize)}
          >
            Previous images
          </button>
          <span>
            {offset + 1}–{Math.min(offset + pageSize, countRows.length)} of{" "}
            {countRows.length} images
          </span>
          <button
            type="button"
            disabled={offset + pageSize >= countRows.length}
            onClick={() => setOffset(offset + pageSize)}
          >
            Next images
          </button>
        </nav>
      </details>
      <details>
        <summary>Evidence and interpretation</summary>
        <p>
          Reference manifest <code>{evidence.reference_sha256}</code>
        </p>
        <p>
          {model.provider_name} {outcome.runtime_provider_version} · checkpoint{" "}
          <code>{model.checkpoint_sha256}</code>
        </p>
        <p>
          Confidence {evidence.options.inference.confidence_threshold} · IoU{" "}
          {evidence.options.inference.iou_threshold} · device{" "}
          {evidence.options.inference.device}
        </p>
        <ul>
          {snapshot.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
      <p>
        <a href={`${exports}?format=csv`}>Download count CSV</a>
        {" · "}
        <a href={`${exports}?format=json`}>Download evidence JSON</a>
      </p>
      <details>
        <summary>Publish count figure</summary>
        <p>
          The figure uses per-image totals across the selected classes for all
          included detectors.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            publication.mutate();
          }}
        >
          <label>
            Figure type
            <select
              value={figure}
              onChange={(event) => setFigure(event.target.value)}
            >
              <option value="identity_scatter">Identity scatter</option>
              <option value="bland_altman">Bland–Altman</option>
            </select>
          </label>
          <label>
            Figure title
            <input
              required
              value={title}
              maxLength={120}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label>
            Figure style
            <select
              value={style}
              onChange={(event) => setStyle(event.target.value)}
            >
              <option value="grayscale">Grayscale</option>
              <option value="accessible_color">Accessible color</option>
            </select>
          </label>
          <button
            type="submit"
            disabled={record.stale || !title.trim() || publication.isPending}
          >
            Save publication figure
          </button>
        </form>
        {publication.error && <p role="alert">{publication.error.message}</p>}
        {publication.data && (
          <p>
            <a
              href={`${getApiBaseUrl()}${figureBase}/${publication.data.id}/figure.svg`}
            >
              Open figure SVG
            </a>
            {" · "}
            <a
              href={`${getApiBaseUrl()}${figureBase}/${publication.data.id}/table.csv`}
            >
              Download figure table
            </a>
          </p>
        )}
      </details>
    </section>
  );
}
