import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ScientistWorkspaceInspector } from "./ScientistWorkspaceInspector";
import {
  WORKSPACE_INSPECTOR_VIEWS,
  workspaceInspectorDefinition,
} from "./workspaceInspector";

function renderInspector({
  activeView = "gallery",
  activePreset = "annotation",
  onNavigate = vi.fn(),
}: {
  activeView?: Parameters<typeof ScientistWorkspaceInspector>[0]["activeView"];
  activePreset?: Parameters<
    typeof ScientistWorkspaceInspector
  >[0]["activePreset"];
  onNavigate?: Parameters<typeof ScientistWorkspaceInspector>[0]["onNavigate"];
} = {}) {
  render(
    <ScientistWorkspaceInspector
      activeView={activeView}
      activePreset={activePreset}
      activeClassCount={6}
      annotationType="bbox"
      onNavigate={onNavigate}
    />,
  );

  return { onNavigate };
}

describe("ScientistWorkspaceInspector", () => {
  it("defines context for every current project workspace", () => {
    expect(WORKSPACE_INSPECTOR_VIEWS).toHaveLength(16);
    expect(WORKSPACE_INSPECTOR_VIEWS).toContain("environmental_context");
    expect(WORKSPACE_INSPECTOR_VIEWS).toContain("computed_metrics");
    expect(WORKSPACE_INSPECTOR_VIEWS).toContain("scientific_heatmaps");

    for (const view of WORKSPACE_INSPECTOR_VIEWS) {
      const definition = workspaceInspectorDefinition(view);

      expect(definition.title.length).toBeGreaterThan(0);
      expect(definition.summary.length).toBeGreaterThan(0);
      expect(definition.recordPolicy.length).toBeGreaterThan(0);
      expect(definition.actions.length).toBeGreaterThan(0);
      expect(definition.actions.every((action) => action.target !== view)).toBe(
        true,
      );
    }
  });

  it("preserves scientific truth boundaries for spatial heatmaps", () => {
    renderInspector({ activeView: "scientific_heatmaps" });

    const definition = workspaceInspectorDefinition("scientific_heatmaps");

    expect(definition.boundary).toBe("mixed");
    expect(definition.recordPolicy).toContain(
      "Pending predictions are never counted as verified annotations.",
    );
    expect(screen.getByText("Scientific spatial heatmaps")).toBeInTheDocument();
    expect(screen.getByText("Reviewable evidence")).toBeInTheDocument();
  });
  it("shows the explicit machine-output versus scientist-truth boundary", () => {
    renderInspector();

    const boundary = screen.getByLabelText("Scientific truth boundary");

    expect(within(boundary).getByText("Machine output")).toBeInTheDocument();
    expect(within(boundary).getByText("Provisional")).toBeInTheDocument();
    expect(within(boundary).getByText("Scientist truth")).toBeInTheDocument();
    expect(
      within(boundary).getByText("Explicitly verified"),
    ).toBeInTheDocument();
  });

  it("surfaces morphometrics and scale-calibration guidance without duplicating measurement state", () => {
    renderInspector({
      activeView: "gallery",
      activePreset: "morphometrics",
    });

    expect(
      screen.getByText("Scale calibration & measurements"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Automatic scale-bar evidence must be confirmed/),
    ).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("bbox")).toBeInTheDocument();
    expect(screen.getByText("Canonical workspace")).toBeInTheDocument();
  });

  it("navigates to related canonical tools instead of implementing duplicate tool logic", async () => {
    const onNavigate = vi.fn();

    renderInspector({ onNavigate });

    await userEvent.click(
      screen.getByRole("button", {
        name: /Model Hub/,
      }),
    );

    expect(onNavigate).toHaveBeenCalledWith("models");
  });

  it("makes Review Mode require explicit human verification", () => {
    renderInspector({
      activeView: "review_queue",
      activePreset: "review",
    });

    expect(screen.getByText("Human verification required")).toBeInTheDocument();
    expect(screen.getByText("Review / QA preset")).toBeInTheDocument();
    expect(
      screen.getByText(/Acceptance, correction, or rejection remains/),
    ).toBeInTheDocument();
  });
});
