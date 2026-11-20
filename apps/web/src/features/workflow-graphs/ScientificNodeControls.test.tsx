import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "../../api/client";
import * as ecologyApi from "../ecology/ecologyAnalysisApi";
import * as workflowApi from "./workflowGraphApi";
import {
  hasScientificNodeControls,
  scientificConfigurationIssue,
  ScientificNodeControls,
} from "./ScientificNodeControls";

const comparison = {
  id: "comparison",
  stale: false,
  snapshot: { options: { name: "Baseline" } },
};

function renderControls(type: string, initial: Record<string, unknown> = {}) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Fixture() {
    const [config, setConfig] = useState(initial);
    return (
      <>
        <ScientificNodeControls
          nodeType={type}
          projectId="local-study"
          parameters={config}
          onChange={setConfig}
        />
        <output>{JSON.stringify(config)}</output>
      </>
    );
  }
  return render(
    <QueryClientProvider client={cache}>
      <Fixture />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

it("binds a guided paired contrast to an eligible reviewed source", async () => {
  const record = {
    id: "growth",
    content_sha256: "a".repeat(64),
    stale: false,
    snapshot: {
      reviewed_by: "Reviewer",
      selection: {
        kind: "growth",
        metric: "box_width",
        sources: [],
        sampling_plan: [
          {
            experimental_unit_id: "Tank A",
            organism_keys: ["a"],
            dates: ["2026-01-01", "2026-01-08"],
          },
        ],
      },
      result: { kind: "growth" },
    },
  } as unknown as ecologyApi.EcologyAnalysis;
  vi.spyOn(ecologyApi, "listEcologyAnalyses").mockResolvedValue({
    items: [record],
    total: 1,
  });
  vi.spyOn(api, "request").mockResolvedValue(record);
  renderControls("paired_growth_contrast");
  expect(hasScientificNodeControls("paired_growth_contrast")).toBe(true);
  expect(await screen.findByRole("option", { name: /Reviewer/ })).toBeVisible();
  fireEvent.change(screen.getByLabelText("Frozen growth analysis"), {
    target: { value: "growth" },
  });
  fireEvent.change(await screen.findByLabelText("Baseline UTC date"), {
    target: { value: "2026-01-01" },
  });
  fireEvent.change(screen.getByLabelText("Follow-up UTC date"), {
    target: { value: "2026-01-08" },
  });
  fireEvent.change(screen.getByLabelText("Independent unit type"), {
    target: { value: "tank" },
  });
  fireEvent.change(screen.getByLabelText("Declared estimand"), {
    target: { value: "Mean within-tank change" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Exclude a unit/ }));
  const parameters = JSON.parse(screen.getByRole("status").textContent || "{}");
  expect(parameters).toMatchObject({
    analysis_id: "growth",
    source_sha256: record.content_sha256,
    experimental_unit_type: "tank",
    missingness_policy: "complete_unit",
  });
  expect(
    scientificConfigurationIssue("paired_growth_contrast", parameters),
  ).toBeUndefined();
  expect(
    scientificConfigurationIssue("paired_growth_contrast", {
      ...parameters,
      source_sha256: "",
    }),
  ).toBeTruthy();
});

it("replays a current project comparison and clears the calculation choice", async () => {
  const request = vi.spyOn(api, "request").mockImplementation(async (path) => {
    expect(path).toContain("/projects/local-study/");
    return (path.includes("/static-comparisons") ? [] : [comparison]) as never;
  });
  renderControls("scientific_comparison", {
    configuration: { name: "Old settings" },
  });
  fireEvent.change(screen.getByLabelText("Operation"), {
    target: { value: "comparison_id" },
  });
  await screen.findByRole("option", { name: "Baseline" });
  fireEvent.change(screen.getByLabelText("Saved comparison"), {
    target: { value: "comparison" },
  });
  expect(screen.getByRole("status").textContent).toContain(
    '"comparison_id":"comparison"',
  );
  expect(screen.getByRole("status").textContent).not.toContain(
    '"configuration"',
  );
  expect(request).toHaveBeenCalled();
});

it("uses the standalone acquisition contract and validates clipping bands", async () => {
  vi.spyOn(api, "getDatasetVersions").mockResolvedValue([]);
  renderControls("image_acquisition_quality");
  fireEvent.change(screen.getByLabelText("Dark luma maximum"), {
    target: { value: "252" },
  });
  expect(screen.getByRole("alert")).toHaveTextContent("Dark luma maximum");
  expect(screen.getByRole("status").textContent).toContain(
    '"dark_luma_max":252',
  );
});

it("configures a project-owned mesh measurement from the guided workspace", async () => {
  const hash = "a".repeat(64);
  const asset = {
    id: "mesh-asset",
    project_id: "local-study",
    original_filename: "colony.obj",
    source_format: "obj",
    sha256: hash,
    parse_status: "succeeded",
    parse_summary: { source_kind_resolved: "mesh" },
  };
  vi.spyOn(workflowApi, "listProjectSpatialAssets")
    .mockResolvedValueOnce([
      { ...asset, parse_status: "queued", parse_summary: null },
    ] as never)
    .mockResolvedValue([asset] as never);

  expect(hasScientificNodeControls("mesh_surface_preview")).toBe(true);
  renderControls("mesh_surface_preview", {
    obj_text: "v 0 0 0",
    expected_source_payload_sha256: "b".repeat(64),
    calibration_review: { independent_reviewer_id: "original-reviewer" },
    surface_path_vertex_pairs: [[0, 1]],
    anatomical_branch: { base_landmark: "previous branch" },
  });
  const pending = await screen.findByRole("option", {
    name: "colony.obj · OBJ · queued (unavailable)",
  });
  expect(pending).toBeDisabled();
  await screen.findByRole(
    "option",
    { name: "colony.obj · OBJ · parsed" },
    { timeout: 2500 },
  );
  fireEvent.change(screen.getByLabelText("Project 3D original"), {
    target: { value: "mesh-asset" },
  });
  fireEvent.change(screen.getByLabelText("Meters per source unit"), {
    target: { value: "0.001" },
  });
  fireEvent.change(screen.getByLabelText("Calibration evidence"), {
    target: { value: "Scale bar measured in the source reconstruction" },
  });

  expect(
    JSON.parse(screen.getByRole("status").textContent ?? "{}"),
  ).toMatchObject({
    asset_id: "mesh-asset",
    expected_source_payload_sha256: hash,
    obj_text: null,
    calibration_review: null,
    calibration_review_id: null,
    surface_path_vertex_pairs: null,
    anatomical_branch: null,
  });
  expect(screen.getByRole("status").textContent).toContain(
    '"meters_per_unit":0.001',
  );
  const timestamp = "2026-01-01T11:34:56.123456-05:00";
  fireEvent.change(screen.getByLabelText("Acquisition timestamp"), {
    target: { value: timestamp },
  });
  expect(screen.getByRole("status")).toHaveTextContent(
    `"observed_at_utc":"${timestamp}"`,
  );
  expect(screen.getByText(/Surface routes are geometric paths/)).toBeVisible();
});

it("keeps point-cloud measurements distinct from surface and branch claims", async () => {
  vi.spyOn(workflowApi, "listProjectSpatialAssets").mockResolvedValue([
    {
      id: "cloud-asset",
      sha256: "c".repeat(64),
      parse_summary: { source_kind_resolved: "point_cloud" },
      project_id: "local-study",
      original_filename: "survey.ply",
      source_format: "ply",
      parse_status: "succeeded",
    },
  ] as never);

  expect(hasScientificNodeControls("point_cloud_preview")).toBe(true);
  renderControls("point_cloud_preview");
  await screen.findByRole("option", { name: "survey.ply · PLY · parsed" });
  expect(
    screen.getByText(
      /does not infer surface area, volume, or anatomical branch length/,
    ),
  ).toBeVisible();
  fireEvent.click(screen.getByLabelText("Preserve measured chord endpoints"));
  expect(screen.getByRole("status").textContent).toContain(
    '"preserve_measured_chord_endpoints_in_preview":true',
  );
});

it("guides registration and correspondence review for longitudinal comparison", () => {
  expect(hasScientificNodeControls("mesh_longitudinal_comparison")).toBe(true);
  renderControls("mesh_longitudinal_comparison");

  fireEvent.change(screen.getByLabelText("Registration source frame"), {
    target: { value: "survey-2025" },
  });
  fireEvent.change(screen.getByLabelText("Registration target frame"), {
    target: { value: "survey-2026" },
  });
  fireEvent.change(screen.getByLabelText("Registration evidence note"), {
    target: { value: "Six surveyed control correspondences" },
  });
  fireEvent.change(screen.getByLabelText("Earlier observation ID"), {
    target: { value: "obs-before" },
  });
  fireEvent.change(screen.getByLabelText("Later observation ID"), {
    target: { value: "obs-after" },
  });
  fireEvent.change(screen.getByLabelText("Matching observer"), {
    target: { value: "observer-a" },
  });
  fireEvent.change(screen.getByLabelText("Correspondence evidence note"), {
    target: { value: "Tag and morphology agree" },
  });

  const output = screen.getByRole("status").textContent ?? "";
  expect(output).toContain('"source_frame_id":"survey-2025"');
  expect(output).toContain('"before_observation_id":"obs-before"');
  expect(
    screen.getByText(/Supporting review is durable audit evidence/),
  ).toBeVisible();
});

it("requires measured registration diagnostics and preserves explicit zero residual", () => {
  renderControls("mesh_longitudinal_comparison");
  fireEvent.change(screen.getByLabelText("Registration source frame"), {
    target: { value: "earlier-frame" },
  });
  const saved = () =>
    JSON.parse(screen.getByRole("status").textContent ?? "{}");
  expect(saved().registration_evidence.rms_residual_m).toBeUndefined();
  expect(saved().registration_evidence.correspondence_count).toBeUndefined();
  expect(
    scientificConfigurationIssue("mesh_longitudinal_comparison", saved()),
  ).toMatch(/residual.*correspondences/);
  fireEvent.change(screen.getByLabelText("RMS residual (meters)"), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText("Correspondence count"), {
    target: { value: "3" },
  });
  expect(saved().registration_evidence.rms_residual_m).toBe(0);
  expect(
    scientificConfigurationIssue("mesh_longitudinal_comparison", saved()),
  ).toBeUndefined();
});

it("selects an inspect-only local provider manifest for a saved workflow", async () => {
  vi.spyOn(api, "request").mockResolvedValue([
    {
      provider_id: "grounding_dino",
      display_name: "Grounding DINO",
      source_kind: "built_in",
      discovery_status: "built_in",
      source_filename: null,
      source_sha256: null,
    },
    {
      provider_id: "local_depth",
      display_name: "Local Depth Inspector",
      source_kind: "local_manifest",
      discovery_status: "valid",
      source_filename: "local-depth.json",
      source_sha256: "a".repeat(64),
    },
  ] as never);

  expect(hasScientificNodeControls("provider_manifest_snapshot")).toBe(true);
  renderControls("provider_manifest_snapshot");
  await screen.findByRole("option", { name: "Local Depth Inspector · valid" });
  fireEvent.change(screen.getByLabelText("Local provider manifest"), {
    target: { value: "local_depth" },
  });

  const output = screen.getByRole("status").textContent ?? "";
  expect(output).toContain('"record_id":"local_depth"');
  expect(output).toContain(`"expected_source_sha256":"${"a".repeat(64)}"`);
  expect(
    screen.getByText(/snapshots metadata only and never executes/),
  ).toBeVisible();
});
