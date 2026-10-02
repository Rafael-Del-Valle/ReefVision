import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import {
  correctSkeletonAnalysis,
  createSkeletonAnalysis,
  exportSkeletonAnalysis,
  getSkeletonReadiness,
  listSkeletonAnalyses,
  reviewSkeletonAnalysis,
  type SkeletonAnalysisRevision,
} from "./skeletonAnalysisApi";
import { SkeletonAnalysisPanel } from "./SkeletonAnalysisPanel";
import type { SkeletonOverlayModel } from "./SkeletonOverlayLayer";
import type { EditorMaskAnnotation } from "./types";

vi.mock("./skeletonAnalysisApi", () => ({
  correctSkeletonAnalysis: vi.fn(),
  createSkeletonAnalysis: vi.fn(),
  exportSkeletonAnalysis: vi.fn(),
  getSkeletonReadiness: vi.fn(),
  listSkeletonAnalyses: vi.fn(),
  reviewSkeletonAnalysis: vi.fn(),
  skeletonExportDownloadUrl: vi.fn(
    (analysisId: string) => "/skeleton/" + analysisId + "/download",
  ),
}));

const selectedMask: EditorMaskAnnotation = {
  id: "mask-1",
  label_class_id: "class-1",
  geometry_kind: "polygon",
  points: [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 10 },
  ],
  mask_path: null,
  x_min: 0,
  y_min: 0,
  x_max: 10,
  y_max: 10,
  area_pixels: 50,
  source_type: "human",
  persisted: true,
  revision: 1,
};

const analysis = {
  id: "analysis-1",
  analysis_series_id: "series-1",
  analysis_revision: 1,
  supersedes_analysis_id: null,
  mask_annotation_id: "mask-1",
  image_id: "image-1",
  mask_revision: 1,
  current_mask_revision: 1,
  source_kind: "automatic",
  algorithm: "zhang_suen",
  algorithm_version: "0001",
  terminal_spur_max_length_pixels: 0,
  input_mask_sha256: "a".repeat(64),
  calibration_sha256: null,
  parameters_sha256: "b".repeat(64),
  result_sha256: "c".repeat(64),
  correction: {},
  review_status: "unreviewed",
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  created_by: "local_user",
  created_at: "2026-10-02T12:00:00Z",
  is_latest_revision: true,
  stale_mask: false,
  stale_calibration: false,
  stale: false,
  result: {
    schema_version: "skeleton-analysis-0001",
    mask_annotation_id: "mask-1",
    image_id: "image-1",
    mask_revision: 1,
    algorithm: "zhang_suen",
    algorithm_version: "0001",
    connectivity: 8,
    automatic_bridge_applied: false,
    raw_skeleton_pixel_count: 4,
    raw_skeleton_pixels: [
      { x: 1, y: 1 },
      { x: 2, y: 1 },
      { x: 3, y: 1 },
      { x: 4, y: 1 },
    ],
    raw_skeleton_component_count: 1,
    graph_nodes: [],
    graph_edges: [],
    topology_preserved: true,
    endpoint_count: 2,
    junction_pixel_count: 0,
    junction_cluster_count: 0,
    terminal_spur_max_length_pixels: 0,
    spur_pruning_applied: false,
    removed_spur_count: 0,
    pruned_skeleton_pixel_count: 3,
    pruned_skeleton_pixels: [
      { x: 1, y: 1 },
      { x: 2, y: 1 },
      { x: 3, y: 1 },
    ],
    pruned_graph_nodes: [],
    pruned_graph_edges: [],
    raw_branch_count: 1,
    pruned_branch_count: 1,
    raw_total_linear_extension_pixels: 12,
    pruned_total_linear_extension_pixels: 10,
    raw_total_linear_extension_physical: null,
    pruned_total_linear_extension_physical: null,
    raw_longest_path_pixels: 12,
    pruned_longest_path_pixels: 10,
    raw_longest_path_physical: null,
    pruned_longest_path_physical: null,
    raw_branch_angles: [],
    pruned_branch_angles: [],
    calibrated: false,
    physical_unit: null,
    distance_per_pixel: null,
    calibration_source: null,
    calibration_confidence: null,
    perspective_corrected: false,
    length_calibration_method: "pixel_only",
    reference_plane_only: null,
    final_skeleton_source: "automatic_pruned",
    human_correction_applied: false,
    final_skeleton_pixels: [
      { x: 1, y: 1 },
      { x: 2, y: 1 },
      { x: 3, y: 1 },
    ],
    final_graph_nodes: [],
    final_graph_edges: [],
    final_branch_count: 1,
    final_total_linear_extension_pixels: 10,
    final_total_linear_extension_physical: null,
    final_longest_path_pixels: 10,
    final_longest_path_physical: null,
    final_branch_angles: [],
  },
} as SkeletonAnalysisRevision;

function renderPanel(onOverlayChange = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    onOverlayChange,
    ...render(
      <QueryClientProvider client={client}>
        <SkeletonAnalysisPanel
          selectedMask={selectedMask}
          documentDirty={false}
          onOverlayChange={onOverlayChange}
        />
      </QueryClientProvider>,
    ),
  };
}

function latestOverlay(
  calls: unknown[][],
): SkeletonOverlayModel {
  const overlays = calls
    .map((call) => call[0])
    .filter((value): value is SkeletonOverlayModel => value != null);
  const overlay = overlays[overlays.length - 1];
  if (!overlay) throw new Error("Skeleton overlay was not published");
  return overlay;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSkeletonReadiness).mockResolvedValue({
    schema_version: "skeleton-readiness-0001",
    mask_annotation_id: "mask-1",
    image_id: "image-1",
    mask_revision: 1,
    geometry_kind: "polygon",
    mask_status: "verified",
    connectivity: 8,
    total_foreground_pixels: 50,
    component_count: 1,
    single_component: true,
    ready_for_skeletonization: true,
    blocking_reason: null,
    resolution_actions: [],
    automatic_bridge_applied: false,
  });
  vi.mocked(listSkeletonAnalyses).mockResolvedValue([analysis]);
  vi.mocked(createSkeletonAnalysis).mockResolvedValue(analysis);
  vi.mocked(reviewSkeletonAnalysis).mockResolvedValue(analysis);
  vi.mocked(correctSkeletonAnalysis).mockResolvedValue(analysis);
  vi.mocked(exportSkeletonAnalysis).mockResolvedValue({
    analysis_id: analysis.id,
    analysis_revision: 1,
    package_name: "skeleton-analysis",
    archive_name: "skeleton-analysis.zip",
    archive_size_bytes: 1234,
    archive_sha256: "d".repeat(64),
    manifest_sha256: "e".repeat(64),
    verification_status: "verified",
  });
});

it("shows raw, pruned, and final skeleton measurements", async () => {
  renderPanel();

  expect(await screen.findByText("12.00 px")).toBeInTheDocument();
  expect(screen.getAllByText("10.00 px")).toHaveLength(3);
  expect(screen.getByText("automatic pruned")).toBeInTheDocument();
  expect(screen.getByText("unreviewed")).toBeInTheDocument();
});

it("queues canvas edits and submits them only as an explicit correction", async () => {
  const onOverlayChange = vi.fn();
  renderPanel(onOverlayChange);

  await screen.findByText("12.00 px");
  fireEvent.click(screen.getByRole("button", { name: "Add pixels" }));

  await waitFor(() => {
    const overlay = latestOverlay(onOverlayChange.mock.calls);
    expect(overlay.editMode).toBe("add");
  });

  act(() => {
    latestOverlay(onOverlayChange.mock.calls).onPixelClick({ x: 4, y: 1 });
  });
  expect(await screen.findByText(/Pending: \+1 \/ -0 pixels/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Correction reason"), {
    target: { value: "extend_endpoint" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

  await waitFor(() =>
    expect(correctSkeletonAnalysis).toHaveBeenCalledWith("analysis-1", {
      add_pixels: [{ x: 4, y: 1 }],
      remove_pixels: [],
      reason_code: "extend_endpoint",
      note: null,
    }),
  );
});
