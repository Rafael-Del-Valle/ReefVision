import { useState } from "react";
import type {
  AcquisitionQualityReport,
  AcquisitionQualityThresholds,
} from "../../api/client";

export const defaultAcquisitionThresholds: AcquisitionQualityThresholds = {
  min_width_px: 1,
  min_height_px: 1,
  min_sharpness: 25,
  dark_luma_max: 5,
  bright_luma_min: 250,
  max_clipped_fraction: 0.05,
  require_capture_time: false,
  require_camera_metadata: false,
  require_calibration: false,
};

const numericFields = [
  { key: "min_width_px", label: "Minimum width (px)", min: 1, step: 1 },
  { key: "min_height_px", label: "Minimum height (px)", min: 1, step: 1 },
  { key: "min_sharpness", label: "Minimum detail score", min: 0, step: 1 },
  {
    key: "dark_luma_max",
    label: "Dark luma maximum",
    min: 0,
    max: 255,
    step: 1,
  },
  {
    key: "bright_luma_min",
    label: "Bright luma minimum",
    min: 0,
    max: 255,
    step: 1,
  },
  {
    key: "max_clipped_fraction",
    label: "Maximum fraction in each clipping band",
    min: 0,
    max: 1,
    step: 0.01,
  },
] as const;

const requirements = [
  ["require_capture_time", "Require timezone-qualified capture time"],
  ["require_camera_metadata", "Require camera make and model"],
  ["require_calibration", "Require a saved calibration"],
] as const;

export function AcquisitionQualityControls({
  thresholds,
  onChange,
}: {
  thresholds: AcquisitionQualityThresholds;
  onChange: (thresholds: AcquisitionQualityThresholds) => void;
}) {
  return (
    <details open>
      <summary>Acquisition thresholds</summary>
      <p>
        Detail scores flag low texture and possible blur. Clipping uses the
        fraction of opaque source pixels in each decoded 8-bit luma band.
      </p>
      <div className="dashboard-grid compact-grid">
        {numericFields.map((field) => (
          <label key={field.key}>
            {field.label}
            <input
              type="number"
              min={field.min}
              max={"max" in field ? field.max : undefined}
              step={field.step}
              value={
                Number.isFinite(thresholds[field.key])
                  ? thresholds[field.key]
                  : ""
              }
              onChange={(event) =>
                onChange({
                  ...thresholds,
                  [field.key]: event.target.valueAsNumber,
                })
              }
            />
          </label>
        ))}
      </div>
      {requirements.map(([field, label]) => (
        <label className="toggle-row" key={field}>
          <input
            type="checkbox"
            checked={thresholds[field]}
            onChange={(event) =>
              onChange({ ...thresholds, [field]: event.target.checked })
            }
          />
          {label}
        </label>
      ))}
    </details>
  );
}

const staleLabels: Record<string, string> = {
  acquisition_scope_changed: "The image scope has changed.",
  acquisition_metadata_changed: "Capture or calibration metadata has changed.",
  acquisition_media_unavailable: "One or more source images are unavailable.",
};

function formatFraction(value: number | null): string {
  return value === null ? "Unavailable" : (value * 100).toFixed(1) + "%";
}

export function AcquisitionQualityResults({
  report,
  staleReasons,
  onReuseThresholds,
}: {
  report: AcquisitionQualityReport;
  staleReasons: string[];
  onReuseThresholds: (thresholds: AcquisitionQualityThresholds) => void;
}) {
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const pages = Math.ceil(report.images.length / pageSize);
  return (
    <section aria-label="Acquisition quality evidence">
      <h5>Acquisition evidence</h5>
      <p>
        {report.evaluated_image_count} images checked ·{" "}
        {report.unavailable_image_count} unavailable for pixel checks ·
        scientist review required
      </p>
      <p>
        Acquisition findings leave source media and analysis selections
        untouched.
      </p>
      {staleReasons.length > 0 && (
        <p role="status">
          Historical evidence.{" "}
          {staleReasons
            .map((reason) => staleLabels[reason] ?? reason)
            .join(" ")}{" "}
          Rerun quality control to check the current sources.
        </p>
      )}
      <button
        type="button"
        className="secondary"
        onClick={() => onReuseThresholds(report.thresholds)}
      >
        Reuse acquisition thresholds
      </button>
      {report.images.length === 0 && <p>No source images in this scope.</p>}
      {report.images.length > 0 && (
        <details>
          <summary>Image measurements</summary>
          <div className="scientific-table-scroll">
            <table className="scientific-table">
              <thead>
                <tr>
                  <th scope="col">Image</th>
                  <th scope="col">Dimensions (px)</th>
                  <th scope="col">Detail score</th>
                  <th scope="col">Dark clipping</th>
                  <th scope="col">Bright clipping</th>
                  <th scope="col">Capture time (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {report.images
                  .slice(page * pageSize, (page + 1) * pageSize)
                  .map((image) => (
                    <tr key={image.source_sha256}>
                      <th scope="row">{image.filename}</th>
                      <td>
                        {image.width_px} × {image.height_px}
                      </td>
                      <td>
                        {image.measurements.sharpness?.toFixed(2) ??
                          image.measurements.status.replaceAll("_", " ")}
                      </td>
                      <td>
                        {formatFraction(image.measurements.dark_fraction)}
                      </td>
                      <td>
                        {formatFraction(image.measurements.bright_fraction)}
                      </td>
                      <td>{image.capture_time_utc ?? "Unavailable"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <nav className="pagination" aria-label="Acquisition evidence pages">
              <button
                type="button"
                className="secondary"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <span>
                Page {page + 1} of {pages}
              </span>
              <button
                type="button"
                className="secondary"
                disabled={page + 1 >= pages}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </nav>
          )}
        </details>
      )}
      <details>
        <summary>Method and provenance</summary>
        <p>Method {report.method}</p>
        <p>
          Evidence SHA-256 <code>{report.evidence_sha256}</code>
        </p>
        <pre className="json-block">
          {JSON.stringify(report.thresholds, null, 2)}
        </pre>
      </details>
    </section>
  );
}
