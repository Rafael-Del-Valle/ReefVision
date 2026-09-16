import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { getAnnotationSession, type Project } from "../../api/client";
import { RasterMaskWorkspace } from "./RasterMaskWorkspace";

vi.mock("../../api/client", () => ({
  getAnnotationSession: vi.fn(),
  imageDisplayUrl: () => "/image.png",
}));

vi.mock("./rasterMaskApi", () => ({
  editRasterMask: vi.fn(),
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
