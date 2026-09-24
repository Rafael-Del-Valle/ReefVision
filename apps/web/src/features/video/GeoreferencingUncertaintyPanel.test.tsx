import { render, screen } from "@testing-library/react";

import { describe, expect, it } from "vitest";

import { GeoreferencingUncertaintyPanel } from "./GeoreferencingUncertaintyPanel";

const telemetry = {
  absolute_time_error_ms: 15 as number | null,
  sync_tolerance_ms: 100,
  within_sync_tolerance: true,
};

const unavailable = {
  available: false,
  method: "not_estimated",
  reason_unavailable: "Formal uncertainty propagation is not yet implemented.",
};

function renderPanel(uncertainty = unavailable, evidence = telemetry) {
  return render(
    <GeoreferencingUncertaintyPanel
      uncertainty={uncertainty}
      telemetry={evidence}
      calibrationVersion="1"
      projectionMethodVersion="opencv-dji-enu-flat-wgs84-v1"
    />,
  );
}

describe("GeoreferencingUncertaintyPanel", () => {
  it("explicitly reports that formal uncertainty is not estimated", () => {
    renderPanel();

    expect(
      screen.getByText("Formal positional uncertainty: Not estimated"),
    ).toBeInTheDocument();

    expect(
      screen.getByText(
        "Formal uncertainty propagation is not yet implemented.",
      ),
    ).toBeInTheDocument();
  });

  it("shows persisted synchronization evidence", () => {
    renderPanel();

    expect(screen.getByText("15.00 ms")).toBeInTheDocument();

    expect(screen.getByText("100.00 ms")).toBeInTheDocument();

    expect(
      screen.getByText("Within synchronization tolerance"),
    ).toBeInTheDocument();
  });

  it("shows an out-of-tolerance observation without inventing accuracy", () => {
    renderPanel(unavailable, {
      ...telemetry,
      absolute_time_error_ms: 140,
      within_sync_tolerance: false,
    });

    expect(screen.getByText("140.00 ms")).toBeInTheDocument();

    expect(screen.getByText("No")).toBeInTheDocument();

    expect(
      screen.getByText("Formal positional uncertainty: Not estimated"),
    ).toBeInTheDocument();
  });

  it("does not invent numeric values for unavailable timing evidence", () => {
    renderPanel(unavailable, {
      ...telemetry,
      absolute_time_error_ms: null,
    });

    expect(screen.getByText("Unavailable")).toBeInTheDocument();

    expect(screen.queryByText("NaN")).not.toBeInTheDocument();

    expect(screen.queryByText("Infinity")).not.toBeInTheDocument();
  });

  it("shows method and calibration provenance", () => {
    renderPanel();

    expect(screen.getByText("not_estimated")).toBeInTheDocument();

    expect(
      screen.getByText("opencv-dji-enu-flat-wgs84-v1"),
    ).toBeInTheDocument();

    expect(screen.getByText("Calibration version")).toBeInTheDocument();
  });
});

describe("Task 17D numeric uncertainty", () => {
  type Uncertainty = Parameters<
    typeof GeoreferencingUncertaintyPanel
  >[0]["uncertainty"];

  function renderNumeric(uncertainty: Uncertainty) {
    return render(
      <GeoreferencingUncertaintyPanel
        uncertainty={uncertainty}
        telemetry={telemetry}
        calibrationVersion="1"
        projectionMethodVersion="opencv-dji-enu-flat-wgs84-v1"
      />,
    );
  }

  it("displays persisted numeric estimates with their units", () => {
    renderNumeric({
      available: true,
      method: "propagated_1sigma",
      reason_unavailable: null,
      horizontal_sigma_m: 2.5,
      horizontal_95_m: 4.9,
      major_axis_95_m: 6.1,
      minor_axis_95_m: 3.2,
      major_axis_bearing_deg: 45,
      telemetry_component_m: 0.8,
      pose_component_m: 1.1,
      height_component_m: 1.4,
      calibration_component_m: 0.6,
    });

    const panel = screen.getByTestId("georeferencing-numeric-uncertainty");

    for (const value of [
      "2.50 m",
      "4.90 m",
      "6.10 m",
      "3.20 m",
      "45.00 deg",
      "0.80 m",
      "1.10 m",
      "1.40 m",
      "0.60 m",
    ]) {
      expect(panel).toHaveTextContent(value);
    }
  });

  it("hides numeric values when uncertainty is unavailable", () => {
    renderNumeric({
      available: false,
      method: "not_estimated",
      reason_unavailable: "Not calculated.",
      horizontal_sigma_m: 2.5,
    });

    expect(
      screen.queryByTestId("georeferencing-numeric-uncertainty"),
    ).not.toBeInTheDocument();

    expect(screen.getByText("Not calculated.")).toBeInTheDocument();
  });

  it("does not invent values when numeric metadata is missing", () => {
    renderNumeric({
      available: true,
      method: "empirical_validation",
      reason_unavailable: null,
    });

    expect(
      screen.getByTestId("georeferencing-numeric-uncertainty"),
    ).toHaveTextContent(
      "Numeric positional uncertainty values are unavailable",
    );

    expect(screen.queryByText("0.00 m")).not.toBeInTheDocument();
  });

  it("preserves zero and partial values without inventing an ellipse", () => {
    renderNumeric({
      available: true,
      method: "combined",
      reason_unavailable: null,
      horizontal_sigma_m: 0,
      horizontal_95_m: Number.POSITIVE_INFINITY,
      major_axis_95_m: 8,
      minor_axis_95_m: null,
      major_axis_bearing_deg: 90,
      pose_component_m: -1,
    });

    const panel = screen.getByTestId("georeferencing-numeric-uncertainty");

    expect(panel).toHaveTextContent("0.00 m");
    expect(panel).toHaveTextContent("8.00 m");
    expect(panel).toHaveTextContent("No ellipse is inferred");

    expect(panel).not.toHaveTextContent("90.00 deg");
    expect(panel).not.toHaveTextContent("Infinity");
    expect(panel).not.toHaveTextContent("NaN");
    expect(panel).not.toHaveTextContent("-1.00 m");
  });
});
