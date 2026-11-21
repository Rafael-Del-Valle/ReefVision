import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "../../api/client";
import {
  hasScientificNodeControls,
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
  vi.spyOn(api, "request").mockResolvedValue([
    {
      id: "mesh-asset",
      project_id: "local-study",
      original_filename: "colony.obj",
      source_format: "obj",
      parse_status: "succeeded",
    },
  ] as never);

  expect(hasScientificNodeControls("mesh_surface_preview")).toBe(true);
  renderControls("mesh_surface_preview");
  await screen.findByRole("option", { name: "colony.obj · OBJ · parsed" });
  fireEvent.change(screen.getByLabelText("Project 3D original"), {
    target: { value: "mesh-asset" },
  });
  fireEvent.change(screen.getByLabelText("Meters per source unit"), {
    target: { value: "0.001" },
  });
  fireEvent.change(screen.getByLabelText("Calibration evidence"), {
    target: { value: "Scale bar measured in the source reconstruction" },
  });

  expect(screen.getByRole("status").textContent).toContain(
    '"asset_id":"mesh-asset"',
  );
  expect(screen.getByRole("status").textContent).toContain(
    '"meters_per_unit":0.001',
  );
  expect(screen.getByText(/Surface routes are geometric paths/)).toBeVisible();
  const extrema = screen.getByLabelText(
    "Preserve source-axis extrema faces in preview",
  );
  const patches = screen.getByLabelText(
    "Preserve disconnected mesh patches in preview",
  );
  expect(extrema).not.toBeChecked();
  expect(patches).not.toBeChecked();
  fireEvent.click(extrema);
  fireEvent.click(patches);
  expect(screen.getByRole("status").textContent).toContain(
    '"preserve_axis_extrema_in_preview":true',
  );
  expect(screen.getByRole("status").textContent).toContain(
    '"preserve_edge_connected_patches_in_preview":true',
  );
  fireEvent.click(extrema);
  expect(screen.getByRole("status").textContent).toContain(
    '"preserve_axis_extrema_in_preview":false',
  );
  expect(screen.getByText(/Display sampling only/)).toBeVisible();
});

it("keeps point-cloud measurements distinct from surface and branch claims", async () => {
  vi.spyOn(api, "request").mockResolvedValue([
    {
      id: "cloud-asset",
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
