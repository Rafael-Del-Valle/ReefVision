import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { MaskCoveragePanel } from "./MaskCoveragePanel";

const project = {
  id: "00000000-0000-4000-8000-000000000001",
  name: "Coverage survey",
  slug: "coverage-survey",
  description: null,
  storage_root: "projects/coverage-survey",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-11-05T00:00:00Z",
  updated_at: "2026-11-05T00:00:00Z",
  archived_at: null,
  label_classes: [],
} satisfies Project;

const imageId = "00000000-0000-4000-8000-000000000011";
const targetClass = "00000000-0000-4000-8000-000000000021";
const roiClass = "00000000-0000-4000-8000-000000000022";
const definition = {
  id: "00000000-0000-4000-8000-000000000031",
  project_id: project.id,
  name: "Coral ROI cover",
  definition_kind: "mask_coverage",
  expression: "union_area(verified_masks) / explicit_denominator",
  grouping_level: "image",
  label_class_ids: [targetClass],
  roi_label_class_id: roiClass,
  operation: "verified_mask_union_coverage",
  output_unit: "percent",
  formula_version: "reefvision.mask-coverage.v1",
  schema_version: "1.1.0",
  required_review_state: "reviewed",
  independence_contract: "one_unit_per_image",
  roi_contract: "verified_mask_class_union",
  definition_sha256: "d".repeat(64),
  created_at: "2026-11-05T01:00:00Z",
};
const summary = {
  mask_count: 2,
  density_object_count: 2,
  summed_mask_area_pixels: 32,
  union_area_pixels: 24,
  overlap_area_pixels: 8,
  image_denominator_pixels: 100,
  image_coverage_percent: 24,
  roi_denominator_pixels: 25,
  target_union_in_roi_pixels: 16,
  roi_coverage_percent: 64,
  area_by_class: [
    {
      label_class_id: targetClass,
      label_name: "Coral",
      mask_count: 2,
      summed_mask_area_pixels: 32,
      union_area_pixels: 24,
      physical_unit: "cm",
      union_area_physical: 6,
    },
  ],
  physical_unit: "cm",
  union_area_physical: 6,
  sampling_area_physical: 6.25,
  object_density_per_square_unit: 0.32,
  calibration_method: "scalar_distance_per_pixel",
  physical_unavailable_reason: null,
};
const preview = {
  ...summary,
  schema_version: "1.1.0",
  definition_id: definition.id,
  definition_sha256: definition.definition_sha256,
  grouping_level: "image",
  required_review_state: "reviewed",
  roi_contract: "verified_mask_class_union",
  image_count: 1,
  independent_unit_count: 1,
  algorithm: "reefvision.source-pixel-mask-union.v1",
  coordinate_frame: "source_image_pixels",
  images: [
    {
      ...summary,
      image_id: imageId,
      unit_key: imageId,
      width_px: 10,
      height_px: 10,
    },
  ],
  groups: [
    {
      ...summary,
      unit_key: imageId,
      image_ids: [imageId],
    },
  ],
  image_snapshot: [{ image_id: imageId }],
  mask_snapshot: [],
  evidence_sha256: "e".repeat(64),
};
const result = {
  ...preview,
  id: "00000000-0000-4000-8000-000000000041",
  project_id: project.id,
  result_kind: "mask_coverage",
  definition_name: definition.name,
  expression: definition.expression,
  formula_version: definition.formula_version,
  output_unit: "percent",
  observed_at: "2026-11-05T01:05:00Z",
  provenance: { verified_masks_only: true },
  content_sha256: "c".repeat(64),
  workflow_run_id: null,
  workflow_node_run_id: null,
  created_at: "2026-11-05T01:05:00Z",
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MaskCoveragePanel project={project} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("MaskCoveragePanel", () => {
  it("saves per-image polygon geometry in the coverage definition", async () => {
    const polygon = {
      image_id: imageId,
      points: [
        [0, 0],
        [5, 0],
        [0, 5],
      ],
    };
    const submitted = vi.fn();
    vi.stubGlobal("fetch", async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        submitted(JSON.parse(String(init.body)));
        return json({
          ...definition,
          roi_label_class_id: null,
          roi_contract: "source_image_polygons",
          roi_polygons: [polygon],
        });
      }
      return json({ items: [], total: 0 });
    });
    renderPanel();
    fireEvent.change(screen.getByLabelText("Coverage name"), {
      target: { value: "Transect polygon" },
    });
    fireEvent.change(screen.getByLabelText("Saved ROI polygons (JSON)"), {
      target: { value: JSON.stringify([polygon]) },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save coverage definition" }),
    );
    await waitFor(() =>
      expect(submitted).toHaveBeenCalledWith({
        name: "Transect polygon",
        grouping_level: "image",
        label_class_ids: [],
        roi_label_class_id: null,
        roi_polygons: [polygon],
      }),
    );
  });
  it("creates, previews, persists, validates, and exports mask coverage", async () => {
    let savedDefinition = false;
    let savedResult = false;
    const submitted: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const path = String(url);
      if (init?.method === "POST") {
        submitted.push(JSON.parse(String(init.body)));
        if (path.endsWith("/computed-mask-coverage-definitions")) {
          savedDefinition = true;
          return json(definition, 201);
        }
        if (path.endsWith("/preview")) return json(preview);
        savedResult = true;
        return json(result, 201);
      }
      if (path.includes("/validation")) {
        return json({
          result_id: result.id,
          current: true,
          saved_evidence_sha256: preview.evidence_sha256,
          current_evidence_sha256: preview.evidence_sha256,
          reasons: [],
        });
      }
      if (path.includes("computed-mask-coverage-definitions")) {
        return json({
          items: savedDefinition ? [definition] : [],
          total: savedDefinition ? 1 : 0,
        });
      }
      return json({
        items: savedResult ? [result] : [],
        total: savedResult ? 1 : 0,
      });
    });

    renderPanel();
    expect(
      await screen.findByText("No mask coverage results yet"),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Coverage name"), {
      target: { value: definition.name },
    });
    fireEvent.change(screen.getByLabelText("Target class IDs"), {
      target: { value: targetClass },
    });
    fireEvent.change(screen.getByLabelText("ROI class ID"), {
      target: { value: roiClass },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save coverage definition" }),
    );
    expect(
      await screen.findByRole("option", { name: definition.name }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Coverage image IDs"), {
      target: { value: imageId },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview mask coverage" }),
    );
    const previewSummary = await screen.findByLabelText(
      "Mask coverage summary",
    );
    expect(previewSummary).toHaveTextContent("Summed mask pixels32");
    expect(previewSummary).toHaveTextContent("Union pixels24");
    expect(previewSummary).toHaveTextContent("Overlap pixels8");
    expect(previewSummary).toHaveTextContent("Image coverage24%");
    expect(previewSummary).toHaveTextContent("ROI coverage64%");
    expect(previewSummary).toHaveTextContent("Physical union area6 cm²");
    expect(previewSummary).toHaveTextContent("Per-image summaries");
    expect(previewSummary).toHaveTextContent("Independent-unit summaries");
    expect(previewSummary).toHaveTextContent(
      `Unit ${imageId}: 1 image(s), 24 union px²`,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Save immutable coverage" }),
    );
    expect(await screen.findByText("Evidence current")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Export mask coverage CSV" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining(
        `/projects/${project.id}/computed-mask-coverage-results.csv`,
      ),
    );
    await waitFor(() => expect(submitted).toHaveLength(3));
    expect(submitted).toEqual([
      {
        name: definition.name,
        grouping_level: "image",
        label_class_ids: [targetClass],
        roi_label_class_id: roiClass,
      },
      { image_ids: [imageId] },
      { image_ids: [imageId] },
    ]);
  });
});
