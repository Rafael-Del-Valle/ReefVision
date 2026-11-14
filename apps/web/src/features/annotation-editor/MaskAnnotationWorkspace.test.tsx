import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeAll, beforeEach, expect, it, vi } from "vitest";

import {
  getAnnotationSession,
  saveAnnotations,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import { MaskAnnotationWorkspace } from "./MaskAnnotationWorkspace";
import { EnhancedAnnotationEditor } from "./EnhancedAnnotationEditor";
import {
  generatePolygonFill,
  generateSmartClosePolygon,
} from "./rasterMaskApi";

beforeAll(() => {
  Object.defineProperty(SVGElement.prototype, "setPointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(SVGElement.prototype, "releasePointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(SVGElement.prototype, "hasPointerCapture", {
    configurable: true,
    value: vi.fn(() => true),
  });
});

vi.mock("../../api/client", () => ({
  getAnnotationSession: vi.fn(),
  saveAnnotations: vi.fn(),
  imageDisplayUrl: () => "/image.png",
}));
vi.mock("./rasterMaskApi", () => ({
  generatePolygonFill: vi.fn(),
  generateSmartClosePolygon: vi.fn(),
  rasterMaskContentUrl: () => "",
}));
vi.mock("./MaskMeasurementPanel", () => ({ MaskMeasurementPanel: () => null }));
vi.mock("./SkeletonAnalysisPanel", () => ({
  SkeletonAnalysisPanel: () => null,
}));
vi.mock("./SkeletonOverlayLayer", () => ({
  SkeletonOverlayLayer: () => null,
}));
vi.mock("./CenterlineMeasurementLayer", () => ({
  CenterlineMeasurementLayer: () => null,
}));
vi.mock("./AnnotationEditor", () => ({
  AnnotationEditor: () => <div data-testid="box-workspace" />,
}));
vi.mock("./RasterMaskWorkspace", () => ({
  RasterMaskWorkspace: () => <div data-testid="raster-workspace" />,
}));

const points = [
  { x: 10, y: 10 },
  { x: 30, y: 10 },
  { x: 30, y: 25 },
  { x: 10, y: 25 },
];
function session(imageId = "image-1", withClass = true): AnnotationSession {
  return {
    image: {
      id: imageId,
      width_px: 400,
      height_px: 300,
      original_filename: `${imageId}.png`,
      annotation_status: "unannotated",
      annotation_revision: 0,
    },
    label_classes: withClass
      ? [
          {
            id: "class-1",
            name: "Coral",
            display_color: "#2a9d8f",
            is_active: true,
          },
        ]
      : [],
    annotations: [],
    mask_annotations: [],
    counts_by_class: [],
    previous_image_id: null,
    next_image_id: null,
  } as unknown as AnnotationSession;
}
function workspace(imageId = "image-1") {
  return (
    <MaskAnnotationWorkspace
      project={{ id: "project-1", name: "Reef" } as Project}
      imageId={imageId}
      onReturnToBoxes={vi.fn()}
      onClose={vi.fn()}
      onOpenBrush={openBrush}
    />
  );
}
const openBrush = vi.fn();
async function mount() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      {workspace()}
    </QueryClientProvider>,
  );
  await screen.findByTestId("activate-polygon-fill-tool");
  return { ...view, queryClient };
}
function seed() {
  const layer = screen.getByTestId("polygon-mask-layer");
  vi.spyOn(layer, "getBoundingClientRect").mockReturnValue({
    left: 20,
    top: 30,
    width: 200,
    height: 150,
  } as DOMRect);
  fireEvent.pointerDown(layer, { clientX: 30, clientY: 40, button: 0 });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAnnotationSession).mockImplementation(async (id) => session(id));
  vi.mocked(generatePolygonFill).mockResolvedValue({ points });
  vi.mocked(generateSmartClosePolygon).mockResolvedValue({ points });
});

async function mountEnhancedWithFill() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EnhancedAnnotationEditor
        project={{ id: "project-1", name: "Reef" } as Project}
        initialImageId="image-1"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByTestId("open-fill-object-tool"));
  const maskWorkspace = await screen.findByTestId("mask-workspace");
  await waitFor(() =>
    expect(maskWorkspace).toHaveAttribute("data-active-tool", "fill"),
  );
  seed();
  await screen.findByText("1 masks");
}

function navigateEnhanced(destination: "raster" | "boxes") {
  fireEvent.click(
    screen.getByTestId(
      destination === "raster" ? "open-brush-tool" : "return-main-tools",
    ),
  );
}

it.each(["raster", "boxes"] as const)(
  "saves an unsaved Fill before left-rail navigation to %s",
  async (destination) => {
    let finishSave!: (
      response: Awaited<ReturnType<typeof saveAnnotations>>,
    ) => void;
    vi.mocked(saveAnnotations).mockReturnValue(
      new Promise((resolve) => {
        finishSave = resolve;
      }),
    );
    await mountEnhancedWithFill();
    navigateEnhanced(destination);
    expect(screen.getByTestId("mask-workspace")).toBeInTheDocument();
    expect(screen.getByTestId("enhanced-annotation-editor")).toHaveAttribute(
      "data-active-annotation-type",
      "masks",
    );
    await waitFor(() => expect(saveAnnotations).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveAnnotations).mock.calls[0][1]).toMatchObject({
      mask_annotations: [{ geometry_kind: "polygon", points }],
    });
    await act(async () =>
      finishSave({
        ...session(),
        image: { ...session().image, annotation_revision: 1 },
      }),
    );
    await screen.findByTestId(
      destination === "raster" ? "raster-workspace" : "box-workspace",
    );
    expect(screen.queryByTestId("mask-workspace")).not.toBeInTheDocument();
  },
);

it.each(["raster", "boxes"] as const)(
  "keeps unsaved Fill when left-rail navigation to %s cannot save",
  async (destination) => {
    vi.mocked(saveAnnotations).mockRejectedValue(new Error("Save unavailable"));
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await mountEnhancedWithFill();
    navigateEnhanced(destination);
    await screen.findByText("Save unavailable");
    expect(screen.getByTestId("enhanced-annotation-editor")).toHaveAttribute(
      "data-active-annotation-type",
      "masks",
    );
    expect(screen.getByText("1 masks")).toBeInTheDocument();
  },
);

it("fills in source coordinates as a normal polygon with selection, undo, redo, save and deletion", async () => {
  await mount();
  fireEvent.click(screen.getByTestId("activate-polygon-fill-tool"));
  seed();
  await waitFor(() => expect(screen.getByText("1 masks")).toBeInTheDocument());
  expect(vi.mocked(generatePolygonFill).mock.calls[0].slice(0, 2)).toEqual([
    "image-1",
    { seed: { x: 20, y: 20 }, tolerance: 24 },
  ]);
  expect(screen.getByText("1 selected")).toBeInTheDocument();
  expect(
    screen
      .getByTestId("polygon-mask-layer")
      .querySelector("polygon")
      ?.getAttribute("points"),
  ).toBe("10,10 30,10 30,25 10,25");
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(screen.getByText("0 masks")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Redo" }));
  expect(screen.getByText("1 masks")).toBeInTheDocument();
  vi.mocked(saveAnnotations).mockRejectedValue(new Error("Save unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await screen.findByText("Save unavailable");
  expect(vi.mocked(saveAnnotations).mock.calls[0][1]).toMatchObject({
    mask_annotations: [
      { geometry_kind: "polygon", label_class_id: "class-1", points },
    ],
  });
  fireEvent.click(screen.getByTestId("activate-mask-select-tool"));
  fireEvent.pointerDown(
    screen.getByTestId("polygon-mask-layer").querySelector("polygon")!,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Delete selected masks" }),
  );
  expect(screen.getByText("0 masks")).toBeInTheDocument();
});

it("duplicates polygons as unverified drafts and keeps the edit reversible", async () => {
  await mount();
  fireEvent.click(screen.getByTestId("activate-polygon-fill-tool"));
  seed();
  await screen.findByText("1 masks");

  fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
  expect(screen.getByText("2 masks")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(screen.getByText("1 masks")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Redo" }));
  expect(screen.getByText("2 masks")).toBeInTheDocument();

  vi.mocked(saveAnnotations).mockRejectedValue(new Error("Save unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await screen.findByText("Save unavailable");
  expect(vi.mocked(saveAnnotations).mock.calls[0][1]).toMatchObject({
    mask_annotations: expect.arrayContaining([
      expect.objectContaining({ status: "draft" }),
    ]),
  });
});

it("does not expose a separate rotated-box annotation tool", async () => {
  await mount();
  expect(
    screen.queryByTestId("activate-rotated-box-tool"),
  ).not.toBeInTheDocument();
});

it("deletes a selected mask with Backspace even when the canvas is not focused", async () => {
  await mount();
  fireEvent.click(screen.getByTestId("activate-polygon-fill-tool"));
  seed();
  await screen.findByText("1 masks");

  fireEvent.click(screen.getByTestId("activate-mask-select-tool"));
  fireEvent.pointerDown(
    screen.getByTestId("polygon-mask-layer").querySelector("polygon")!,
  );
  expect(screen.getByText("1 selected")).toBeInTheDocument();

  fireEvent.keyDown(document.body, { key: "Backspace" });

  await waitFor(() => expect(screen.getByText("0 masks")).toBeInTheDocument());
});

it("uses endpoint-safe styling for the Auto-close tolerance slider", async () => {
  await mount();
  fireEvent.click(screen.getByTestId("activate-smart-close-tool"));

  const slider = screen.getByLabelText("Auto-close tolerance");
  expect(slider).toHaveAttribute("min", "0");
  expect(slider).toHaveAttribute("max", "100");
  expect(slider).toHaveClass("annotation-range-control");
});

it("uses a separate Smart Close tool with full-opening strength at zero", async () => {
  await mount();
  fireEvent.click(screen.getByTestId("activate-smart-close-tool"));
  expect(screen.getByLabelText("Auto-close tolerance")).toHaveValue("0");
  expect(screen.getByText("Full opening")).toBeInTheDocument();

  seed();
  await waitFor(() => expect(screen.getByText("1 masks")).toBeInTheDocument());
  expect(
    vi.mocked(generateSmartClosePolygon).mock.calls[0].slice(0, 2),
  ).toEqual(["image-1", { seed: { x: 20, y: 20 }, closure_strength: 0 }]);
  expect(generatePolygonFill).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText("Auto-close tolerance"), {
    target: { value: "60" },
  });
  expect(screen.getByText("60%")).toBeInTheDocument();
});

it("shows fill failures and leaves the annotation history unchanged", async () => {
  vi.mocked(generatePolygonFill).mockRejectedValue(
    new Error("Fill contains holes"),
  );
  await mount();
  // The toolbar renders before the asynchronous annotation session restores
  // its active class. A click on its initially disabled Fill button is a no-op.
  // Wait for the real editing precondition instead of racing session loading.
  const fillButton = screen.getByTestId("activate-polygon-fill-tool");
  await waitFor(() => expect(fillButton).toBeEnabled());
  fireEvent.click(fillButton);
  await waitFor(() =>
    expect(screen.getByTestId("mask-workspace")).toHaveAttribute(
      "data-active-tool",
      "fill",
    ),
  );
  seed();
  await waitFor(() => expect(generatePolygonFill).toHaveBeenCalledTimes(1));
  await screen.findByText("Fill contains holes");
  expect(screen.getByText("0 masks")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
});

it("ignores an in-flight fill after switching images", async () => {
  let resolve!: (value: { points: typeof points }) => void;
  vi.mocked(generatePolygonFill).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const { rerender, queryClient } = await mount();
  fireEvent.click(screen.getByTestId("activate-polygon-fill-tool"));
  seed();
  rerender(
    <QueryClientProvider client={queryClient}>
      {workspace("image-2")}
    </QueryClientProvider>,
  );
  await screen.findByText("image-2.png");
  await act(async () => resolve({ points }));
  expect(screen.getByText("0 masks")).toBeInTheDocument();
});

it("requires an active class before filling", async () => {
  vi.mocked(getAnnotationSession).mockResolvedValue(session("image-1", false));
  await mount();
  expect(screen.getByTestId("activate-polygon-fill-tool")).toBeDisabled();
});

it("retains unsaved fill when Brush navigation cannot save", async () => {
  vi.mocked(saveAnnotations).mockRejectedValue(new Error("Save unavailable"));
  vi.spyOn(window, "confirm").mockReturnValue(false);
  await mount();
  fireEvent.click(screen.getByTestId("activate-polygon-fill-tool"));
  seed();
  await screen.findByText("1 masks");
  fireEvent.click(screen.getByRole("button", { name: "Brush" }));
  await screen.findByText("Save unavailable");
  expect(openBrush).not.toHaveBeenCalled();
  expect(screen.getByText("1 masks")).toBeInTheDocument();
});

it.each(
  [
    [],
    [
      { x: 1, y: 1 },
      { x: 2, y: 2 },
      { x: 3, y: 3 },
    ],
    [
      { x: -1, y: 1 },
      { x: 2, y: 2 },
      { x: 3, y: 1 },
    ],
  ].map((points) => ({ points })),
)(
  "rejects invalid fill geometry without creating an annotation",
  async (invalid) => {
    vi.mocked(generatePolygonFill).mockResolvedValue(invalid);
    await mount();
    fireEvent.click(screen.getByTestId("activate-polygon-fill-tool"));
    seed();
    await screen.findByText("Fill returned an invalid or empty polygon");
    expect(screen.getByText("0 masks")).toBeInTheDocument();
  },
);

it("refreshes same-image mask state when a newer annotation session replaces cached data", async () => {
  const staleSession = {
    ...session(),
    image: { ...session().image, annotation_revision: 4 },
    mask_annotations: [
      {
        id: "stale-mask",
        image_id: "image-1",
        label_class_id: "class-1",
        geometry_kind: "polygon",
        mask_path: null,
        polygon_json: points.map((point) => [point.x, point.y]),
        x_min: 10,
        y_min: 10,
        x_max: 30,
        y_max: 25,
        area_pixels: 300,
        source_type: "human",
        provenance_json: null,
        status: "verified",
        created_by: "local_user",
        created_at: "2026-09-16T00:00:00Z",
        updated_at: "2026-09-16T00:00:00Z",
        deleted_at: null,
        revision: 1,
      },
    ],
  } as unknown as AnnotationSession;
  const freshSession = {
    ...session(),
    image: { ...session().image, annotation_revision: 5 },
    mask_annotations: [],
  } as unknown as AnnotationSession;

  vi.mocked(getAnnotationSession).mockResolvedValue(freshSession);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClient.setQueryData(["annotation-session", "image-1"], staleSession);

  render(
    <QueryClientProvider client={queryClient}>
      {workspace()}
    </QueryClientProvider>,
  );

  expect(await screen.findByText("1 masks")).toBeInTheDocument();
  await waitFor(() => expect(getAnnotationSession).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByText("0 masks")).toBeInTheDocument());
});
