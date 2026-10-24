import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AnnotationSession,
  ClassVisibilityBundle,
  ClassVisibilityLayerType,
  Project,
} from "../../api/client";
import { AnnotationEditor, annotationImageSource } from "./AnnotationEditor";

const project: Project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: "Octocoral polyp annotations",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Muricea Closed",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#E76F51",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
    {
      id: "class-2",
      project_id: "project-1",
      class_index: 1,
      display_order: 1,
      name: "Muricea Open",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#2A9D8F",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
  ],
};

const session: AnnotationSession = {
  image: {
    id: "image-1",
    project_id: project.id,
    original_filename: "swiftia-frame.png",
    managed_path: "projects/project-1/images/originals/image-1.png",
    thumbnail_path: null,
    sha256: "a".repeat(64),
    width_px: 1600,
    height_px: 1200,
    file_size_bytes: 2048,
    media_type: "image/png",
    import_source: "trial/swiftia-frame.png",
    capture_timestamp: null,
    group_key: null,
    metadata_json: {},
    annotation_status: "in_progress",
    annotation_revision: 2,
    annotation_count: 1,
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
  },
  label_classes: project.label_classes,
  annotations: [
    {
      id: "annotation-1",
      image_id: "image-1",
      label_class_id: "class-1",
      x_min: 100,
      y_min: 120,
      x_max: 260,
      y_max: 300,
      source_type: "human",
      source_model_id: null,
      source_prediction_id: null,
      created_by: "local_user",
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
      deleted_at: null,
      revision: 1,
    },
  ],
  counts_by_class: [
    { label_class_id: "class-1", count: 1 },
    { label_class_id: "class-2", count: 0 },
  ],
  previous_image_id: null,
  next_image_id: null,
};

const assistModel = {
  id: "assist-model-1",
  project_id: project.id,
  purpose: "assist" as const,
  display_name: "Fixture SAM",
  source_filename: "sam_vit_b_fixture.pth",
  managed_path: "projects/project-1/models/assist-model-1.pth",
  sha256: "b".repeat(64),
  file_size_bytes: 1024,
  framework: "segment_anything",
  task: "assist_segmentation",
  provider_name: "segment_anything",
  provider_version: "1.0",
  class_map_json: {},
  input_size_json: null,
  metadata_json: { variant: "vit_b" },
  notes: null,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
};

const pendingProposal = {
  id: "proposal-1",
  project_id: project.id,
  image_id: session.image.id,
  model_id: "detector-model-1",
  model_display_name: "Fixture Detector",
  inference_job_id: "job-1",
  model_checksum: "c".repeat(64),
  label_class_id: "class-1",
  predicted_label: "Muricea Closed",
  predicted_index: 0,
  confidence: 0.88,
  x_min: 320,
  y_min: 240,
  x_max: 520,
  y_max: 460,
  review_status: "pending",
  was_edited: false,
  reviewer_action_at: null,
  accepted_annotation_id: null,
  inference_settings_json: {},
  provenance_json: { provider_name: "ultralytics" },
  created_at: "2026-07-08T00:00:00Z",
};

function buildVisibilityBundle(options?: {
  userPreferences?: Partial<Record<ClassVisibilityLayerType, string[]>>;
  projectDefaults?: Partial<Record<ClassVisibilityLayerType, string[]>>;
}): ClassVisibilityBundle {
  const createScopeRecord = (
    hiddenByLayer?: Partial<Record<ClassVisibilityLayerType, string[]>>,
  ) => ({
    annotations: {
      saved: Boolean(hiddenByLayer?.annotations),
      hidden_class_ids: hiddenByLayer?.annotations ?? [],
      updated_at: hiddenByLayer?.annotations ? "2026-07-10T00:00:00Z" : null,
      updated_by_identity: hiddenByLayer?.annotations
        ? "local-user:test"
        : null,
    },
    predictions: {
      saved: Boolean(hiddenByLayer?.predictions),
      hidden_class_ids: hiddenByLayer?.predictions ?? [],
      updated_at: hiddenByLayer?.predictions ? "2026-07-10T00:00:00Z" : null,
      updated_by_identity: hiddenByLayer?.predictions
        ? "local-user:test"
        : null,
    },
    qc_overlays: {
      saved: Boolean(hiddenByLayer?.qc_overlays),
      hidden_class_ids: hiddenByLayer?.qc_overlays ?? [],
      updated_at: hiddenByLayer?.qc_overlays ? "2026-07-10T00:00:00Z" : null,
      updated_by_identity: hiddenByLayer?.qc_overlays
        ? "local-user:test"
        : null,
    },
    video_tracks: {
      saved: Boolean(hiddenByLayer?.video_tracks),
      hidden_class_ids: hiddenByLayer?.video_tracks ?? [],
      updated_at: hiddenByLayer?.video_tracks ? "2026-07-10T00:00:00Z" : null,
      updated_by_identity: hiddenByLayer?.video_tracks
        ? "local-user:test"
        : null,
    },
    segmentation_overlays: {
      saved: Boolean(hiddenByLayer?.segmentation_overlays),
      hidden_class_ids: hiddenByLayer?.segmentation_overlays ?? [],
      updated_at: hiddenByLayer?.segmentation_overlays
        ? "2026-07-10T00:00:00Z"
        : null,
      updated_by_identity: hiddenByLayer?.segmentation_overlays
        ? "local-user:test"
        : null,
    },
  });

  return {
    project_id: project.id,
    user_identity: "local-user:test",
    supported_layer_types: [
      "annotations",
      "predictions",
      "qc_overlays",
      "video_tracks",
      "segmentation_overlays",
    ],
    precedence: [
      "temporary_qc_reveal",
      "session_override",
      "user_preference",
      "project_default",
      "visible_by_default",
    ],
    user_preferences: createScopeRecord(options?.userPreferences),
    project_defaults: createScopeRecord(options?.projectDefaults),
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function handleDefaultEditorRequests(
  url: string,
  init?: RequestInit,
): Response | undefined {
  if (url.includes(`/projects/${project.id}/model-catalog`)) {
    return jsonResponse({
      schema_version: 2,
      catalog_version: "2.0.0",
      models: [],
      warnings: [],
      rejected_entries: [],
    });
  }
  if (url.includes(`/projects/${project.id}/models?purpose=detector`)) {
    return jsonResponse([]);
  }
  if (url.includes(`/projects/${project.id}/models?purpose=assist`)) {
    return jsonResponse([]);
  }
  if (
    url.endsWith(`/projects/${project.id}/class-visibility`) &&
    (!init?.method || init.method === "GET")
  ) {
    return jsonResponse(buildVisibilityBundle());
  }
  if (
    url.includes(`/images/${session.image.id}/prediction-proposals`) &&
    (!init?.method || init.method === "GET")
  ) {
    return jsonResponse({ items: [], counts: { pending: 0 } });
  }
  return undefined;
}

function renderEditor(onClose = vi.fn(), onActiveImageChange = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AnnotationEditor
        project={project}
        initialImageId={session.image.id}
        onClose={onClose}
        onActiveImageChange={onActiveImageChange}
      />
    </QueryClientProvider>,
  );
  return { onClose, onActiveImageChange, queryClient };
}

function selectionPanel(): HTMLElement {
  const section = screen
    .getByRole("heading", { name: "1 selected" })
    .closest("section");
  if (!(section instanceof HTMLElement)) {
    throw new Error("Selection section was not rendered");
  }
  return section;
}

function stubCanvasRect(): void {
  const canvas = screen.getByTestId("annotation-canvas");
  Object.defineProperty(canvas, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      x: 0,
      y: 0,
      width: 1200,
      height: 780,
      top: 0,
      left: 0,
      right: 1200,
      bottom: 780,
      toJSON: () => ({}),
    }),
  });
}

function mockBasicEditorRequests(): void {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (
      url.endsWith(`/images/${session.image.id}/annotations`) &&
      (!init?.method || init.method === "GET")
    ) {
      return jsonResponse(session);
    }
    const fallback = handleDefaultEditorRequests(url, init);
    if (fallback) return fallback;
    throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("AnnotationEditor", () => {
  it("preserves the thumbnail when the full-resolution preload fails", () => {
    expect(
      annotationImageSource("image-1", "managed/thumb.png", false),
    ).toContain("/images/image-1/thumbnail");
    expect(
      annotationImageSource("image-1", "managed/thumb.png", true),
    ).toContain("/images/image-1/display");
    expect(annotationImageSource("image-1", null, false)).toContain(
      "/images/image-1/display",
    );
  });

  it("keeps an annotation preview visible after a failed full-size preload and can retry", async () => {
    const preloaders: FakeImage[] = [];
    class FakeImage {
      decoding = "";
      onload: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      src = "";
      constructor() {
        preloaders.push(this);
      }
    }
    vi.stubGlobal("Image", FakeImage);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith(`/images/${session.image.id}/annotations`)) {
        return jsonResponse({
          ...session,
          image: { ...session.image, thumbnail_path: "thumb.png" },
        });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${url}`);
    });
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    await waitFor(() => expect(preloaders.length).toBeGreaterThan(0));
    const first = preloaders.find((image) =>
      image.src.includes("/display?retry=0"),
    );
    expect(first).toBeDefined();
    act(() => first?.onerror?.(new Event("error")));
    expect(
      await screen.findByText("Full-resolution image could not load"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("annotation-canvas").querySelector("image"),
    ).toHaveAttribute("href", expect.stringContaining("/thumbnail"));

    await userEvent.click(
      screen.getByRole("button", { name: "Retry full-resolution image" }),
    );
    const second = await waitFor(() => {
      const item = preloaders.find((image) =>
        image.src.includes("/display?retry=1"),
      );
      expect(item).toBeDefined();
      return item;
    });
    act(() => second?.onload?.(new Event("load")));
    expect(
      screen.queryByText("Full-resolution image could not load"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("annotation-canvas").querySelector("image"),
    ).toHaveAttribute("href", expect.stringContaining("/display?retry=1"));
  });

  it("keeps thumbnail preview until the full image has decoded", async () => {
    const decodeGate: { release: () => void } = {
      release: () => undefined,
    };
    const decodePromise = new Promise<void>((resolve) => {
      decodeGate.release = resolve;
    });
    const preloaders: FakeImage[] = [];
    class FakeImage {
      decoding = "";
      onload: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      src = "";
      decode = vi.fn(() => decodePromise);
      constructor() {
        preloaders.push(this);
      }
    }
    vi.stubGlobal("Image", FakeImage);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith(`/images/${session.image.id}/annotations`)) {
        return jsonResponse({
          ...session,
          image: { ...session.image, thumbnail_path: "thumb.png" },
        });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    const preloader = await waitFor(() => {
      const item = preloaders.find((candidate) =>
        candidate.src.includes("/display?retry=0"),
      );
      expect(item).toBeDefined();
      return item;
    });
    const source = () =>
      screen.getByTestId("annotation-canvas").querySelector("image");

    act(() => preloader?.onload?.(new Event("load")));
    expect(preloader?.decode).toHaveBeenCalledOnce();
    expect(source()).toHaveAttribute(
      "href",
      expect.stringContaining("/thumbnail"),
    );
    expect(
      screen.getByText("Loading full-resolution image..."),
    ).toBeInTheDocument();

    await act(async () => {
      decodeGate.release();
      await decodePromise;
    });
    expect(source()).toHaveAttribute(
      "href",
      expect.stringContaining("/display?retry=0"),
    );
    expect(
      screen.queryByText("Loading full-resolution image..."),
    ).not.toBeInTheDocument();
  });

  it("does not apply a previous image preload to a newly opened image", async () => {
    const preloaders: FakeImage[] = [];
    class FakeImage {
      decoding = "";
      onload: ((event: Event) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      src = "";
      constructor() {
        preloaders.push(this);
      }
    }
    vi.stubGlobal("Image", FakeImage);
    const firstSession: AnnotationSession = {
      ...session,
      image: { ...session.image, thumbnail_path: "first-thumb.png" },
      next_image_id: "image-2",
    };
    const secondSession: AnnotationSession = {
      ...session,
      image: {
        ...session.image,
        id: "image-2",
        original_filename: "swiftia-next.png",
        thumbnail_path: "second-thumb.png",
        annotation_revision: 0,
        annotation_count: 0,
      },
      annotations: [],
      counts_by_class: project.label_classes.map((label) => ({
        label_class_id: label.id,
        count: 0,
      })),
      previous_image_id: session.image.id,
      next_image_id: null,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/images/image-1/annotations")) {
        return jsonResponse(firstSession);
      }
      if (url.endsWith("/images/image-2/annotations")) {
        return jsonResponse(secondSession);
      }
      if (url.endsWith("/images/image-2/prediction-proposals")) {
        return jsonResponse({ items: [], counts: { pending: 0 } });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${url}`);
    });
    renderEditor();
    await screen.findByRole("heading", { name: "swiftia-frame.png" });
    const first = await waitFor(() => {
      const image = preloaders.find((item) =>
        item.src.includes("/images/image-1/display?retry=0"),
      );
      expect(image).toBeDefined();
      return image;
    });
    const priorLoad = first?.onload;
    act(() => first?.onload?.(new Event("load")));
    expect(
      screen.getByTestId("annotation-canvas").querySelector("image"),
    ).toHaveAttribute("href", expect.stringContaining("image-1/display"));

    await userEvent.keyboard("d");
    await screen.findByRole("heading", { name: "swiftia-next.png" });
    const second = await waitFor(() => {
      const image = preloaders.find((item) =>
        item.src.includes("/images/image-2/display?retry=0"),
      );
      expect(image).toBeDefined();
      return image;
    });

    const canvasImage = () =>
      screen.getByTestId("annotation-canvas").querySelector("image");
    expect(canvasImage()).toHaveAttribute(
      "href",
      expect.stringContaining("image-2/thumbnail"),
    );
    expect(
      screen.getByText("Loading full-resolution image..."),
    ).toBeInTheDocument();

    // A delayed event from the previous image must not paint the new canvas.
    act(() => priorLoad?.(new Event("load")));
    expect(canvasImage()).toHaveAttribute(
      "href",
      expect.stringContaining("image-2/thumbnail"),
    );
    act(() => second?.onload?.(new Event("load")));
    expect(canvasImage()).toHaveAttribute(
      "href",
      expect.stringContaining("image-2/display"),
    );
    expect(
      screen.queryByText("Loading full-resolution image..."),
    ).not.toBeInTheDocument();
  });

  it("navigates between images from quick review without discarding saved edits", async () => {
    const firstSession: AnnotationSession = {
      ...session,
      next_image_id: "image-2",
    };
    const secondSession: AnnotationSession = {
      ...session,
      image: {
        ...session.image,
        id: "image-2",
        original_filename: "swiftia-next.png",
        annotation_revision: 0,
        annotation_count: 0,
      },
      annotations: [],
      counts_by_class: project.label_classes.map((label) => ({
        label_class_id: label.id,
        count: 0,
      })),
      previous_image_id: session.image.id,
      next_image_id: null,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/images/image-1/annotations")) {
        return jsonResponse(firstSession);
      }
      if (url.endsWith("/images/image-2/annotations")) {
        return jsonResponse(secondSession);
      }
      if (url.includes("/images/image-2/prediction-proposals")) {
        return jsonResponse({ items: [], counts: { pending: 0 } });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${url}`);
    });
    renderEditor();
    await screen.findByRole("heading", { name: "swiftia-frame.png" });
    await userEvent.click(
      screen.getByRole("button", { name: /Quick review \(≤50%\)/ }),
    );
    let dialog = await screen.findByRole("dialog", {
      name: "Confidence-based review",
    });
    const next = within(dialog).getByRole("button", { name: "Next image" });
    expect(next).toBeEnabled();
    await userEvent.click(next);
    await screen.findByRole("heading", { name: "swiftia-next.png" });
    dialog = screen.getByRole("dialog", {
      name: "Confidence-based review",
    });
    expect(
      within(dialog).getByRole("button", { name: "Previous image" }),
    ).toBeEnabled();
    expect(
      within(dialog).getByRole("button", { name: "Next image" }),
    ).toBeDisabled();
  });

  it("reports the controlled active image identity", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith(`/images/${session.image.id}/annotations`)) {
        return jsonResponse(session);
      }
      const standard = handleDefaultEditorRequests(url, init);
      if (standard) return standard;
      throw new Error(`Unhandled request ${String(input)}`);
    });
    const onActiveImageChange = vi.fn();

    renderEditor(vi.fn(), onActiveImageChange);

    await waitFor(() =>
      expect(onActiveImageChange).toHaveBeenLastCalledWith(session.image.id),
    );
  });

  it("temporarily pans with Alt plus left drag and cancels on pointer loss", async () => {
    mockBasicEditorRequests();
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    stubCanvasRect();
    const canvas = screen.getByTestId("annotation-canvas");
    const viewport = screen.getByTestId("viewport-transform");
    const initialTransform = viewport.getAttribute("transform");

    fireEvent.pointerDown(canvas, {
      button: 0,
      altKey: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(window, { clientX: 145, clientY: 130 });
    expect(viewport.getAttribute("transform")).not.toBe(initialTransform);
    const pannedTransform = viewport.getAttribute("transform");

    fireEvent.pointerCancel(window);
    fireEvent.pointerMove(window, { clientX: 300, clientY: 300 });
    expect(viewport.getAttribute("transform")).toBe(pannedTransform);

    fireEvent.pointerDown(canvas, {
      button: 1,
      clientX: 145,
      clientY: 130,
    });
    fireEvent.pointerMove(window, { clientX: 170, clientY: 155 });
    expect(viewport.getAttribute("transform")).not.toBe(pannedTransform);
    const middlePannedTransform = viewport.getAttribute("transform");
    fireEvent.blur(window);
    fireEvent.pointerMove(window, { clientX: 400, clientY: 400 });
    expect(viewport.getAttribute("transform")).toBe(middlePannedTransform);
  });

  it("culls offscreen boxes while preserving the full object list and restores on reset", async () => {
    mockBasicEditorRequests();
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    stubCanvasRect();
    expect(screen.getByTestId("annotation-annotation-1")).toBeInTheDocument();
    const canvas = screen.getByTestId("annotation-canvas");
    fireEvent.pointerDown(canvas, {
      button: 0,
      altKey: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(window, { clientX: -4000, clientY: -4000 });
    fireEvent.pointerCancel(window);
    expect(screen.queryByTestId("annotation-annotation-1")).toBeNull();
    expect(
      within(screen.getByRole("listbox", { name: "Objects" })).getAllByRole(
        "option",
      ),
    ).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Reset View" }));
    expect(screen.getByTestId("annotation-annotation-1")).toBeInTheDocument();
  });

  it("offers actual-size and reset-view commands without changing annotations", async () => {
    mockBasicEditorRequests();
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    const viewport = screen.getByTestId("viewport-transform");

    await userEvent.click(
      screen.getByRole("button", { name: "Actual Size (100%)" }),
    );
    expect(viewport.getAttribute("transform")).toContain("scale(1)");
    expect(screen.getByTestId("annotation-annotation-1")).toHaveAttribute(
      "x",
      "100",
    );

    await userEvent.click(screen.getByRole("button", { name: "Reset View" }));
    expect(viewport.getAttribute("transform")).not.toContain("scale(1)");
    expect(screen.getByTestId("annotation-annotation-1")).toHaveAttribute(
      "x",
      "100",
    );
  });

  it("copies, pastes, duplicates, and reverses boxes through one document history", async () => {
    mockBasicEditorRequests();
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    stubCanvasRect();

    // Editing an already reviewed image must invalidate its prior review.
    await userEvent.selectOptions(
      screen.getByLabelText("Annotation status"),
      "reviewed",
    );
    fireEvent.pointerDown(screen.getByTestId("annotation-annotation-1"), {
      button: 0,
    });
    fireEvent.keyDown(document.body, { key: "c", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "v", ctrlKey: true });

    const objectList = screen.getByRole("listbox", { name: "Objects" });
    expect(within(objectList).getAllByRole("option")).toHaveLength(2);
    expect(screen.getByText(/Pasted 1 annotation/)).toBeInTheDocument();
    expect(screen.getByLabelText("Annotation status")).toHaveValue(
      "in_progress",
    );
    fireEvent.keyDown(document.body, { key: "d", ctrlKey: true });
    expect(within(objectList).getAllByRole("option")).toHaveLength(3);

    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(within(objectList).getAllByRole("option")).toHaveLength(2);
    fireEvent.keyDown(document.body, { key: "y", ctrlKey: true });
    expect(within(objectList).getAllByRole("option")).toHaveLength(3);
  });

  it("does not run clipboard shortcuts while typing", async () => {
    mockBasicEditorRequests();
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    const filter = screen.getByPlaceholderText("Filter by class");
    fireEvent.keyDown(filter, { key: "d", ctrlKey: true });
    expect(
      within(screen.getByRole("listbox", { name: "Objects" })).getAllByRole(
        "option",
      ),
    ).toHaveLength(1);
  });

  it("shows and deletes polygon masks from Main Select", async () => {
    const sessionWithMask = {
      ...session,
      mask_annotations: [
        {
          id: "mask-1",
          image_id: session.image.id,
          label_class_id: "class-1",
          geometry_kind: "polygon",
          mask_path: null,
          polygon_json: [
            [320, 320],
            [420, 320],
            [420, 420],
            [320, 420],
          ],
          x_min: 320,
          y_min: 320,
          x_max: 420,
          y_max: 420,
          area_pixels: 10000,
          source_type: "human",
          provenance_json: null,
          status: "verified",
          created_by: "local_user",
          created_at: "2026-07-08T00:00:00Z",
          updated_at: "2026-07-08T00:00:00Z",
          deleted_at: null,
          revision: 1,
        },
      ],
      mask_counts_by_class: [{ label_class_id: "class-1", count: 1 }],
    } as AnnotationSession;

    let savedPayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(sessionWithMask);
      }
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        init?.method === "PUT"
      ) {
        savedPayload = JSON.parse(String(init.body)) as Record<string, unknown>;
        return jsonResponse({
          image: {
            ...session.image,
            annotation_revision: 3,
          },
          annotations: session.annotations,
          mask_annotations: [],
          counts_by_class: session.counts_by_class,
          mask_counts_by_class: [],
        });
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) {
        return shared;
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    stubCanvasRect();

    const mask = await screen.findByTestId("mask-annotation-mask-1");
    expect(mask).toBeVisible();
    expect(screen.getByText(/Polygon \/ Fill/)).toBeInTheDocument();

    fireEvent.pointerDown(mask, { button: 0 });
    expect(
      screen.getByRole("heading", { name: "1 selected" }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Delete selection" }),
    );
    expect(
      screen.queryByTestId("mask-annotation-mask-1"),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save now" }));
    await waitFor(() =>
      expect(savedPayload).toMatchObject({
        deleted_mask_annotation_ids: ["mask-1"],
      }),
    );
  });

  it("keeps the selected annotation class unchanged in box mode", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) {
        return shared;
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    stubCanvasRect();

    expect(
      screen.getByRole("listbox", { name: "Objects" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("prediction-inspector-slot")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pan tool" }));
    expect(screen.getByRole("button", { name: "Pan tool" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await userEvent.click(screen.getByRole("button", { name: "Box tool" }));
    fireEvent.pointerDown(screen.getByTestId("annotation-annotation-1"), {
      clientX: 0,
      clientY: 0,
      button: 0,
    });

    await waitFor(() =>
      expect(
        screen.getByText(
          /Draw new boxes with the active class without changing the current selection\./,
        ),
      ).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByTestId("class-tool-2"));

    const panel = within(selectionPanel());
    expect(panel.getByText("Muricea Closed")).toBeInTheDocument();
    expect(panel.queryByText("Muricea Open")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Active class: Muricea Open\./),
    ).toBeInTheDocument();
  });

  it("reassigns the selected annotation class in select mode", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        init?.method === "PUT"
      ) {
        return jsonResponse({
          image: {
            ...session.image,
            annotation_revision: 3,
          },
          annotations: [
            {
              ...session.annotations[0],
              label_class_id: "class-2",
            },
          ],
          counts_by_class: [
            { label_class_id: "class-1", count: 0 },
            { label_class_id: "class-2", count: 1 },
          ],
        });
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) {
        return shared;
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    stubCanvasRect();

    await userEvent.click(screen.getByRole("button", { name: "Box tool" }));
    fireEvent.pointerDown(screen.getByTestId("annotation-annotation-1"), {
      clientX: 0,
      clientY: 0,
      button: 0,
    });
    await userEvent.click(screen.getByRole("button", { name: "Select tool" }));
    await userEvent.click(screen.getByTestId("class-tool-2"));

    const panel = within(selectionPanel());
    expect(panel.getByText("Muricea Open")).toBeInTheDocument();
    expect(panel.queryByText("Muricea Closed")).not.toBeInTheDocument();
  });

  it("updates class visibility locally without refetching annotations", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (
          url.endsWith(`/images/${session.image.id}/annotations`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse(session);
        }
        if (
          url.endsWith(`/projects/${project.id}/class-visibility`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse(buildVisibilityBundle());
        }
        if (
          url.includes(`/images/${session.image.id}/prediction-proposals`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse({
            items: [pendingProposal],
            counts: { pending: 1 },
          });
        }
        const shared = handleDefaultEditorRequests(url, init);
        if (shared) {
          return shared;
        }
        throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
      });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });

    expect(
      await screen.findByTestId(`prediction-row-${pendingProposal.id}`),
    ).toBeInTheDocument();

    const firstClassRow = screen.getByTestId("class-tool-1").closest("li");
    if (!(firstClassRow instanceof HTMLElement)) {
      throw new Error("Expected the first class row to render");
    }
    await userEvent.click(
      within(firstClassRow).getByRole("checkbox", { name: "Visible" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByTestId("annotation-annotation-1"),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByTestId(`prediction-row-${pendingProposal.id}`),
    ).toBeInTheDocument();

    const annotationGets = fetchMock.mock.calls.filter(
      ([request, requestInit]) =>
        String(request).endsWith(`/images/${session.image.id}/annotations`) &&
        (!requestInit?.method || requestInit.method === "GET"),
    );
    const predictionGets = fetchMock.mock.calls.filter(
      ([request, requestInit]) =>
        String(request).includes(
          `/images/${session.image.id}/prediction-proposals`,
        ) &&
        (!requestInit?.method || requestInit.method === "GET"),
    );
    expect(annotationGets).toHaveLength(1);
    expect(predictionGets).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(
      await screen.findByTestId("annotation-annotation-1"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(`prediction-row-${pendingProposal.id}`),
    ).toBeInTheDocument();
  });

  it("opens a synchronized prediction inspector with crop, confidence, provenance, and review navigation", async () => {
    const secondProposal = {
      ...pendingProposal,
      id: "proposal-2",
      predicted_label: "Muricea Open",
      label_class_id: "class-2",
      confidence: 0.42,
      x_min: 600,
      x_max: 760,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (
        url.includes(`/images/${session.image.id}/prediction-proposals`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse({
          items: [pendingProposal, secondProposal],
          counts: { pending: 2 },
        });
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) return shared;
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await userEvent.click(
      await screen.findByTestId(`prediction-row-${secondProposal.id}`),
    );

    const inspector = screen.getByRole("region", {
      name: "Prediction Inspector",
    });
    expect(
      within(inspector).getAllByText("Muricea Open").length,
    ).toBeGreaterThan(0);
    expect(within(inspector).getByText("0.42")).toBeInTheDocument();
    expect(
      within(inspector).getByText(/no calibrated probability/i),
    ).toBeInTheDocument();
    expect(
      within(inspector).getByRole("img", { name: /crop of Muricea Open/i }),
    ).toBeInTheDocument();
    expect(
      within(inspector).getByText("Prediction 1 of 2"),
    ).toBeInTheDocument();

    await userEvent.keyboard("j");
    expect(
      within(inspector).getAllByText("Muricea Closed").length,
    ).toBeGreaterThan(0);
    expect(
      within(inspector).getByText("Prediction 2 of 2"),
    ).toBeInTheDocument();
  });

  it("saves a personal visibility preference and keeps annotation fetches local", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (
          url.endsWith(`/images/${session.image.id}/annotations`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse(session);
        }
        if (
          url.endsWith(`/projects/${project.id}/class-visibility`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse(buildVisibilityBundle());
        }
        if (
          url.endsWith(
            `/projects/${project.id}/class-visibility/preferences/annotations`,
          ) &&
          init?.method === "PUT"
        ) {
          return jsonResponse({
            saved: true,
            hidden_class_ids: ["class-1"],
            updated_at: "2026-07-10T00:00:00Z",
            updated_by_identity: "local-user:test",
          });
        }
        const shared = handleDefaultEditorRequests(url, init);
        if (shared) {
          return shared;
        }
        throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
      });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });

    const firstClassRow = screen.getByTestId("class-tool-1").closest("li");
    if (!(firstClassRow instanceof HTMLElement)) {
      throw new Error("Expected the first class row to render");
    }
    await userEvent.click(
      within(firstClassRow).getByRole("checkbox", { name: "Visible" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByTestId("annotation-annotation-1"),
      ).not.toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Save as My Preference" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("class-visibility-status")).toHaveTextContent(
        "Saved my preference for Annotations.",
      ),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Reset Session" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("class-visibility-status")).toHaveTextContent(
        "Reset the session override for Annotations.",
      ),
    );
    expect(
      screen.queryByTestId("annotation-annotation-1"),
    ).not.toBeInTheDocument();

    const annotationGets = fetchMock.mock.calls.filter(
      ([request, requestInit]) =>
        String(request).endsWith(`/images/${session.image.id}/annotations`) &&
        (!requestInit?.method || requestInit.method === "GET"),
    );
    expect(annotationGets).toHaveLength(1);
  });

  it("keeps prediction visibility separate through project defaults", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (
        url.endsWith(`/projects/${project.id}/class-visibility`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(
          buildVisibilityBundle({
            projectDefaults: { predictions: ["class-1"] },
          }),
        );
      }
      if (
        url.includes(`/images/${session.image.id}/prediction-proposals`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse({
          items: [pendingProposal],
          counts: { pending: 1 },
        });
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) {
        return shared;
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });

    expect(screen.getByTestId("annotation-annotation-1")).toBeInTheDocument();
    expect(
      screen.queryByTestId(`prediction-row-${pendingProposal.id}`),
    ).not.toBeInTheDocument();
  });

  it("shows a friendly API message instead of a raw fetch error when saving fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        init?.method === "PUT"
      ) {
        throw new TypeError("NetworkError when attempting to fetch resource");
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) {
        return shared;
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });

    await userEvent.selectOptions(
      screen.getByLabelText("Annotation status"),
      "reviewed",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save now" }));

    expect(
      await screen.findAllByText(
        /ReefVision could not reach the ReefVision API\./,
      ),
    ).toHaveLength(2);
    expect(
      screen.queryByText("NetworkError when attempting to fetch resource"),
    ).not.toBeInTheDocument();
  });

  it("allows returning to the gallery after a failed save when edits are discarded", async () => {
    const onClose = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        init?.method === "PUT"
      ) {
        throw new TypeError("NetworkError when attempting to fetch resource");
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) {
        return shared;
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor(onClose);
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });

    await userEvent.selectOptions(
      screen.getByLabelText("Annotation status"),
      "reviewed",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Back to gallery" }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(window.confirm).toHaveBeenCalledWith(
      "Saving failed. Discard unsaved local annotation edits and return to the gallery?",
    );
  });

  it("sends a selected prediction proposal through Prompt Assist and accepts the mask", async () => {
    let proposalAccepted = false;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (
          url.endsWith(`/images/${session.image.id}/annotations`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse(session);
        }
        if (url.includes(`/projects/${project.id}/models?purpose=detector`)) {
          return jsonResponse([]);
        }
        if (url.includes(`/projects/${project.id}/models?purpose=assist`)) {
          return jsonResponse([assistModel]);
        }
        if (url.includes(`/projects/${project.id}/model-catalog`)) {
          return jsonResponse({
            schema_version: 2,
            catalog_version: "2.0.0",
            warnings: [],
            rejected_entries: [],
            models: [
              {
                catalog_id: `registered/${assistModel.id}`,
                display_name: assistModel.display_name,
                selection_kind: "registered_model",
                installation_state: "Ready",
                resolved_model_id: assistModel.id,
                provider_id: "segment_anything",
              },
            ],
          });
        }
        if (
          url.includes(`/images/${session.image.id}/prediction-proposals`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse({
            items: proposalAccepted ? [] : [pendingProposal],
            counts: { pending: proposalAccepted ? 0 : 1 },
          });
        }
        if (
          url.endsWith(`/images/${session.image.id}/assist-sessions`) &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            session_id: "assist-session-1",
            project_id: project.id,
            image_id: session.image.id,
            model_id: assistModel.id,
            model_display_name: assistModel.display_name,
            provider_name: "segment_anything",
            provider_version: "1.0",
            created_at: "2026-07-08T00:00:00Z",
            last_used_at: "2026-07-08T00:00:00Z",
            expires_at: "2026-07-08T00:15:00Z",
            add_stroke_count: 0,
            subtract_stroke_count: 0,
            brush_radius: null,
            source_prediction_id: pendingProposal.id,
            prompt_type: null,
            candidate_box: null,
            candidate_mask_png_base64: null,
          });
        }
        if (
          url.endsWith("/assist-sessions/assist-session-1/box") &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            session_id: "assist-session-1",
            project_id: project.id,
            image_id: session.image.id,
            model_id: assistModel.id,
            model_display_name: assistModel.display_name,
            provider_name: "segment_anything",
            provider_version: "1.0",
            created_at: "2026-07-08T00:00:00Z",
            last_used_at: "2026-07-08T00:00:02Z",
            expires_at: "2026-07-08T00:15:00Z",
            add_stroke_count: 0,
            subtract_stroke_count: 0,
            brush_radius: null,
            source_prediction_id: pendingProposal.id,
            prompt_type: "box_to_mask",
            candidate_box: {
              x_min: 324,
              y_min: 244,
              x_max: 516,
              y_max: 456,
            },
            candidate_mask_png_base64: "ZmFrZS1tYXNr",
          });
        }
        if (
          url.endsWith("/assist-sessions/assist-session-1/accept") &&
          init?.method === "POST"
        ) {
          proposalAccepted = true;
          return jsonResponse({
            session_id: "assist-session-1",
            annotation: {
              id: "annotation-2",
              image_id: session.image.id,
              label_class_id: "class-1",
              x_min: 324,
              y_min: 244,
              x_max: 516,
              y_max: 456,
              source_type: "assist_mask",
              source_model_id: assistModel.id,
              source_prediction_id: pendingProposal.id,
              created_by: "local_user",
              created_at: "2026-07-08T00:00:03Z",
              updated_at: "2026-07-08T00:00:03Z",
              deleted_at: null,
              revision: 1,
            },
          });
        }
        if (
          url.endsWith("/assist-sessions/assist-session-1") &&
          init?.method === "DELETE"
        ) {
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
      });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });

    await userEvent.click(screen.getByTestId("prediction-row-proposal-1"));
    await userEvent.click(
      screen.getByRole("button", { name: "Segment selected proposal" }),
    );

    expect(
      await screen.findByText(/Candidate mask ready via segment_anything/i),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/images\/image-1\/assist-sessions$/),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          model_id: assistModel.id,
          device: "auto",
          source_prediction_id: pendingProposal.id,
        }),
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Accept mask" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/assist-sessions\/assist-session-1\/accept$/),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ label_class_id: "class-1" }),
        }),
      ),
    );
  });
  it("deploys a trained project model on the currently open image", async () => {
    const detectorModel = {
      id: "detector-best",
      project_id: project.id,
      purpose: "detector",
      display_name: "Coral best.pt",
      source_filename: "best.pt",
      managed_path: "projects/project-1/models/best.pt",
      sha256: "d".repeat(64),
      file_size_bytes: 2048,
      framework: "ultralytics",
      task: "detect",
      provider_name: "ultralytics",
      provider_version: "8.4.19",
      class_map_json: {},
      input_size_json: null,
      metadata_json: {},
      notes: null,
      created_at: "2026-09-16T00:00:00Z",
      updated_at: "2026-09-16T00:00:00Z",
    };
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (url.includes(`/projects/${project.id}/models?purpose=detector`)) {
        return jsonResponse([detectorModel]);
      }
      if (url.includes(`/projects/${project.id}/model-catalog`)) {
        return jsonResponse({
          schema_version: 2,
          catalog_version: "2.0.0",
          models: [],
          warnings: [],
          rejected_entries: [],
        });
      }
      if (
        url.endsWith(`/projects/${project.id}/class-visibility`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(buildVisibilityBundle());
      }
      if (
        url.includes(`/images/${session.image.id}/prediction-proposals`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse({ items: [], counts: { pending: 0 } });
      }
      if (
        url.endsWith(`/projects/${project.id}/inference-jobs`) &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          id: "job-single",
          project_id: project.id,
          job_type: "inference",
          status: "queued",
          progress_current: 0,
          progress_total: 1,
          result_json: {},
          error_message: null,
        });
      }
      if (url.includes("/jobs/job-single")) {
        return jsonResponse({
          id: "job-single",
          project_id: project.id,
          job_type: "inference",
          status: "succeeded",
          progress_current: 1,
          progress_total: 1,
          result_json: {},
          error_message: null,
        });
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    expect(
      screen.getByRole("heading", { name: "Deploy trained model" }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Run model on this image" }),
    );

    await waitFor(() => {
      const request = requests.find(
        (entry) =>
          entry.url.endsWith(`/projects/${project.id}/inference-jobs`) &&
          entry.init?.method === "POST",
      );
      expect(request).toBeDefined();
      expect(JSON.parse(String(request?.init?.body))).toMatchObject({
        model_id: "detector-best",
        image_ids: [session.image.id],
        confidence_threshold: 0.25,
      });
    });
  });

  it("updates the cached annotation session revision after a successful save", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        init?.method === "PUT"
      ) {
        const body = JSON.parse(String(init.body));
        return jsonResponse({
          image: {
            ...session.image,
            annotation_revision: 3,
          },
          annotations: body.annotations,
          counts_by_class: session.counts_by_class,
        });
      }
      const shared = handleDefaultEditorRequests(url, init);
      if (shared) return shared;
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    const { queryClient } = renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    await userEvent.click(screen.getByRole("button", { name: "Select tool" }));
    fireEvent.pointerDown(screen.getByTestId("annotation-annotation-1"), {
      button: 0,
      clientX: 120,
      clientY: 160,
    });
    await userEvent.click(screen.getByTestId("class-tool-2"));
    await userEvent.click(screen.getByRole("button", { name: "Save now" }));

    await waitFor(() => {
      const cached = queryClient.getQueryData<AnnotationSession>([
        "annotation-session",
        session.image.id,
      ]);
      expect(cached?.image.annotation_revision).toBe(3);
      expect(cached?.annotations[0].label_class_id).toBe("class-2");
    });
  });

  it("offers explicit in-canvas accept and reject for a new SAM raster mask", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    let created = false;
    let accepted = false;
    const samProposal = {
      ...pendingProposal,
      id: "sam-proposal-1",
      geometry_kind: "raster_mask",
      mask_path: "projects/project-1/prediction-masks/sam-proposal-1.png",
      label_class_id: null,
      predicted_label: "SAM 2 mask",
      provenance_json: { provider_id: "sam2" },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(session);
      }
      if (
        url.includes(`/projects/${project.id}/sam2-models`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse([
          {
            variant: "small",
            ready: true,
            installed: true,
            repo_id: "facebook/sam2.1-hiera-small",
            revision: "a".repeat(40),
            weight_sha256: "f".repeat(64),
          },
        ]);
      }
      if (
        url.includes("/advanced-providers/sam2/execute") &&
        init?.method === "POST"
      ) {
        created = true;
        return jsonResponse({
          provider_id: "sam2",
          task: "assist_segmentation",
          status: "succeeded",
          model_id: "sam2-small",
          model_revision: "a".repeat(40),
          result: { proposal_id: samProposal.id, proposal_count: 1 },
          warnings: [],
        });
      }
      if (
        url.endsWith(`/prediction-proposals/${samProposal.id}/accept`) &&
        init?.method === "POST"
      ) {
        accepted = true;
        return jsonResponse({
          proposal: { ...samProposal, review_status: "accepted" },
          mask_annotation: { id: "accepted-mask-1" },
        });
      }
      if (
        url.includes(`/images/${session.image.id}/prediction-proposals`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse({
          items: created && !accepted ? [samProposal] : [],
          counts: { pending: created && !accepted ? 1 : 0 },
        });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    fireEvent.pointerDown(screen.getByTestId("annotation-annotation-1"), {
      button: 0,
      clientX: 145,
      clientY: 185,
    });
    fireEvent.pointerUp(window);
    await userEvent.click(
      screen.getByRole("button", { name: "SAM box prompt" }),
    );

    const review = await screen.findByTestId("sam-proposal-review");
    expect(
      within(review).getByText(/SAM mask is a proposal — not saved yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("proposal-mask-sam-proposal-1"),
    ).toBeInTheDocument();
    expect(
      within(review).getByRole("button", { name: "Accept SAM mask" }),
    ).toBeEnabled();
    expect(
      calls.some((request) => request.url.endsWith("/sam-proposal-1/accept")),
    ).toBe(false);

    await userEvent.click(
      within(review).getByRole("button", { name: "Accept SAM mask" }),
    );
    await waitFor(() => {
      expect(accepted).toBe(true);
      expect(
        screen.queryByTestId("sam-proposal-review"),
      ).not.toBeInTheDocument();
    });
    expect(
      calls.find((request) => request.url.endsWith("/sam-proposal-1/accept"))
        ?.init?.method,
    ).toBe("POST");
  });

  it("runs the separately labeled SAM box action on a selected image box", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      )
        return jsonResponse(session);
      if (
        url.includes(`/projects/${project.id}/sam2-models`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse([
          {
            variant: "small",
            repo_id: "facebook/sam2.1-hiera-small",
            ready: true,
            installed: true,
            revision: "a".repeat(40),
            weight_sha256: "f".repeat(64),
            path: "C:/models/sam2",
            reason: null,
            license_summary: "Apache-2.0",
          },
        ]);
      }
      if (
        url.includes("/advanced-providers/sam2/execute") &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          provider_id: "sam2",
          task: "assist_segmentation",
          status: "succeeded",
          model_id: "facebook/sam2.1-hiera-small",
          model_revision: "a".repeat(40),
          result: { proposal_id: "sam-proposal-1", proposal_count: 1 },
          warnings: [],
        });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    fireEvent.pointerDown(screen.getByTestId("annotation-annotation-1"), {
      button: 0,
      clientX: 145,
      clientY: 185,
    });
    fireEvent.pointerUp(window);
    await userEvent.click(
      screen.getByRole("button", { name: "SAM box prompt" }),
    );
    await waitFor(() => {
      const request = requests.find((entry) =>
        entry.url.includes("/advanced-providers/sam2/execute"),
      );
      expect(request).toBeDefined();
      const body = JSON.parse(String(request?.init?.body));
      expect(body.prompt_fields).toMatchObject({
        image_id: "image-1",
        sam2_variant: "small",
        box: [100, 120, 260, 300],
      });
    });
  });

  it("arms the separately labeled SAM draw-box action even when the pan tool is active", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      )
        return jsonResponse(session);
      if (
        url.includes(`/projects/${project.id}/sam2-models`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse([
          {
            variant: "small",
            ready: true,
            installed: true,
            revision: "a".repeat(40),
            weight_sha256: "f".repeat(64),
          },
        ]);
      }
      if (
        url.includes("/advanced-providers/sam2/execute") &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          provider_id: "sam2",
          task: "assist_segmentation",
          status: "succeeded",
          model_id: "sam2-small",
          model_revision: "a".repeat(40),
          result: { proposal_id: "sam-drawn-1" },
          warnings: [],
        });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    stubCanvasRect();
    await userEvent.click(screen.getByRole("button", { name: "Pan tool" }));
    fireEvent.pointerUp(window);
    await userEvent.click(
      screen.getByRole("button", { name: "SAM box prompt" }),
    );
    expect(
      screen.getByText(/SAM prompt ready: drag a bounding box/),
    ).toBeInTheDocument();
    const canvas = screen.getByTestId("annotation-canvas");
    fireEvent.pointerDown(canvas, { button: 0, clientX: 150, clientY: 150 });
    fireEvent.pointerMove(window, { clientX: 250, clientY: 240 });
    fireEvent.pointerUp(window);
    await waitFor(() => {
      const request = requests.find((item) =>
        item.url.includes("/advanced-providers/sam2/execute"),
      );
      expect(request).toBeDefined();
      const body = JSON.parse(String(request?.init?.body));
      expect(body.prompt_fields.sam2_variant).toBe("small");
      expect(body.prompt_fields.box[2]).toBeGreaterThan(
        body.prompt_fields.box[0],
      );
      expect(body.prompt_fields.box[3]).toBeGreaterThan(
        body.prompt_fields.box[1],
      );
    });
  });

  it("runs the selected detector across the image with Shift+1", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      )
        return jsonResponse(session);
      if (url.includes(`/projects/${project.id}/models?purpose=detector`)) {
        return jsonResponse([
          {
            id: "detector-best",
            project_id: project.id,
            purpose: "detector",
            display_name: "Coral best.pt",
            source_filename: "best.pt",
            managed_path: "models/best.pt",
            sha256: "d".repeat(64),
            file_size_bytes: 2048,
            framework: "ultralytics",
            task: "detect",
            provider_name: "ultralytics",
            provider_version: "8.3",
            class_map_json: {},
            input_size_json: null,
            metadata_json: { active_for_predictions: true },
            notes: null,
            created_at: "2026-10-10T00:00:00Z",
            updated_at: "2026-10-10T00:00:00Z",
          },
        ]);
      }
      if (
        url.endsWith(`/projects/${project.id}/inference-jobs`) &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          id: "job-shortcut",
          project_id: project.id,
          job_type: "inference",
          status: "queued",
          progress_current: 0,
          progress_total: 1,
          result_json: {},
          error_message: null,
        });
      }
      if (url.includes("/jobs/job-shortcut")) {
        return jsonResponse({
          id: "job-shortcut",
          project_id: project.id,
          job_type: "inference",
          status: "succeeded",
          progress_current: 1,
          progress_total: 1,
          result_json: {},
          error_message: null,
        });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Predict objects in image (Shift+1)",
        }),
      ).not.toBeDisabled(),
    );
    fireEvent.keyDown(window, { key: "!", code: "Digit1", shiftKey: true });
    await waitFor(() => {
      const request = requests.find(
        (entry) =>
          entry.url.endsWith(`/projects/${project.id}/inference-jobs`) &&
          entry.init?.method === "POST",
      );
      expect(request).toBeDefined();
      expect(JSON.parse(String(request?.init?.body))).toMatchObject({
        model_id: "detector-best",
        image_ids: [session.image.id],
      });
    });
  });
  it("starts bounded full-image SAM proposals without a registered detector", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith(`/images/${session.image.id}/annotations`))
        return jsonResponse(session);
      if (url.includes(`/projects/${project.id}/models?purpose=detector`)) {
        return jsonResponse([
          {
            id: "unpromoted-detector",
            project_id: project.id,
            purpose: "detector",
            display_name: "Unvalidated detector",
            source_filename: "candidate.pt",
            managed_path: "models/candidate.pt",
            sha256: "d".repeat(64),
            file_size_bytes: 2048,
            framework: "ultralytics",
            task: "detect",
            provider_name: "ultralytics",
            provider_version: "8.3",
            class_map_json: {},
            input_size_json: null,
            metadata_json: {},
            notes: null,
            created_at: "2026-10-10T00:00:00Z",
            updated_at: "2026-10-10T00:00:00Z",
          },
        ]);
      }
      if (url.includes("/sam-image-proposals") && init?.method === "POST") {
        return jsonResponse({
          id: "sam-grid-job",
          status: "queued",
          progress_current: 0,
          progress_total: 16,
          result_json: {},
        });
      }
      if (url.includes("/jobs/sam-grid-job"))
        return jsonResponse({
          id: "sam-grid-job",
          status: "running",
          progress_current: 3,
          progress_total: 16,
          result_json: { stage: "sampling" },
        });
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    fireEvent.keyDown(window, { key: "!", code: "Digit1", shiftKey: true });
    await waitFor(() => {
      const request = requests.find(
        (item) =>
          item.url.endsWith("/sam-image-proposals") &&
          item.init?.method === "POST",
      );
      expect(request).toBeDefined();
      expect(JSON.parse(String(request?.init?.body))).toMatchObject({
        image_id: session.image.id,
        variant: "small",
      });
      expect(JSON.parse(String(request?.init?.body))).not.toHaveProperty("box");
    });
    expect(
      await screen.findByRole("button", { name: "Cancel image predictions" }),
    ).toBeEnabled();
    expect(
      requests.some((item) =>
        item.url.includes("/advanced-providers/sam2/execute"),
      ),
    ).toBe(false);
    expect(requests.some((item) => item.url.endsWith("/accept"))).toBe(false);
    expect(requests.some((item) => item.url.endsWith("/inference-jobs"))).toBe(
      false,
    );
  });

  it("explains Shift+2 needs one saved mask without invoking a detector", async () => {
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith(`/images/${session.image.id}/annotations`))
        return jsonResponse(session);
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request: ${url}`);
    });
    renderEditor();
    await screen.findByRole("heading", {
      name: session.image.original_filename,
    });
    fireEvent.keyDown(window, { key: "@", code: "Digit2", shiftKey: true });
    expect(
      await screen.findByText(
        /Select exactly one saved polygon or raster mask/,
      ),
    ).toBeInTheDocument();
    expect(requests.some((url) => url.includes("/inference-jobs"))).toBe(false);
  });

  it("previews a selected mask with Shift+2 and replaces its identity only after acceptance", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    let accepted = false;
    const mask = {
      id: "refine-mask",
      image_id: session.image.id,
      label_class_id: "class-1",
      geometry_kind: "polygon",
      mask_path: null,
      polygon_json: [
        [20, 20],
        [60, 20],
        [60, 60],
        [20, 60],
      ],
      x_min: 20,
      y_min: 20,
      x_max: 60,
      y_max: 60,
      area_pixels: 1600,
      source_type: "human",
      provenance_json: null,
      status: "verified",
      created_by: "local_user",
      created_at: session.image.created_at,
      updated_at: session.image.updated_at,
      deleted_at: null,
      revision: 3,
    };
    const candidate = {
      candidate_id: "refine-1",
      mask_annotation_id: mask.id,
      image_id: session.image.id,
      expected_revision: 3,
      status: "pending",
      mask_url: "/mask-refinements/refine-1/content",
      old_area_pixels: 1600,
      proposed_area_pixels: 1500,
      iou: 0.91,
      edge_change_percent: 9,
      warnings: [],
      requires_confirmation: false,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith(`/images/${session.image.id}/annotations`))
        return jsonResponse({
          ...session,
          image: { ...session.image, annotation_revision: accepted ? 3 : 2 },
          mask_annotations: [{ ...mask, revision: accepted ? 4 : 3 }],
        });
      if (url.endsWith(`/mask-annotations/${mask.id}/refinements`))
        return jsonResponse(candidate);
      if (url.endsWith("/mask-refinements/refine-1/accept")) {
        accepted = true;
        return jsonResponse({
          image: session.image,
          mask_annotation: { ...mask, revision: 4 },
        });
      }
      const fallback = handleDefaultEditorRequests(url, init);
      if (fallback) return fallback;
      throw new Error(`Unhandled request ${url}`);
    });
    renderEditor();
    const original = await screen.findByTestId("mask-annotation-refine-mask");
    fireEvent.pointerDown(original, { button: 0 });
    fireEvent.pointerUp(window);
    fireEvent.keyDown(window, { key: "@", code: "Digit2", shiftKey: true });
    const review = await screen.findByRole("region", {
      name: "Mask refinement review",
    });
    expect(
      screen.getByTestId("mask-annotation-refine-mask"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("refinement-proposal-overlay"),
    ).toBeInTheDocument();
    expect(accepted).toBe(false);
    expect(
      JSON.parse(
        String(
          requests.find((item) => item.url.endsWith("/refinements"))?.init
            ?.body,
        ),
      ),
    ).toMatchObject({ expected_revision: 3, variant: "small" });
    await userEvent.click(
      within(review).getByRole("button", { name: "Edit proposed mask" }),
    );
    expect(
      screen.getByRole("button", { name: "Undo brush stroke" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Redo brush stroke" }),
    ).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", { name: "Cancel mask edits" }),
    );
    await userEvent.click(
      within(review).getByRole("button", { name: "Accept & Replace" }),
    );
    await screen.findByRole("button", { name: "Undo refinement" });
    expect(accepted).toBe(true);
    expect(screen.getAllByTestId("mask-annotation-refine-mask")).toHaveLength(
      1,
    );
    expect(
      requests.some(
        (item) =>
          item.url.includes("/prediction-proposals/") &&
          item.init?.method === "POST",
      ),
    ).toBe(false);
  });
});
