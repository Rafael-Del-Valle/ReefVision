import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { getAnnotationSession, type Project } from "../../api/client";
import { RasterMaskWorkspace } from "./RasterMaskWorkspace";

vi.mock("../../api/client", () => ({
  getAnnotationSession: vi.fn(),
  imageDisplayUrl: () => "/image.png",
}));

vi.mock("./rasterMaskApi", () => ({
  editRasterMask: vi.fn(),
  duplicateRasterMask: vi.fn(),
  reclassifyRasterMask: vi.fn(),
  rasterMaskContentUrl: () => "/mask.png",
}));

vi.mock("./SkeletonAnalysisPanel", () => ({
  SkeletonAnalysisPanel: ({
    selectedMask,
  }: {
    selectedMask: { id: string; geometry_kind: string } | null;
  }) => (
    <div data-testid="raster-skeleton-panel">
      {selectedMask
        ? `${selectedMask.id}:${selectedMask.geometry_kind}`
        : "no-mask"}
    </div>
  ),
}));
vi.mock("./SkeletonOverlayLayer", () => ({
  SkeletonOverlayLayer: () => null,
}));

const session = {
  image: {
    id: "image-1",
    project_id: "project-1",
    original_filename: "reef.png",
    width_px: 400,
    height_px: 300,
    annotation_revision: 0,
  },
  label_classes: [
    {
      id: "class-1",
      name: "Coral",
      display_color: "#2a9d8f",
      is_active: true,
    },
  ],
  annotations: [],
  mask_annotations: [],
  counts_by_class: [],
  previous_image_id: null,
  next_image_id: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAnnotationSession).mockResolvedValue(session as never);
});

it("uses endpoint-safe styling for the Brush radius slider", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <RasterMaskWorkspace
        project={{ id: "project-1", name: "Reef" } as Project}
        imageId="image-1"
        onReturnToMasks={vi.fn()}
        onReturnToBoxes={vi.fn()}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );

  const slider = await screen.findByRole("slider", { name: /Brush radius/i });
  expect(slider).toHaveAttribute("min", "1");
  expect(slider).toHaveAttribute("max", "128");
  expect(slider).toHaveClass("annotation-range-control");
});

it("reassigns a selected painted mask class immediately and displays the class color", async () => {
  const mask = {
    id: "mask-1",
    image_id: "image-1",
    label_class_id: "class-1",
    geometry_kind: "raster_mask",
    mask_path: "projects/project-1/masks/mask-1.png",
    polygon_json: null,
    x_min: 10,
    y_min: 10,
    x_max: 80,
    y_max: 70,
    area_pixels: 900,
    source_type: "human_brush",
    provenance_json: null,
    status: "verified",
    created_by: "local_user",
    created_at: "2026-09-16T00:00:00Z",
    updated_at: "2026-09-16T00:00:00Z",
    deleted_at: null,
    revision: 1,
  };
  const maskSession = {
    ...session,
    label_classes: [
      session.label_classes[0],
      {
        id: "class-2",
        name: "Sponge",
        display_color: "#e76f51",
        is_active: true,
      },
    ],
    mask_annotations: [mask],
  };
  const updatedSession = {
    ...maskSession,
    image: { ...maskSession.image, annotation_revision: 1 },
    mask_annotations: [
      {
        ...mask,
        label_class_id: "class-2",
        revision: 2,
      },
    ],
  };

  vi.mocked(getAnnotationSession)
    .mockResolvedValueOnce(maskSession as never)
    .mockResolvedValue(updatedSession as never);
  const rasterApi = (await import("./rasterMaskApi")) as unknown as {
    reclassifyRasterMask: ReturnType<typeof vi.fn>;
  };
  rasterApi.reclassifyRasterMask.mockResolvedValue({
    image: updatedSession.image,
    mask_annotation: updatedSession.mask_annotations[0],
  });

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RasterMaskWorkspace
        project={{ id: "project-1", name: "Reef" } as Project}
        imageId="image-1"
        onReturnToMasks={vi.fn()}
        onReturnToBoxes={vi.fn()}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );

  await screen.findByRole("button", { name: /Coral \| r1/i });
  const initialOverlay = screen.getByTestId("selected-raster-mask-overlay");
  expect(initialOverlay).toHaveStyle({ backgroundColor: "#2a9d8f" });

  await screen.findByText("Sponge");
  screen.getByText("Sponge").closest("button")?.click();

  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /Sponge \| r2/i }),
    ).toBeInTheDocument(),
  );
  expect(screen.getByTestId("selected-raster-mask-overlay")).toHaveStyle({
    backgroundColor: "#e76f51",
  });
  expect(screen.getByTestId("raster-skeleton-panel")).toHaveTextContent(
    "mask-1:raster_mask",
  );
});

it("copies and duplicates a selected raster mask as an unverified server record", async () => {
  const mask = {
    id: "mask-1",
    image_id: "image-1",
    label_class_id: "class-1",
    geometry_kind: "raster_mask",
    mask_path: "projects/project-1/masks/image-1/mask-1-r1.png",
    polygon_json: null,
    x_min: 10,
    y_min: 10,
    x_max: 80,
    y_max: 70,
    area_pixels: 900,
    source_type: "human_brush",
    provenance_json: { edit_mode: "paint" },
    status: "verified",
    created_by: "local_user",
    created_at: "2026-09-16T00:00:00Z",
    updated_at: "2026-09-16T00:00:00Z",
    deleted_at: null,
    revision: 1,
  };
  const duplicate = {
    ...mask,
    id: "mask-2",
    mask_path: "projects/project-1/masks/image-1/mask-2-r1.png",
    source_type: "human_copy",
    provenance_json: null,
    status: "draft",
  };
  const initial = { ...session, mask_annotations: [mask] };
  const updated = {
    ...session,
    image: { ...session.image, annotation_revision: 1 },
    mask_annotations: [mask, duplicate],
  };
  vi.mocked(getAnnotationSession)
    .mockResolvedValueOnce(initial as never)
    .mockResolvedValue(updated as never);
  const rasterApi = (await import("./rasterMaskApi")) as unknown as {
    duplicateRasterMask: ReturnType<typeof vi.fn>;
  };
  rasterApi.duplicateRasterMask.mockResolvedValue({
    image: updated.image,
    mask_annotation: duplicate,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RasterMaskWorkspace
        project={{ id: "project-1", name: "Reef" } as Project}
        imageId="image-1"
        onReturnToMasks={vi.fn()}
        onReturnToBoxes={vi.fn()}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );

  await screen.findByRole("button", { name: /Coral \| r1/i });
  fireEvent.click(screen.getByRole("button", { name: "Copy" }));
  expect(screen.getByRole("status")).toHaveTextContent("internal clipboard");
  fireEvent.keyDown(document.body, { key: "v", ctrlKey: true });

  await waitFor(() =>
    expect(rasterApi.duplicateRasterMask).toHaveBeenCalledWith(
      "image-1",
      "mask-1",
      { base_revision: 0 },
    ),
  );
  expect(await screen.findByText("2 masks")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("unverified mask");
});
