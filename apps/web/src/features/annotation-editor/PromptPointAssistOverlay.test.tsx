import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAnnotationSession,
  getProjectModelCatalog,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import {
  acceptPromptAssistSession,
  applyPromptAssistPoints,
  createPromptAssistSession,
  deletePromptAssistSession,
  type PromptAssistSession,
} from "./promptPointAssistApi";
import { PromptPointAssistOverlay } from "./PromptPointAssistOverlay";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client",
  );
  return {
    ...actual,
    getAnnotationSession: vi.fn(),
    getProjectModelCatalog: vi.fn(),
  };
});

vi.mock("./promptPointAssistApi", async () => {
  const actual = await vi.importActual<typeof import("./promptPointAssistApi")>(
    "./promptPointAssistApi",
  );
  return {
    ...actual,
    createPromptAssistSession: vi.fn(),
    applyPromptAssistPoints: vi.fn(),
    acceptPromptAssistSession: vi.fn(),
    deletePromptAssistSession: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Point assist project",
  slug: "point-assist-project",
  description: null,
  storage_root: "projects/point-assist-project",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-19T00:00:00Z",
  updated_at: "2026-07-19T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

const baseSession: PromptAssistSession = {
  session_id: "assist-1",
  project_id: project.id,
  image_id: "image-1",
  model_id: "model-1",
  model_display_name: "EfficientViT-SAM",
  provider_name: "efficientvit_sam",
  provider_version: "1.0",
  created_at: "2026-07-19T12:00:00Z",
  last_used_at: "2026-07-19T12:00:00Z",
  expires_at: "2026-07-19T12:30:00Z",
  add_stroke_count: 0,
  subtract_stroke_count: 0,
  positive_point_count: 0,
  negative_point_count: 0,
  brush_radius: null,
  source_prediction_id: null,
  prompt_type: null,
  candidate_box: null,
  candidate_mask_png_base64: null,
};

function renderOverlay() {
  const sidebar = document.createElement("aside");
  sidebar.className = "annotation-editor-sidebar";
  document.body.appendChild(sidebar);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("annotation-canvas");
  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  Object.defineProperty(group, "getScreenCTM", {
    value: () => ({ inverse: () => ({}) }),
  });
  svg.appendChild(group);
  document.body.appendChild(svg);

  class TestDomPoint {
    constructor(
      public x: number,
      public y: number,
    ) {}

    matrixTransform() {
      return { x: this.x, y: this.y };
    }
  }
  vi.stubGlobal("DOMPoint", TestDomPoint);

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <PromptPointAssistOverlay
        project={project}
        imageId="image-1"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return { ...view, svg, sidebar };
}

describe("PromptPointAssistOverlay", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    document.body.innerHTML = "";
    vi.mocked(getAnnotationSession).mockResolvedValue({
      image: {
        id: "image-1",
        project_id: project.id,
        original_filename: "coral.png",
        managed_path: "projects/point-assist-project/images/coral.png",
        thumbnail_path: null,
        sha256: "abc",
        width_px: 640,
        height_px: 480,
        file_size_bytes: 100,
        media_type: "image/png",
        import_source: null,
        capture_timestamp: null,
        group_key: null,
        metadata_json: {},
        annotation_status: "unannotated",
        annotation_revision: 0,
        annotation_count: 0,
        created_at: "2026-07-19T00:00:00Z",
        updated_at: "2026-07-19T00:00:00Z",
      },
      label_classes: [
        {
          id: "class-1",
          project_id: project.id,
          class_index: 0,
          display_order: 0,
          name: "Coral",
          scientific_name: null,
          state_name: null,
          description: null,
          display_color: "#57cc99",
          is_active: true,
          archived_at: null,
          created_at: "2026-07-19T00:00:00Z",
          updated_at: "2026-07-19T00:00:00Z",
        },
      ],
      annotations: [],
      counts_by_class: [],
      previous_image_id: null,
      next_image_id: null,
    } satisfies AnnotationSession);
    vi.mocked(getProjectModelCatalog).mockResolvedValue({
      models: [
        {
          catalog_id: "efficientvit-sam",
          display_name: "EfficientViT-SAM",
          installation_state: "Ready",
          selection_kind: "registered_model",
          resolved_model_id: "model-1",
        },
      ],
    } as never);
    vi.mocked(createPromptAssistSession).mockResolvedValue(baseSession);
    vi.mocked(applyPromptAssistPoints).mockResolvedValue({
      ...baseSession,
      last_used_at: "2026-07-19T12:00:01Z",
      positive_point_count: 1,
      prompt_type: "points",
      candidate_box: { x_min: 80, y_min: 90, x_max: 160, y_max: 180 },
      candidate_mask_png_base64: "cG5n",
    });
    vi.mocked(acceptPromptAssistSession).mockResolvedValue({
      session_id: baseSession.session_id,
      annotation: {},
      mask_annotation: {},
    });
    vi.mocked(deletePromptAssistSession).mockResolvedValue(undefined);
  });

  it("places a point, previews the mask, and accepts it", async () => {
    const user = userEvent.setup();
    const { svg } = renderOverlay();

    expect(
      await screen.findByRole("heading", {
        name: /positive and negative points/i,
      }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Accept mask as")).toHaveValue("class-1"),
    );

    fireEvent.pointerDown(svg, { button: 0, clientX: 100, clientY: 120 });
    expect(await screen.findByText("1 include")).toBeInTheDocument();
    expect(screen.getByText(/\(100.0, 120.0\)/)).toBeInTheDocument();

    const previewButton = screen.getByRole("button", {
      name: /generate mask preview/i,
    });
    expect(previewButton).toBeEnabled();
    await user.click(previewButton);
    await waitFor(() =>
      expect(applyPromptAssistPoints).toHaveBeenCalledWith("assist-1", {
        positive_points: [{ x: 100, y: 120 }],
        negative_points: [],
        context_box: null,
      }),
    );
    expect(
      await screen.findByText(/candidate ready via efficientvit_sam/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^accept mask$/i }));
    await waitFor(() =>
      expect(acceptPromptAssistSession).toHaveBeenCalledWith(
        "assist-1",
        "class-1",
      ),
    );
    expect(
      await screen.findByText(/no point prompts placed yet/i),
    ).toBeInTheDocument();
  });

  it("requires an include point before exclusion points", async () => {
    const user = userEvent.setup();
    const { svg } = renderOverlay();
    await screen.findByRole("heading", { name: /positive and negative points/i });
    await waitFor(() =>
      expect(screen.getByLabelText("Accept mask as")).toHaveValue("class-1"),
    );

    fireEvent.pointerDown(svg, {
      button: 0,
      clientX: 50,
      clientY: 60,
      altKey: true,
    });

    expect(
      await screen.findByText(/place at least one include point before exclude/i),
    ).toBeInTheDocument();
    expect(screen.getByText("0 exclude")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /exclude point/i }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /close/i }));
  });
});
