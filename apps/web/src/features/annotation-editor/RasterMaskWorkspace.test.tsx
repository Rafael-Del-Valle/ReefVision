import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  getAnnotationSession,
  saveAnnotations,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import { RasterMaskWorkspace } from "./RasterMaskWorkspace";

vi.mock("../../api/client", () => ({
  getAnnotationSession: vi.fn(),
  saveAnnotations: vi.fn(),
  imageDisplayUrl: () => "/image.png",
}));

vi.mock("./rasterMaskApi", () => ({
  editRasterMask: vi.fn(),
  rasterMaskContentUrl: () => "/mask.png",
}));

vi.mock("./RasterBrushLayer", () => ({
  RasterBrushLayer: () => <div data-testid="raster-brush-layer" />,
}));

vi.mock("./RasterFillLayer", () => ({
  RasterFillLayer: () => <div data-testid="raster-fill-layer" />,
}));

const project = { id: "project-1", name: "Reef" } as Project;

function session(withMask = true): AnnotationSession {
  return {
    image: {
      id: "image-1",
      project_id: project.id,
      original_filename: "reef.png",
      width_px: 400,
      height_px: 300,
      annotation_status: "in_progress",
      annotation_revision: withMask ? 3 : 4,
    },
    label_classes: [
      {
        id: "class-1",
        name: "Coral",
        display_color: "#2a9d8f",
        is_active: true,
      },
    ],
    annotations: [
      {
        id: "annotation-1",
        image_id: "image-1",
        label_class_id: "class-1",
        x_min: 10,
        y_min: 10,
        x_max: 30,
        y_max: 30,
      },
    ],
    mask_annotations: withMask
      ? [
          {
            id: "raster-1",
            image_id: "image-1",
            label_class_id: "class-1",
            geometry_kind: "raster_mask",
            mask_path: "projects/project-1/masks/raster-1.png",
            polygon_json: null,
            x_min: 5,
            y_min: 5,
            x_max: 100,
            y_max: 100,
            area_pixels: 500,
            source_type: "human",
            provenance_json: null,
            status: "verified",
            created_by: "local_user",
            created_at: "2026-09-16T00:00:00Z",
            updated_at: "2026-09-16T00:00:00Z",
            deleted_at: null,
            revision: 1,
          },
        ]
      : [],
    counts_by_class: [{ label_class_id: "class-1", count: 1 }],
    mask_counts_by_class: [
      { label_class_id: "class-1", count: withMask ? 1 : 0 },
    ],
    previous_image_id: null,
    next_image_id: null,
  } as unknown as AnnotationSession;
}

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RasterMaskWorkspace
        project={project}
        imageId="image-1"
        onReturnToMasks={vi.fn()}
        onReturnToBoxes={vi.fn()}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("uses a full-track brush-radius control that reaches both endpoints", async () => {
  vi.mocked(getAnnotationSession).mockResolvedValue(session());

  renderWorkspace();
  await screen.findByRole("heading", { name: "1 masks" });

  const radius = screen.getByRole("slider");
  expect(radius).toHaveClass("annotation-range-control");
  expect(radius).toHaveAttribute("min", "1");
  expect(radius).toHaveAttribute("max", "128");

  fireEvent.change(radius, { target: { value: "1" } });
  expect(screen.getByText("Brush radius: 1px")).toBeInTheDocument();

  fireEvent.change(radius, { target: { value: "128" } });
  expect(screen.getByText("Brush radius: 128px")).toBeInTheDocument();
});

it("deletes the selected raster mask with Backspace and preserves box annotations", async () => {
  let deleted = false;
  vi.mocked(getAnnotationSession).mockImplementation(async () =>
    session(!deleted),
  );
  vi.mocked(saveAnnotations).mockImplementation(async () => {
    deleted = true;
    return {
      image: { ...session(false).image, annotation_revision: 4 },
      annotations: session(false).annotations,
      counts_by_class: [{ label_class_id: "class-1", count: 1 }],
    } as unknown as Awaited<ReturnType<typeof saveAnnotations>>;
  });

  renderWorkspace();
  await screen.findByRole("heading", { name: "1 masks" });

  fireEvent.click(
    screen.getByRole("button", { name: /Coral \| r1 \| 500px²/ }),
  );
  fireEvent.keyDown(document.body, { key: "Backspace" });

  await waitFor(() => expect(saveAnnotations).toHaveBeenCalledTimes(1));
  expect(vi.mocked(saveAnnotations).mock.calls[0][1]).toMatchObject({
    annotations: [
      {
        id: "annotation-1",
        label_class_id: "class-1",
        x_min: 10,
        y_min: 10,
        x_max: 30,
        y_max: 30,
      },
    ],
    deleted_mask_annotation_ids: ["raster-1"],
  });
});
