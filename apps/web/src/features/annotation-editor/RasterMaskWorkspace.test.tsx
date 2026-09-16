import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { getAnnotationSession, type Project } from "../../api/client";
import { RasterMaskWorkspace } from "./RasterMaskWorkspace";

vi.mock("../../api/client", () => ({
  getAnnotationSession: vi.fn(),
  imageDisplayUrl: () => "/image.png",
}));

vi.mock("./rasterMaskApi", () => ({
  editRasterMask: vi.fn(),
  reclassifyRasterMask: vi.fn(),
  rasterMaskContentUrl: () => "/mask.png",
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
});
