import { useMemo, useState } from "react";

import {
  imageContentUrl,
  predictionMaskUrl,
  type LabelClass,
  type PredictionProposal,
} from "../../api/client";
import { StatusBadge } from "../../components/ui/StatusBadge";

export interface ReviewedPredictionGeometry {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

interface PredictionInspectorProps {
  proposal: PredictionProposal;
  imageWidth: number;
  imageHeight: number;
  classes: LabelClass[];
  reviewedClassId: string;
  reviewedGeometry: ReviewedPredictionGeometry;
  position: number;
  total: number;
  busy: boolean;
  error?: Error | null;
  onClassChange: (classId: string) => void;
  onGeometryChange: (geometry: ReviewedPredictionGeometry) => void;
  onAccept: () => void;
  onReject: () => void;
  onPromptAssist: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onLocate: () => void;
}

function readableKey(key: string): string {
  return key
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function readableValue(value: unknown): string | null {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  return null;
}

export function PredictionInspector({
  proposal,
  imageWidth,
  imageHeight,
  classes,
  reviewedClassId,
  reviewedGeometry,
  position,
  total,
  busy,
  error,
  onClassChange,
  onGeometryChange,
  onAccept,
  onReject,
  onPromptAssist,
  onPrevious,
  onNext,
  onLocate,
}: PredictionInspectorProps) {
  const [editing, setEditing] = useState(false);
  const width = Math.max(proposal.x_max - proposal.x_min, 1);
  const height = Math.max(proposal.y_max - proposal.y_min, 1);
  const padding = Math.max(width, height) * 0.18;
  const crop = {
    x: Math.max(0, proposal.x_min - padding),
    y: Math.max(0, proposal.y_min - padding),
    width:
      Math.min(imageWidth, proposal.x_max + padding) -
      Math.max(0, proposal.x_min - padding),
    height:
      Math.min(imageHeight, proposal.y_max + padding) -
      Math.max(0, proposal.y_min - padding),
  };
  const geometryKind = proposal.geometry_kind ?? "bounding_box";
  const points = (proposal.polygon_json ?? [])
    .map(([x, y]) => `${x},${y}`)
    .join(" ");
  const reviewedClass = classes.find((item) => item.id === reviewedClassId);
  const classChanged = reviewedClassId !== (proposal.label_class_id ?? "");
  const geometryChanged = ["x_min", "y_min", "x_max", "y_max"].some(
    (key) =>
      reviewedGeometry[key as keyof ReviewedPredictionGeometry] !==
      proposal[key as keyof PredictionProposal],
  );
  const provenance = useMemo(
    () =>
      Object.entries({
        ...proposal.inference_settings_json,
        ...(proposal.provenance_json ?? {}),
      })
        .map(([key, value]) => [key, readableValue(value)] as const)
        .filter(
          (entry): entry is readonly [string, string] => entry[1] !== null,
        ),
    [proposal.inference_settings_json, proposal.provenance_json],
  );

  return (
    <section className="prediction-inspector" aria-label="Prediction Inspector">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Review mode</p>
          <h3>Prediction Inspector</h3>
        </div>
        <StatusBadge status={proposal.review_status} />
      </div>
      <p className="annotation-helper">
        Prediction {position} of {total}
      </p>

      <figure className="prediction-crop">
        <svg
          viewBox={`${crop.x} ${crop.y} ${crop.width} ${crop.height}`}
          role="img"
          aria-label={`Crop of ${proposal.predicted_label} prediction on the source image`}
        >
          <image
            href={imageContentUrl(proposal.image_id)}
            x="0"
            y="0"
            width={imageWidth}
            height={imageHeight}
            preserveAspectRatio="none"
          />
          {geometryKind === "raster_mask" && (
            <image
              href={predictionMaskUrl(proposal.id)}
              x="0"
              y="0"
              width={imageWidth}
              height={imageHeight}
              opacity="0.42"
              preserveAspectRatio="none"
            />
          )}
          {geometryKind === "polygon_mask" && points ? (
            <polygon points={points} className="prediction-crop-outline" />
          ) : (
            <rect
              x={proposal.x_min}
              y={proposal.y_min}
              width={width}
              height={height}
              className="prediction-crop-outline"
            />
          )}
        </svg>
        <figcaption>
          {geometryKind.replaceAll("_", " ")} with contextual padding
        </figcaption>
      </figure>
      <button type="button" className="secondary" onClick={onLocate}>
        Locate on image
      </button>

      <div className="prediction-primary-facts">
        <div>
          <span>Predicted class</span>
          <strong>{proposal.predicted_label}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>{proposal.confidence.toFixed(2)}</strong>
        </div>
      </div>
      <div
        className="confidence-meter"
        role="meter"
        aria-label={`Raw model confidence ${proposal.confidence.toFixed(2)}`}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={proposal.confidence}
      >
        <span
          style={{
            width: `${Math.max(0, Math.min(1, proposal.confidence)) * 100}%`,
          }}
        />
      </div>
      <p className="annotation-helper">
        Raw model confidence; no calibrated probability is available.
      </p>

      <dl className="prediction-geometry-facts">
        <div>
          <dt>Geometry</dt>
          <dd>{geometryKind.replaceAll("_", " ")}</dd>
        </div>
        <div>
          <dt>Width</dt>
          <dd>{Math.round(width)} px</dd>
        </div>
        <div>
          <dt>Height</dt>
          <dd>{Math.round(height)} px</dd>
        </div>
        <div>
          <dt>Area</dt>
          <dd>{Math.round(width * height).toLocaleString()} px²</dd>
        </div>
        {proposal.polygon_json && (
          <div>
            <dt>Vertices</dt>
            <dd>{proposal.polygon_json.length}</dd>
          </div>
        )}
      </dl>

      <label>
        Researcher-reviewed class
        <select
          value={reviewedClassId}
          onChange={(event) => onClassChange(event.target.value)}
        >
          {classes
            .filter((item) => item.is_active !== false)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
        </select>
      </label>
      {(classChanged || geometryChanged) && (
        <div className="review-change-summary" role="status">
          <strong>Reviewed result differs</strong>
          {classChanged && (
            <span>Class: {reviewedClass?.name ?? "Unmapped"}</span>
          )}
          {geometryChanged && <span>Geometry edited</span>}
          <small>The original prediction remains unchanged.</small>
        </div>
      )}
      <button
        type="button"
        className="secondary"
        aria-expanded={editing}
        onClick={() => setEditing((value) => !value)}
      >
        {editing ? "Close geometry editor" : "Edit geometry"}
      </button>
      {editing && geometryKind === "bounding_box" && (
        <div className="prediction-coordinate-grid">
          {(["x_min", "y_min", "x_max", "y_max"] as const).map((key) => (
            <label key={key}>
              {readableKey(key)}
              <input
                type="number"
                value={reviewedGeometry[key]}
                onChange={(event) =>
                  onGeometryChange({
                    ...reviewedGeometry,
                    [key]: Number(event.target.value),
                  })
                }
              />
            </label>
          ))}
        </div>
      )}

      <div className="prediction-review-actions">
        <button
          type="button"
          disabled={busy || proposal.review_status !== "pending"}
          onClick={onAccept}
        >
          {classChanged || geometryChanged
            ? "Accept reviewed result"
            : "Accept prediction"}
        </button>
        <button
          type="button"
          className="danger-ghost"
          disabled={busy || proposal.review_status !== "pending"}
          onClick={onReject}
        >
          Reject prediction
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || proposal.review_status !== "pending"}
          onClick={onPromptAssist}
        >
          Prompt Assist
        </button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          The review action could not be saved. {error.message}
        </p>
      )}
      <div className="prediction-navigation">
        <button
          type="button"
          className="secondary"
          disabled={position <= 1}
          onClick={onPrevious}
        >
          Previous prediction (K)
        </button>
        <button
          type="button"
          className="secondary"
          disabled={position >= total}
          onClick={onNext}
        >
          Next prediction (J)
        </button>
      </div>

      <details className="prediction-provenance">
        <summary>Model provenance</summary>
        <dl>
          <div>
            <dt>Model</dt>
            <dd>{proposal.model_display_name}</dd>
          </div>
          <div>
            <dt>Inference run</dt>
            <dd>{proposal.inference_job_id}</dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>{new Date(proposal.created_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt>Model checksum</dt>
            <dd>{proposal.model_checksum}</dd>
          </div>
          {provenance.map(([key, value]) => (
            <div key={key}>
              <dt>{readableKey(key)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </details>
      <details>
        <summary>Original model output</summary>
        <p>
          {proposal.predicted_label} · Confidence{" "}
          {proposal.confidence.toFixed(2)}
        </p>
        <p>
          Bounds: {proposal.x_min.toFixed(1)}, {proposal.y_min.toFixed(1)} →{" "}
          {proposal.x_max.toFixed(1)}, {proposal.y_max.toFixed(1)} px
        </p>
      </details>
    </section>
  );
}
