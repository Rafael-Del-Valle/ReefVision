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
  getAnnotationSession,
  getClassVisibilityBundle,
  type ClassVisibilityBundle,
  type ClassVisibilityScopeState,
  type Project,
} from "../../api/client";
import { RasterMaskWorkspace } from "./RasterMaskWorkspace";

vi.mock("../../api/client", () => ({
  getAnnotationSession: vi.fn(),
  getClassVisibilityBundle: vi.fn(),
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

const emptyVisibilityState: ClassVisibilityScopeState = {
  saved: false,
  hidden_class_ids: [],
  updated_at: null,
  updated_by_identity: null,
};

function visibilityBundle(
  projectId: string,
  options: {
    userSaved?: boolean;
    userHidden?: string[];
    projectSaved?: boolean;
    projectHidden?: string[];
  } = {},
): ClassVisibilityBundle {
  const scopes = {
    annotations: emptyVisibilityState,
    predictions: emptyVisibilityState,
    qc_overlays: emptyVisibilityState,
    video_tracks: emptyVisibilityState,
    segmentation_overlays: emptyVisibilityState,
  };
  return {
    project_id: projectId,
    user_identity: "local-user:fixture",
    supported_layer_types: [
      "annotations",
      "predictions",
      "qc_overlays",
      "video_tracks",
      "segmentation_overlays",
    ],
    precedence: [],
    user_preferences: {
      ...scopes,
      segmentation_overlays: {
        ...emptyVisibilityState,
        saved: options.userSaved ?? false,
        hidden_class_ids: options.userHidden ?? [],
      },
    },
    project_defaults: {
      ...scopes,
      segmentation_overlays: {
        ...emptyVisibilityState,
        saved: options.projectSaved ?? false,
        hidden_class_ids: options.projectHidden ?? [],
      },
    },
  };
}

const savedRasterMask = {
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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAnnotationSession).mockResolvedValue(session as never);
  vi.mocked(getClassVisibilityBundle).mockImplementation(async (projectId) =>
    visibilityBundle(projectId),
  );
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

it("keeps the class, brush size and source revision selected when a stroke began", async () => {
  const twoClassSession = {
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
  };
  vi.mocked(getAnnotationSession).mockResolvedValue(twoClassSession as never);
  const rasterApi = (await import("./rasterMaskApi")) as unknown as {
    editRasterMask: ReturnType<typeof vi.fn>;
  };
  rasterApi.editRasterMask.mockImplementation(() => new Promise(() => {}));
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
  const canvas = (await screen.findByTestId(
    "raster-brush-layer",
  )) as unknown as SVGSVGElement;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 400,
    bottom: 300,
    width: 400,
    height: 300,
    toJSON: () => ({}),
  });
  Object.defineProperty(canvas, "setPointerCapture", { value: vi.fn() });
  Object.defineProperty(canvas, "releasePointerCapture", { value: vi.fn() });
  Object.defineProperty(canvas, "hasPointerCapture", {
    value: vi.fn(() => true),
  });

  await screen.findByRole("button", { name: "Sponge" });
  fireEvent.pointerDown(canvas, {
    button: 0,
    pointerId: 91,
    clientX: 100,
    clientY: 75,
  });
  fireEvent.click(screen.getByRole("button", { name: "Sponge" }));
  fireEvent.change(screen.getByRole("slider", { name: /Brush radius/i }), {
    target: { value: "40" },
  });
  fireEvent.pointerMove(canvas, {
    pointerId: 91,
    clientX: 200,
    clientY: 150,
  });
  fireEvent.pointerUp(canvas, { pointerId: 91 });
  await waitFor(() =>
    expect(rasterApi.editRasterMask).toHaveBeenCalledWith("image-1", {
      base_revision: 0,
      mask_annotation_id: null,
      label_class_id: "class-1",
      mode: "paint",
      brush_radius: 12,
      fill_tolerance: 24,
      strokes: [
        {
          points: [
            { x: 100, y: 75 },
            { x: 200, y: 150 },
          ],
        },
      ],
    }),
  );
});

it("keeps the target object selected at pointer-down when the mask list changes mid-stroke", async () => {
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
    provenance_json: null,
    status: "verified",
    created_by: "local_user",
    created_at: "2026-09-16T00:00:00Z",
    updated_at: "2026-09-16T00:00:00Z",
    deleted_at: null,
    revision: 1,
  };
  vi.mocked(getAnnotationSession).mockResolvedValue({
    ...session,
    mask_annotations: [mask, { ...mask, id: "mask-2" }],
  } as never);
  const rasterApi = (await import("./rasterMaskApi")) as unknown as {
    editRasterMask: ReturnType<typeof vi.fn>;
  };
  rasterApi.editRasterMask.mockImplementation(() => new Promise(() => {}));
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
  await screen.findByText("2 masks");
  const canvas = screen.getByTestId(
    "raster-brush-layer",
  ) as unknown as SVGSVGElement;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 400,
    bottom: 300,
    width: 400,
    height: 300,
    toJSON: () => ({}),
  });
  Object.defineProperty(canvas, "setPointerCapture", { value: vi.fn() });
  Object.defineProperty(canvas, "releasePointerCapture", { value: vi.fn() });
  Object.defineProperty(canvas, "hasPointerCapture", {
    value: vi.fn(() => true),
  });

  fireEvent.pointerDown(canvas, {
    button: 0,
    pointerId: 92,
    clientX: 100,
    clientY: 75,
  });
  fireEvent.click(screen.getAllByRole("button", { name: /Coral \| r1/i })[1]);
  fireEvent.pointerUp(canvas, { pointerId: 92 });
  await waitFor(() =>
    expect(rasterApi.editRasterMask).toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({
        base_revision: 0,
        mask_annotation_id: "mask-1",
        label_class_id: "class-1",
        mode: "paint",
        brush_radius: 12,
        strokes: [{ points: [{ x: 100, y: 75 }] }],
      }),
    ),
  );
});

it("isolates the selected biological class and a late brush save across project navigation", async () => {
  const newSession = {
    ...session,
    image: {
      ...session.image,
      id: "image-2",
      project_id: "project-2",
      original_filename: "sponge.png",
      annotation_revision: 7,
    },
    label_classes: [
      {
        id: "class-2",
        name: "Sponge",
        display_color: "#e76f51",
        is_active: true,
      },
    ],
  };
  vi.mocked(getAnnotationSession).mockImplementation(
    async (id) => (id === "image-2" ? newSession : session) as never,
  );
  const rasterApi = (await import("./rasterMaskApi")) as unknown as {
    editRasterMask: ReturnType<typeof vi.fn>;
  };
  let resolveEdit!: (response: unknown) => void;
  rasterApi.editRasterMask.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveEdit = resolve;
      }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const workspace = (imageId: string, projectId: string) => (
    <QueryClientProvider client={queryClient}>
      <RasterMaskWorkspace
        project={{ id: projectId, name: "Reef" } as Project}
        imageId={imageId}
        onReturnToMasks={vi.fn()}
        onReturnToBoxes={vi.fn()}
        onClose={vi.fn()}
      />
    </QueryClientProvider>
  );
  const { rerender } = render(workspace("image-1", "project-1"));
  const canvas = (await screen.findByTestId(
    "raster-brush-layer",
  )) as unknown as SVGSVGElement;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 400,
    bottom: 300,
    width: 400,
    height: 300,
    toJSON: () => ({}),
  });
  Object.defineProperty(canvas, "setPointerCapture", { value: vi.fn() });
  Object.defineProperty(canvas, "releasePointerCapture", { value: vi.fn() });
  Object.defineProperty(canvas, "hasPointerCapture", {
    value: vi.fn(() => true),
  });
  fireEvent.pointerDown(canvas, {
    button: 0,
    pointerId: 101,
    clientX: 100,
    clientY: 75,
  });
  fireEvent.pointerUp(canvas, { pointerId: 101 });
  await waitFor(() =>
    expect(rasterApi.editRasterMask).toHaveBeenCalledTimes(1),
  );
  expect(rasterApi.editRasterMask).toHaveBeenCalledWith(
    "image-1",
    expect.objectContaining({ base_revision: 0, label_class_id: "class-1" }),
  );

  rerender(workspace("image-2", "project-2"));
  await screen.findByText("sponge.png");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Sponge" }).closest("li"),
    ).toHaveClass("selected"),
  );
  await act(async () => {
    resolveEdit({
      image: { ...session.image, annotation_revision: 1 },
      mask_annotation: {
        id: "mask-from-image-1",
        label_class_id: "class-1",
        deleted_at: null,
      },
    });
  });
  await waitFor(() =>
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["annotation-session", "image-1"],
    }),
  );
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: ["project-images", "project-1"],
  });
  expect(
    screen.getByRole("button", { name: "Sponge" }).closest("li"),
  ).toHaveClass("selected");
  expect(
    screen.queryByRole("button", { name: "Coral" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("0 masks")).toBeInTheDocument();

  // The next brush gesture must use the new study's class and source revision.
  const newCanvas = screen.getByTestId(
    "raster-brush-layer",
  ) as unknown as SVGSVGElement;
  vi.spyOn(newCanvas, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 400,
    bottom: 300,
    width: 400,
    height: 300,
    toJSON: () => ({}),
  });
  Object.defineProperty(newCanvas, "setPointerCapture", { value: vi.fn() });
  Object.defineProperty(newCanvas, "releasePointerCapture", { value: vi.fn() });
  Object.defineProperty(newCanvas, "hasPointerCapture", {
    value: vi.fn(() => true),
  });
  fireEvent.pointerDown(newCanvas, {
    button: 0,
    pointerId: 102,
    clientX: 140,
    clientY: 95,
  });
  fireEvent.pointerUp(newCanvas, { pointerId: 102 });
  await waitFor(() =>
    expect(rasterApi.editRasterMask).toHaveBeenCalledWith(
      "image-2",
      expect.objectContaining({
        base_revision: 7,
        mask_annotation_id: null,
        label_class_id: "class-2",
      }),
    ),
  );
});

it.each(["reclassify", "duplicate"] as const)(
  "ignores a late %s acknowledgement from the previous image",
  async (operation) => {
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
    const initial = {
      ...session,
      mask_annotations: [mask],
      label_classes: [
        session.label_classes[0],
        {
          id: "class-2",
          name: "Sponge",
          display_color: "#e76f51",
          is_active: true,
        },
      ],
    };
    const next = {
      ...session,
      image: {
        ...session.image,
        id: "image-2",
        project_id: "project-2",
        original_filename: "new-project.png",
      },
      mask_annotations: [],
      label_classes: [
        {
          id: "class-3",
          name: "Seagrass",
          display_color: "#386641",
          is_active: true,
        },
      ],
    };
    vi.mocked(getAnnotationSession).mockImplementation(
      async (id) => (id === "image-2" ? next : initial) as never,
    );
    const rasterApi = (await import("./rasterMaskApi")) as unknown as {
      reclassifyRasterMask: ReturnType<typeof vi.fn>;
      duplicateRasterMask: ReturnType<typeof vi.fn>;
    };
    let resolveOperation!: (response: unknown) => void;
    const mockOperation =
      operation === "reclassify"
        ? rasterApi.reclassifyRasterMask
        : rasterApi.duplicateRasterMask;
    mockOperation.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveOperation = resolve;
        }),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const workspace = (imageId: string, projectId: string) => (
      <QueryClientProvider client={queryClient}>
        <RasterMaskWorkspace
          project={{ id: projectId, name: "Reef" } as Project}
          imageId={imageId}
          onReturnToMasks={vi.fn()}
          onReturnToBoxes={vi.fn()}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(workspace("image-1", "project-1"));
    await waitFor(() =>
      expect(screen.getByTestId("raster-skeleton-panel")).toHaveTextContent(
        "mask-1:raster_mask",
      ),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: operation === "reclassify" ? "Sponge" : "Duplicate",
      }),
    );
    await waitFor(() => expect(mockOperation).toHaveBeenCalledTimes(1));
    rerender(workspace("image-2", "project-2"));
    await screen.findByText("new-project.png");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Seagrass" }).closest("li"),
      ).toHaveClass("selected"),
    );
    await act(async () => {
      resolveOperation({
        image: { ...session.image, annotation_revision: 1 },
        mask_annotation: { ...mask, label_class_id: "class-2", revision: 2 },
      });
    });
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["annotation-session", "image-1"],
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["project-images", "project-1"],
    });
    expect(
      screen.getByRole("button", { name: "Seagrass" }).closest("li"),
    ).toHaveClass("selected");
    expect(screen.getByText("0 masks")).toBeInTheDocument();
    expect(screen.getByTestId("raster-skeleton-panel")).toHaveTextContent(
      "no-mask",
    );
  },
);

it.each(["duplicate", "reclassify", "paint"] as const)(
  "serializes %s against other raster mutations and shortcuts",
  async (operation) => {
    const mask = {
      id: "mask-1",
      image_id: "image-1",
      label_class_id: "class-1",
      geometry_kind: "raster_mask",
      mask_path: "projects/project-1/masks/image-1/mask-1.png",
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
    vi.mocked(getAnnotationSession).mockResolvedValue({
      ...session,
      mask_annotations: [mask],
      label_classes: [
        session.label_classes[0],
        {
          id: "class-2",
          name: "Sponge",
          display_color: "#e76f51",
          is_active: true,
        },
      ],
    } as never);
    const rasterApi = (await import("./rasterMaskApi")) as unknown as {
      editRasterMask: ReturnType<typeof vi.fn>;
      duplicateRasterMask: ReturnType<typeof vi.fn>;
      reclassifyRasterMask: ReturnType<typeof vi.fn>;
    };
    const activeMock =
      operation === "paint"
        ? rasterApi.editRasterMask
        : operation === "reclassify"
          ? rasterApi.reclassifyRasterMask
          : rasterApi.duplicateRasterMask;
    let rejectRequest!: (error: Error) => void;
    activeMock.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectRequest = reject;
        }),
    );
    if (operation !== "duplicate") {
      rasterApi.duplicateRasterMask.mockImplementation(
        () => new Promise(() => {}),
      );
    }
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
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

    if (operation === "duplicate") {
      fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
    } else if (operation === "reclassify") {
      fireEvent.click(screen.getByRole("button", { name: "Sponge" }));
    } else {
      const canvas = screen.getByTestId(
        "raster-brush-layer",
      ) as unknown as SVGSVGElement;
      vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 400,
        bottom: 300,
        width: 400,
        height: 300,
        toJSON: () => ({}),
      });
      Object.defineProperty(canvas, "setPointerCapture", { value: vi.fn() });
      Object.defineProperty(canvas, "releasePointerCapture", {
        value: vi.fn(),
      });
      Object.defineProperty(canvas, "hasPointerCapture", {
        value: vi.fn(() => true),
      });
      fireEvent.pointerDown(canvas, {
        button: 0,
        pointerId: 113,
        clientX: 100,
        clientY: 75,
      });
      fireEvent.pointerUp(canvas, { pointerId: 113 });
    }

    await waitFor(() => expect(activeMock).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Close editor" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Duplicate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sponge" })).toBeDisabled();
    expect(
      screen.getByRole("slider", { name: /Brush radius/i }),
    ).toBeDisabled();

    fireEvent.keyDown(document.body, { key: "d", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "v", ctrlKey: true });
    expect(rasterApi.duplicateRasterMask).toHaveBeenCalledTimes(
      operation === "duplicate" ? 1 : 0,
    );
    expect(activeMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      rejectRequest(new Error("Synthetic offline mutation failure"));
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Close editor" }),
      ).toBeEnabled(),
    );
    fireEvent.keyDown(document.body, { key: "d", ctrlKey: true });
    await waitFor(() =>
      expect(rasterApi.duplicateRasterMask).toHaveBeenCalledTimes(
        operation === "duplicate" ? 2 : 1,
      ),
    );
  },
);

it.each([
  {
    name: "saved personal preference",
    options: { userSaved: true, userHidden: ["class-1"] },
    source: "My Preference",
    hidden: true,
  },
  {
    name: "saved project default",
    options: { projectSaved: true, projectHidden: ["class-1"] },
    source: "Project Default",
    hidden: true,
  },
  {
    name: "explicitly visible personal preference overriding project default",
    options: {
      userSaved: true,
      userHidden: [],
      projectSaved: true,
      projectHidden: ["class-1"],
    },
    source: "My Preference",
    hidden: false,
  },
])(
  "respects $name for selected raster overlays without changing scientific records",
  async ({ options, source, hidden }) => {
    vi.mocked(getAnnotationSession).mockResolvedValue({
      ...session,
      mask_annotations: [savedRasterMask],
    } as never);
    vi.mocked(getClassVisibilityBundle).mockResolvedValue(
      visibilityBundle("project-1", options),
    );
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
    await screen.findByRole("button", { name: /Coral \\| r1/i });
    await waitFor(() =>
      expect(screen.getByTestId("raster-visibility-source")).toHaveTextContent(
        source,
      ),
    );
    expect(screen.getByText("1 masks")).toBeInTheDocument();
    expect(screen.getByTestId("raster-skeleton-panel")).toHaveTextContent(
      "mask-1:raster_mask",
    );
    const brush = screen.getByTestId("raster-brush-layer");
    if (hidden) {
      expect(
        screen.queryByTestId("selected-raster-mask-overlay"),
      ).not.toBeInTheDocument();
      expect(screen.getByTestId("raster-hidden-class-notice")).toHaveTextContent(
        "original pixels and revision remain unchanged",
      );
      expect(brush).toHaveStyle({ cursor: "not-allowed" });
      fireEvent.pointerDown(brush, { button: 0, pointerId: 12 });
      fireEvent.pointerUp(brush, { pointerId: 12 });
      const rasterApi = (await import("./rasterMaskApi")) as unknown as {
        editRasterMask: ReturnType<typeof vi.fn>;
      };
      expect(rasterApi.editRasterMask).not.toHaveBeenCalled();
    } else {
      expect(
        screen.getByTestId("selected-raster-mask-overlay"),
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId("raster-hidden-class-notice"),
      ).not.toBeInTheDocument();
      expect(brush).toHaveStyle({ cursor: "crosshair" });
    }
    expect(savedRasterMask.revision).toBe(1);
    expect(savedRasterMask.area_pixels).toBe(900);
  },
);

it("updates the brush overlay from saved visibility cache without rewriting its mask", async () => {
  vi.mocked(getAnnotationSession).mockResolvedValue({
    ...session,
    mask_annotations: [savedRasterMask],
  } as never);
  vi.mocked(getClassVisibilityBundle).mockResolvedValue(
    visibilityBundle("project-1", {
      userSaved: true,
      userHidden: ["class-1"],
    }),
  );
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
  await screen.findByTestId("raster-hidden-class-notice");
  expect(
    screen.queryByTestId("selected-raster-mask-overlay"),
  ).not.toBeInTheDocument();

  await act(async () => {
    queryClient.setQueryData(
      ["class-visibility", "project-1"],
      visibilityBundle("project-1", { userSaved: true, userHidden: [] }),
    );
  });
  await screen.findByTestId("selected-raster-mask-overlay");
  expect(screen.getByText("1 masks")).toBeInTheDocument();
  expect(screen.getByTestId("raster-skeleton-panel")).toHaveTextContent(
    "mask-1:raster_mask",
  );
  expect(savedRasterMask.area_pixels).toBe(900);
});

it("does not apply another project's stale visibility bundle to a raster mask", async () => {
  vi.mocked(getAnnotationSession).mockResolvedValue({
    ...session,
    mask_annotations: [savedRasterMask],
  } as never);
  vi.mocked(getClassVisibilityBundle).mockResolvedValue(
    visibilityBundle("another-project", {
      userSaved: true,
      userHidden: ["class-1"],
    }),
  );
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
  await waitFor(() =>
    expect(screen.getByTestId("raster-visibility-source")).toHaveTextContent(
      "Visible by default",
    ),
  );
  expect(screen.getByTestId("selected-raster-mask-overlay")).toBeInTheDocument();
  expect(screen.queryByTestId("raster-hidden-class-notice")).not.toBeInTheDocument();
});
