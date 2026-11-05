import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { ScientificHeatmapsPanel } from "./ScientificHeatmapsPanel";

const project = {
  id: "00000000-0000-4000-8000-000000000001",
  name: "Coral survey",
  slug: "coral-survey",
  description: null,
  storage_root: "projects/coral-survey",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: "2026-10-28T00:00:00Z",
  archived_at: null,
  label_classes: [],
} satisfies Project;

const imageId = "00000000-0000-4000-8000-000000000010";

const imagePage = {
  items: [
    {
      id: imageId,
      project_id: project.id,
      original_filename: "coral-01.png",
      thumbnail_path: null,
      width_px: 80,
      height_px: 60,
      group_key: null,
      annotation_status: "reviewed",
      annotation_revision: 2,
      annotation_count: 1,
      created_at: "2026-10-28T00:00:00Z",
      updated_at: "2026-10-28T00:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  page_size: 24,
  pages: 1,
};

const heatmap = {
  schema_version: "1.1.0",
  algorithm: "reefvision-centroid-grid-1",
  project_id: project.id,
  image_id: imageId,
  image_sha256: "a".repeat(64),
  annotation_revision: 2,
  annotation_status: "reviewed",
  width_px: 80,
  height_px: 60,
  columns: 2,
  rows: 2,
  label_class_id: null,
  layers: [
    {
      kind: "reviewed_boxes",
      counting_method: "bounding_rectangle_centroid",
      object_count: 1,
      max_cell_count: 1,
      counts: [
        [1, 0],
        [0, 0],
      ],
      normalized: [
        [1, 0],
        [0, 0],
      ],
    },
    {
      kind: "verified_masks",
      counting_method: "bounding_rectangle_centroid",
      object_count: 1,
      max_cell_count: 1,
      counts: [
        [0, 0],
        [1, 0],
      ],
      normalized: [
        [0, 0],
        [1, 0],
      ],
    },
    {
      kind: "pending_predictions",
      counting_method: "bounding_rectangle_centroid",
      object_count: 0,
      max_cell_count: 0,
      counts: [
        [0, 0],
        [0, 0],
      ],
      normalized: [
        [0, 0],
        [0, 0],
      ],
    },
  ],
  source_sha256: "b".repeat(64),
  content_sha256: "c".repeat(64),
  methodological_notes: ["Pending predictions are not verified."],
};
const comparison = {
  algorithm: "reefvision.class-aware-box-comparison.v1",
  source_a_sha256: "d".repeat(64),
  source_b_sha256: "e".repeat(64),
  content_sha256: "f".repeat(64),
  per_class: {
    fish: {
      count_a: 2,
      count_b: 3,
      signed_count_difference_b_minus_a: 1,
      absolute_count_difference: 1,
      reference_relative_percent_difference: 50,
      reference_relative_percent_reason: null,
      matched_count: 2,
      mean_matched_iou: 0.8,
      unmatched_a_ids: [],
      unmatched_b_ids: ["prediction-3"],
      false_positive_ids: ["prediction-3"],
      false_negative_ids: [],
    },
  },
  methodological_notes: [],
};

function json(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ScientificHeatmapsPanel project={project} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ScientificHeatmapsPanel", () => {
  it("shows separate reviewed and verified layers", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      json(String(url).includes("scientific-heatmaps") ? heatmap : imagePage),
    );

    renderPanel();

    expect(
      await screen.findByRole("img", {
        name: "Source-pixel heatmap overlay",
      }),
    ).toBeVisible();

    expect(
      screen.getByTestId("heatmap-layer-reviewed_boxes"),
    ).toBeInTheDocument();

    expect(
      screen.getByTestId("heatmap-layer-verified_masks"),
    ).toBeInTheDocument();

    expect(
      screen.queryByTestId("heatmap-layer-pending_predictions"),
    ).not.toBeInTheDocument();

    expect(
      within(screen.getByLabelText("reviewed_boxes summary")).getByText(
        "Objects: 1",
      ),
    ).toBeVisible();
  });

  it("toggles evidence layers independently", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      json(String(url).includes("scientific-heatmaps") ? heatmap : imagePage),
    );

    renderPanel();

    await screen.findByRole("img", {
      name: "Source-pixel heatmap overlay",
    });

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Pending model predictions",
      }),
    );

    expect(
      screen.getByTestId("heatmap-layer-pending_predictions"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Reviewed boxes",
      }),
    );

    expect(
      screen.queryByTestId("heatmap-layer-reviewed_boxes"),
    ).not.toBeInTheDocument();
  });

  it("exposes provenance hashes and methodological notes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      json(String(url).includes("scientific-heatmaps") ? heatmap : imagePage),
    );

    renderPanel();

    await screen.findByRole("img", {
      name: "Source-pixel heatmap overlay",
    });

    expect(screen.getByText(heatmap.content_sha256)).toBeInTheDocument();

    expect(
      screen.getByText("Pending predictions are not verified."),
    ).toBeInTheDocument();
  });

  it("compares a pinned prediction job without claiming reviewer identity", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) => {
        const path = String(url);
        if (path.includes("annotation-comparisons"))
          return json({ result_id: "comparison-result", comparison });
        return json(path.includes("scientific-heatmaps") ? heatmap : imagePage);
      });
    renderPanel();
    await screen.findByRole("img", { name: "Source-pixel heatmap overlay" });
    fireEvent.change(screen.getByLabelText("Prediction job ID"), {
      target: { value: "11111111-1111-4111-8111-111111111111" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Compare evidence" }));
    const result = await screen.findByRole("region", {
      name: "Annotation comparison result",
    });
    expect(result).toHaveTextContent("fish: A 2, B 3, matched 2");
    expect(result).toHaveTextContent("no reviewer-performance");
    const request = fetch.mock.calls.find(([url]) =>
      String(url).includes("annotation-comparisons"),
    );
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      geometry_kind: "boxes",
      reference_side: "a",
      source_a: { kind: "reviewed_boxes" },
      source_b: { kind: "prediction_job" },
    });
  });

  it("compares explicit verified masks and draws disagreement geometry", async () => {
    const maskComparison = {
      ...comparison,
      algorithm: "reefvision.class-aware-mask-comparison.v1",
      geometry_kind: "masks",
      per_class: {
        fish: {
          ...comparison.per_class.fish,
          union_iou: 0.75,
          symmetric_difference_area_pixels: 4,
          disagreement_runs: [[1, 2, 5]],
        },
      },
    };
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) => {
        const path = String(url);
        if (path.includes("annotation-comparisons"))
          return json({
            result_id: "mask-comparison-result",
            comparison: maskComparison,
          });
        return json(path.includes("scientific-heatmaps") ? heatmap : imagePage);
      });
    renderPanel();
    await screen.findByRole("img", { name: "Source-pixel heatmap overlay" });
    fireEvent.change(screen.getByLabelText("Comparison geometry"), {
      target: { value: "masks" },
    });
    fireEvent.change(screen.getByLabelText("Source A verified mask IDs"), {
      target: { value: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" },
    });
    fireEvent.change(screen.getByLabelText("Source B type"), {
      target: { value: "verified_masks" },
    });
    fireEvent.change(screen.getByLabelText("Source B verified mask IDs"), {
      target: { value: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Compare evidence" }));

    expect(
      await screen.findByRole("img", { name: "Mask disagreement geometry" }),
    ).toBeVisible();
    expect(screen.getByText(/union IoU 0.750/)).toBeVisible();
    const request = fetch.mock.calls.find(([url]) =>
      String(url).includes("annotation-comparisons"),
    );
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      geometry_kind: "masks",
      source_a: {
        kind: "verified_masks",
        mask_annotation_ids: ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
      },
      source_b: {
        kind: "verified_masks",
        mask_annotation_ids: ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"],
      },
    });
  });
});
