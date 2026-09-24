import type { GeoReferencedObservationDetail } from "./videoGeoreferencedObservationsApi";

type ObservationUncertainty = GeoReferencedObservationDetail["uncertainty"];

type SynchronizationEvidence = Pick<
  GeoReferencedObservationDetail["telemetry"],
  "absolute_time_error_ms" | "sync_tolerance_ms" | "within_sync_tolerance"
>;

interface GeoreferencingUncertaintyPanelProps {
  uncertainty: ObservationUncertainty;
  telemetry: SynchronizationEvidence;
  calibrationVersion: string;
  projectionMethodVersion: string;
}

function milliseconds(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "Unavailable";
  }

  return `${value.toFixed(2)} ms`;
}

function validLength(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function numericUncertainty(uncertainty: ObservationUncertainty) {
  const major = uncertainty.major_axis_95_m;
  const minor = uncertainty.minor_axis_95_m;

  const ellipseComplete =
    validLength(major) && validLength(minor) && major >= minor;

  const bearing = uncertainty.major_axis_bearing_deg;

  const validBearing =
    ellipseComplete &&
    typeof bearing === "number" &&
    Number.isFinite(bearing) &&
    bearing >= 0 &&
    bearing < 360;

  const values: Array<{
    label: string;
    value: number | null | undefined;
    unit: "m" | "deg";
  }> = [
    {
      label: "Horizontal sigma (1 sigma)",
      value: uncertainty.horizontal_sigma_m,
      unit: "m",
    },
    {
      label: "Horizontal 95% radius",
      value: uncertainty.horizontal_95_m,
      unit: "m",
    },
    { label: "95% ellipse major axis", value: major, unit: "m" },
    { label: "95% ellipse minor axis", value: minor, unit: "m" },
    {
      label: "95% ellipse major-axis bearing",
      value: validBearing ? bearing : null,
      unit: "deg",
    },
    {
      label: "Telemetry uncertainty component",
      value: uncertainty.telemetry_component_m,
      unit: "m",
    },
    {
      label: "Pose uncertainty component",
      value: uncertainty.pose_component_m,
      unit: "m",
    },
    {
      label: "Height uncertainty component",
      value: uncertainty.height_component_m,
      unit: "m",
    },
    {
      label: "Calibration uncertainty component",
      value: uncertainty.calibration_component_m,
      unit: "m",
    },
  ];

  const rows = values.flatMap((item) => {
    const value = item.value;

    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
      return [];
    }

    return [
      {
        label: item.label,
        formatted: `${value.toFixed(2)} ${item.unit}`,
      },
    ];
  });

  return {
    rows,
    incompleteEllipse:
      (validLength(major) || validLength(minor)) && !ellipseComplete,
  };
}

export function GeoreferencingUncertaintyPanel({
  uncertainty,
  telemetry,
  calibrationVersion,
  projectionMethodVersion,
}: GeoreferencingUncertaintyPanelProps) {
  const numeric = uncertainty.available
    ? numericUncertainty(uncertainty)
    : null;
  return (
    <section
      className="management-card"
      aria-label="Georeferencing uncertainty"
      data-testid="georeferencing-uncertainty-panel"
      data-uncertainty-available={uncertainty.available ? "true" : "false"}
    >
      <p className="eyebrow">Geographic evidence</p>

      <h3>Uncertainty and synchronization</h3>

      {uncertainty.available ? (
        <p role="status">
          Uncertainty metadata is marked available. No positional error radius
          is inferred by this display.
        </p>
      ) : (
        <div role="status">
          <strong>Formal positional uncertainty: Not estimated</strong>

          <p className="annotation-helper">
            {uncertainty.reason_unavailable ??
              "The persisted observation does not include a formal uncertainty estimate."}
          </p>
        </div>
      )}

      {numeric && (
        <div data-testid="georeferencing-numeric-uncertainty">
          <h4>Persisted positional uncertainty</h4>

          {numeric.rows.length === 0 ? (
            <p>
              Numeric positional uncertainty values are unavailable in this
              observation.
            </p>
          ) : (
            <dl className="annotation-selection-list">
              {numeric.rows.map((item) => (
                <div className="annotation-selection-row" key={item.label}>
                  <dt>{item.label}</dt>
                  <dd>{item.formatted}</dd>
                </div>
              ))}
            </dl>
          )}

          {numeric.incompleteEllipse && (
            <p>
              The persisted ellipse parameters are incomplete or inconsistent.
              No ellipse is inferred.
            </p>
          )}

          <p className="annotation-helper">
            These are persisted uncertainty estimates, not independently
            validated geographic accuracy measurements.
          </p>
        </div>
      )}

      <dl className="annotation-selection-list">
        <div className="annotation-selection-row">
          <dt>Uncertainty method</dt>
          <dd>{uncertainty.method}</dd>
        </div>

        <div className="annotation-selection-row">
          <dt>Absolute synchronization difference</dt>
          <dd>{milliseconds(telemetry.absolute_time_error_ms)}</dd>
        </div>

        <div className="annotation-selection-row">
          <dt>Synchronization tolerance</dt>
          <dd>{milliseconds(telemetry.sync_tolerance_ms)}</dd>
        </div>

        <div className="annotation-selection-row">
          <dt>Within synchronization tolerance</dt>
          <dd>{telemetry.within_sync_tolerance ? "Yes" : "No"}</dd>
        </div>

        <div className="annotation-selection-row">
          <dt>Calibration version</dt>
          <dd>{calibrationVersion}</dd>
        </div>

        <div className="annotation-selection-row">
          <dt>Projection method version</dt>
          <dd>{projectionMethodVersion}</dd>
        </div>
      </dl>

      <p className="annotation-helper">
        Synchronization differences describe temporal alignment. They are not
        geographic accuracy, horizontal error, or positional confidence
        intervals.
      </p>
    </section>
  );
}
