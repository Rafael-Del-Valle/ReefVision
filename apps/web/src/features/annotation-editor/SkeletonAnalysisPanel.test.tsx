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
  previewConnectedBranch,
  reviewSkeletonAnalysis,
  type ConnectedBranchPreview,
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
  previewConnectedBranch: vi.fn(),
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

const branchPreview = {
  schema_version: "connected-branch-preview-0001",
  base_analysis_id: analysis.id,
  base_result_sha256: analysis.result_sha256,
  image_id: analysis.image_id,
  mask_annotation_id: analysis.mask_annotation_id,
  attached_node_id: "junction-1",
  added_edge_id: "branch-1",
  superseded_edge_ids: ["edge-1"],
  replacement_edge_ids: ["split-1", "split-2"],
  original_total_length_pixels: 2,
  proposed_total_length_pixels: 4,
  added_length_pixels: 2,
  nodes: [
    {
      id: "junction-1",
      kind: "junction",
      x: 2,
      y: 1,
      source_pixels: [{ x: 2, y: 1 }],
      external_connection_count: 3,
    },
  ],
  edges: [
    {
      id: "branch-1",
      source_node_id: "junction-1",
      target_node_id: "end-1",
      pixels: [
        { x: 2, y: 1 },
        { x: 2, y: 2 },
        { x: 2, y: 3 },
      ],
      boundary_to_boundary_length_pixels: 2,
      node_to_node_length_pixels: 2,
      is_cycle: false,
    },
  ],
  evidence_level: "proposal_unverified",
  review_gate: "scientist_review_required",
  persistent_change_applied: false,
  physical_length_computed: false,
  geometry_space: "source_image_pixels_2d",
} satisfies ConnectedBranchPreview;

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

function latestOverlay(calls: unknown[][]): SkeletonOverlayModel {
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
  expect(screen.getByText(/Final source:/)).toHaveTextContent(
    "automatic pruned",
  );
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
  expect(
    await screen.findByText(/Pending: \+1 \/ -0 pixels/),
  ).toBeInTheDocument();

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

it("switches visual QC baselines and edits only the final skeleton", async () => {
  const onOverlayChange = vi.fn();
  renderPanel(onOverlayChange);

  await screen.findByText("12.00 px");
  fireEvent.click(screen.getByRole("button", { name: "Raw" }));

  await waitFor(() => {
    const overlay = latestOverlay(onOverlayChange.mock.calls);
    expect(overlay.editMode).toBe("view");
    expect(overlay.pixels).toHaveLength(4);
  });

  fireEvent.click(screen.getByRole("button", { name: "Auto-pruned" }));
  await waitFor(() =>
    expect(latestOverlay(onOverlayChange.mock.calls).pixels).toHaveLength(3),
  );

  fireEvent.click(screen.getByRole("button", { name: "Add pixels" }));
  await waitFor(() => {
    const overlay = latestOverlay(onOverlayChange.mock.calls);
    expect(overlay.editMode).toBe("add");
    expect(overlay.pixels).toHaveLength(3);
  });
});

it("requires approval before building and exposing the verified export", async () => {
  vi.mocked(reviewSkeletonAnalysis).mockResolvedValue({
    ...analysis,
    review_status: "approved",
    reviewed_by: "local_user",
    reviewed_at: "2026-10-02T12:05:00Z",
  });
  vi.mocked(listSkeletonAnalyses)
    .mockResolvedValueOnce([analysis])
    .mockResolvedValue([
      {
        ...analysis,
        review_status: "approved",
        reviewed_by: "local_user",
        reviewed_at: "2026-10-02T12:05:00Z",
      },
    ]);

  renderPanel();
  await screen.findByText("12.00 px");

  expect(
    screen.getByRole("button", { name: "Build verified export" }),
  ).toBeDisabled();

  fireEvent.click(screen.getByText("Scientific review"));
  fireEvent.change(screen.getByLabelText("Review note"), {
    target: { value: "Checked against source image." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));

  await waitFor(() =>
    expect(reviewSkeletonAnalysis).toHaveBeenCalledWith(
      "analysis-1",
      "approved",
      "Checked against source image.",
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Build verified export" }),
    ).toBeEnabled(),
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Build verified export" }),
  );
  await waitFor(() =>
    expect(exportSkeletonAnalysis).toHaveBeenCalledWith("analysis-1"),
  );
  expect(
    await screen.findByText("Verified package: skeleton-analysis.zip"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Download skeleton package" }),
  ).toHaveAttribute("href", "/skeleton/analysis-1/download");
});

it("previews a source-pixel branch with waypoint undo and redo", async () => {
  vi.mocked(previewConnectedBranch).mockResolvedValue(branchPreview);
  vi.mocked(listSkeletonAnalyses).mockResolvedValue([
    { ...analysis, review_status: "approved" },
  ]);
  const { onOverlayChange } = renderPanel();

  const draw = await screen.findByRole("button", { name: "Draw branch" });
  fireEvent.click(draw);
  const preview = screen.getByRole("button", { name: "Preview branch" });
  const undo = screen.getByRole("button", { name: "Undo waypoint" });
  const redo = screen.getByRole("button", { name: "Redo waypoint" });
  expect(preview).toBeDisabled();
  expect(redo).toBeDisabled();
  expect(latestOverlay(onOverlayChange.mock.calls).editMode).toBe("branch");

  act(() => {
    const { onPixelClick } = latestOverlay(onOverlayChange.mock.calls);
    onPixelClick({ x: 2, y: 1 });
    onPixelClick({ x: 2, y: 3 });
  });
  expect(latestOverlay(onOverlayChange.mock.calls).branchPixels).toEqual(
    branchPreview.edges[0].pixels,
  );
  expect(preview).toBeEnabled();
  fireEvent.click(undo);
  expect(preview).toBeDisabled();
  fireEvent.click(redo);
  fireEvent.click(preview);

  await waitFor(() =>
    expect(previewConnectedBranch).toHaveBeenCalledWith(
      analysis.id,
      expect.any(String),
      branchPreview.edges[0].pixels,
    ),
  );
  expect(
    await screen.findByText("Scientist review required"),
  ).toBeInTheDocument();
  expect(screen.getByText("4.00 px")).toBeInTheDocument();
  expect(
    screen.getByText(/1 existing segment splits into 2/),
  ).toBeInTheDocument();
  expect(latestOverlay(onOverlayChange.mock.calls).nodes).toEqual(
    branchPreview.nodes,
  );
  fireEvent.click(screen.getByText("Scientific review"));
  expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Build verified export" }),
  ).toBeDisabled();
  expect(correctSkeletonAnalysis).not.toHaveBeenCalled();
  expect(reviewSkeletonAnalysis).not.toHaveBeenCalled();
  expect(exportSkeletonAnalysis).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Discard branch draft" }));
  expect(
    screen.queryByText("Scientist review required"),
  ).not.toBeInTheDocument();
  expect(latestOverlay(onOverlayChange.mock.calls).branchPixels).toEqual([]);
  expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "Build verified export" }),
  ).toBeEnabled();
});

it("displays a rejected path for revision and never treats it as a preview", async () => {
  vi.mocked(previewConnectedBranch).mockRejectedValue(
    new Error(
      "Proposed branch overlaps existing segments beyond its attachment",
    ),
  );
  const { onOverlayChange } = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Draw branch" }));
  act(() => {
    const { onPixelClick } = latestOverlay(onOverlayChange.mock.calls);
    onPixelClick({ x: 1, y: 1 });
    onPixelClick({ x: 3, y: 1 });
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview branch" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Proposed branch overlaps existing segments beyond its attachment",
  );
  expect(
    screen.queryByText("Scientist review required"),
  ).not.toBeInTheDocument();
  expect(latestOverlay(onOverlayChange.mock.calls).branchPixels).toHaveLength(
    3,
  );
  fireEvent.click(screen.getByRole("button", { name: "Undo waypoint" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("ignores the result of a branch request superseded by a draft edit", async () => {
  let completePreview: (preview: ConnectedBranchPreview) => void = () => {};
  vi.mocked(previewConnectedBranch).mockReturnValue(
    new Promise((resolve) => {
      completePreview = resolve;
    }),
  );
  const { onOverlayChange } = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Draw branch" }));
  act(() => {
    const { onPixelClick } = latestOverlay(onOverlayChange.mock.calls);
    onPixelClick({ x: 2, y: 1 });
    onPixelClick({ x: 2, y: 3 });
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview branch" }));
  await waitFor(() => expect(previewConnectedBranch).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "Undo waypoint" }));
  await act(async () => completePreview(branchPreview));

  expect(
    screen.queryByText("Scientist review required"),
  ).not.toBeInTheDocument();
  expect(latestOverlay(onOverlayChange.mock.calls).branchPixels).toEqual([
    { x: 2, y: 1 },
  ]);
});

it("shows calibrated edge and total lengths as reference-plane measurements", async () => {
  vi.mocked(previewConnectedBranch).mockResolvedValue({
    ...branchPreview,
    physical_length_computed: true,
    calibration: {
      calibration_sha256: "0".repeat(64),
      source: "aruco",
      method: "reference_plane_homography",
      unit: "mm",
      original_total_length: 0.5,
      proposed_total_length: 1.25,
      added_length: 0.75,
    },
    edges: [{ ...branchPreview.edges[0], length_physical: 0.75 }],
  });
  const { onOverlayChange } = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Draw branch" }));
  act(() => {
    const { onPixelClick } = latestOverlay(onOverlayChange.mock.calls);
    onPixelClick({ x: 2, y: 1 });
    onPixelClick({ x: 2, y: 3 });
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview branch" }));
  expect(await screen.findByText("4.00 px | 1.2500 mm")).toBeInTheDocument();
  expect(screen.getAllByText("2.00 px | 0.7500 mm")).toHaveLength(2);
  expect(screen.getByText(/Reference-plane calibration/)).toHaveTextContent(
    "aruco",
  );
  expect(screen.getByText("Scientist review required")).toBeInTheDocument();
});

it("does not draw a branch from a superseded or stale skeleton", async () => {
  vi.mocked(listSkeletonAnalyses).mockResolvedValue([
    { ...analysis, is_latest_revision: false },
  ]);
  renderPanel();
  await screen.findByText("12.00 px");
  expect(
    screen.queryByRole("button", { name: "Draw branch" }),
  ).not.toBeInTheDocument();
});

it("rejects a preview returned for another skeleton revision", async () => {
  vi.mocked(previewConnectedBranch).mockResolvedValue({
    ...branchPreview,
    base_result_sha256: "0".repeat(64),
  });
  const { onOverlayChange } = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Draw branch" }));
  act(() => {
    const { onPixelClick } = latestOverlay(onOverlayChange.mock.calls);
    onPixelClick({ x: 2, y: 1 });
    onPixelClick({ x: 2, y: 3 });
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview branch" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The branch preview does not match this skeleton revision.",
  );
  expect(
    screen.queryByText("Scientist review required"),
  ).not.toBeInTheDocument();
});
