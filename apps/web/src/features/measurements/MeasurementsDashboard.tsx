import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { Project } from "../../api/client";
import {
  downloadUrl,
  getMeasurementSummary,
  validateMeasurements,
} from "../phase456/api";

const referenceExample = JSON.stringify(
  {
    default_tolerance_percent: 10,
    references: [
      {
        mask_annotation_id: "paste-mask-id",
        values: [
          { metric: "area_pixels", reference_value: 1000 },
          {
            metric: "total_linear_extension_physical",
            reference_value: 42.5,
            unit: "mm",
          },
        ],
      },
    ],
  },
  null,
  2,
);

function valueList(values: Record<string, number>): string {
  const entries = Object.entries(values);
  return entries.length
    ? entries.map(([unit, value]) => `${value.toFixed(3)} ${unit}`).join(" · ")
    : "Not calibrated";
}

export function MeasurementsDashboard({ project }: { project: Project }) {
  const [referenceJson, setReferenceJson] = useState(referenceExample);
  const [parseError, setParseError] = useState<string | null>(null);
  const summary = useQuery({
    queryKey: ["measurement_summary", project.id],
    queryFn: ({ signal }) => getMeasurementSummary(project.id, signal),
  });
  const validation = useMutation({
    mutationFn: async () => {
      try {
        const payload = JSON.parse(referenceJson) as Record<string, unknown>;
        setParseError(null);
        return validateMeasurements(project.id, payload);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Reference JSON is invalid";
        setParseError(message);
        throw error;
      }
    },
  });
  const validationTotals = useMemo(() => {
    if (!validation.data) return null;
    return `${validation.data.passed_count} passed · ${validation.data.failed_count} failed`;
  }, [validation.data]);

  return (
    <section className="dashboard-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 4</p>
          <h3>Coral measurements</h3>
          <span>
            Revisioned measurements, scientific summaries, and reference validation
          </span>
        </div>
        <div className="version-actions">
          <a
            className="button-link"
            href={downloadUrl(
              `/projects/${project.id}/measurement-export?format=csv`,
            )}
          >
            Export CSV
          </a>
          <a
            className="button-link secondary"
            href={downloadUrl(
              `/projects/${project.id}/measurement-export?format=numpy`,
            )}
          >
            Export NumPy
          </a>
        </div>
      </div>

      {summary.isPending && <p>Calculating project measurements...</p>}
      {summary.error && <p className="form-error">{summary.error.message}</p>}
      {summary.data && (
        <div className="dashboard-grid">
          <article className="dashboard-card">
            <p className="eyebrow">Coverage</p>
            <h4>{summary.data.mask_count} verified masks</h4>
            <p>{summary.data.calibrated_mask_count} masks have physical calibration.</p>
          </article>
          <article className="dashboard-card">
            <p className="eyebrow">Pixel geometry</p>
            <h4>{summary.data.area_pixels.toLocaleString()} px²</h4>
            <p>{summary.data.perimeter_pixels.toLocaleString()} px perimeter</p>
          </article>
          <article className="dashboard-card">
            <p className="eyebrow">Coral structure</p>
            <h4>
              {summary.data.total_linear_extension_pixels.toLocaleString()} px TLE
            </h4>
            <p>{summary.data.contained_box_count} contained polyp boxes</p>
          </article>
          <article className="dashboard-card">
            <p className="eyebrow">Calibrated area</p>
            <h4>{valueList(summary.data.calibrated_area_by_unit)}</h4>
            <p>Surface: {valueList(summary.data.surface_area_by_unit)}</p>
          </article>
          <article className="dashboard-card">
            <p className="eyebrow">Calibrated TLE</p>
            <h4>{valueList(summary.data.calibrated_tle_by_unit)}</h4>
          </article>
          <article className="dashboard-card">
            <p className="eyebrow">Grouping</p>
            <h4>{summary.data.by_class.length} class summaries</h4>
            <p>Species and state groupings are included in the CSV export.</p>
          </article>
        </div>
      )}

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Scientific acceptance</p>
                <h4>Compare manual references</h4>
              </div>
            </div>
            <p>
              Paste mask IDs and manually measured values. ReefVision reports bias,
              MAE, RMSE, percentage error, and tolerance pass/fail without altering
              any annotation.
            </p>
            <label>
              Reference JSON
              <textarea
                rows={18}
                value={referenceJson}
                onChange={(event) => setReferenceJson(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={validation.isPending}
              onClick={() => validation.mutate()}
            >
              {validation.isPending ? "Validating..." : "Run reference comparison"}
            </button>
            {(parseError || validation.error) && (
              <p className="form-error">
                {parseError ?? validation.error?.message}
              </p>
            )}
          </div>
        </div>

        <div className="dashboard-main">
          <div className="dashboard-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Validation report</p>
                <h4>{validationTotals ?? "No reference comparison yet"}</h4>
              </div>
              {validation.data && (
                <span>{validation.data.observation_count} observations</span>
              )}
            </div>
            {validation.data?.warnings.map((warning) => (
              <p key={warning} className="form-warning">
                {warning}
              </p>
            ))}
            <div className="dashboard-list">
              {validation.data?.summaries.map((item) => (
                <article
                  key={`${item.metric}-${item.unit ?? "none"}`}
                  className="dashboard-row"
                >
                  <div>
                    <strong>{item.metric.replaceAll("_", " ")}</strong>
                    <p>
                      Bias {item.mean_bias.toFixed(4)} · MAE{" "}
                      {item.mean_absolute_error.toFixed(4)} · RMSE{" "}
                      {item.root_mean_square_error.toFixed(4)}
                    </p>
                    <small>
                      MAPE{" "}
                      {item.mean_absolute_percentage_error === null
                        ? "unavailable"
                        : `${item.mean_absolute_percentage_error.toFixed(2)}%`}
                      {item.unit ? ` · ${item.unit}` : ""}
                    </small>
                  </div>
                  <span>
                    {item.passed_count} pass / {item.failed_count} fail
                  </span>
                </article>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
