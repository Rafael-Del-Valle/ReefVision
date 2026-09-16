import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
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
import { AnnotationEditor } from "./AnnotationEditor";

const project: Project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: "Octocoral polyp annotations",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
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

function renderEditor(onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AnnotationEditor
        project={project}
        initialImageId={session.image.id}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onClose };
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AnnotationEditor", () => {
  it("shows a rotation handle for a selected regular box and deletes it with Backspace", async () => {
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
          image: { ...session.image, annotation_revision: 3 },
          annotations: [],
          counts_by_class: [
            { label_class_id: "class-1", count: 0 },
            { label_class_id: "class-2", count: 0 },
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

    const objectList = screen.getByRole("listbox", { name: "Objects" });
    await userEvent.click(within(objectList).getAllByRole("option")[0]);

    expect(
      screen.getByTestId("rotation-handle-annotation-1"),
    ).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "Backspace" });

    expect(
      screen.queryByTestId("annotation-annotation-1"),
    ).not.toBeInTheDocument();
  });

  it("shows rotation and resize handles for a selected rotated box in Main Select", async () => {
    const sessionWithRotatedBox = {
      ...session,
      mask_annotations: [
        {
          id: "rotated-mask-1",
          image_id: session.image.id,
          label_class_id: "class-1",
          geometry_kind: "rotated_box",
          mask_path: null,
          polygon_json: [
            [320, 320],
            [440, 340],
            [420, 440],
            [300, 420],
          ],
          x_min: 300,
          y_min: 320,
          x_max: 440,
          y_max: 440,
          area_pixels: 12400,
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

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(`/images/${session.image.id}/annotations`) &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse(sessionWithRotatedBox);
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

    const objectList = screen.getByRole("listbox", { name: "Objects" });
    const rotatedRow = within(objectList).getByText("Rotated box").closest(
      "button",
    );
    if (!(rotatedRow instanceof HTMLButtonElement)) {
      throw new Error("Rotated box row was not rendered");
    }
    await userEvent.click(rotatedRow);

    expect(
      screen.getByTestId("rotation-handle-rotated-mask-1"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("resize-handle-rotated-mask-1-0"),
    ).toBeInTheDocument();
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
});
