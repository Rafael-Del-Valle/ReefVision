import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAnnotationSession,
  getProjectModelCatalog,
  type AnnotationSession,
  type ModelCatalogEntry,
  type ModelCatalogResponse,
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
  const actual =
    await vi.importActual<typeof import("../../api/client")>(
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

function promptAssistModel(): ModelCatalogEntry {
  return {
    catalog_id: "efficientvit-sam",
    display_name: "SAM ViT-B",
    display_summary: "Registered point-prompt segmentation model.",
    category: "imported_custom_models",
    provider_id: "segment_anything",
    provider: "segment_anything",
    provider_version: "1.0",
    architecture: "SAM ViT-B",
    architecture_family: "SAM",
    variant: "l0",
    model_variant: "l0",
    model_size: "l0",
    task: "assist_segmentation",
    trainable: false,
    inference_supported: true,
    inference: true,
    video_compatibility: false,
    prompt_assist_compatibility: true,
    tiling_compatibility: false,
    tuning_compatibility: false,
    checkpoint_identifier: "efficientvit-sam-l0.pt",
    checkpoint_source: "registered_model",
    download_source_type: "local_registration",
    expected_files: [],
    expected_size: null,
    expected_file_size: null,
    expected_checksum: null,
    license_summary: "User supplied.",
    model_weight_license: "User supplied.",
    package_license: "Apache-2.0",
    provider_pack_id: "efficientvit-sam",
    required_provider_pack: "efficientvit-sam",
    required_package_versions: [],
    recommended_ram: 8,
    recommended_vram: 4,
    minimum_recommended_ram_gb: 8,
    minimum_recommended_vram_gb: 4,
    supported_devices: ["cpu", "cuda"],
    supported_runtimes: ["pytorch"],
    supported_runtime: ["pytorch"],
    supported_precision: ["fp32"],
    desktop_support: "provider_pack",
    desktop_package_status: "installed",
    clean_machine_verification_status: "verified",
    availability: "available",
    deprecation_status: "active",
    replacement_model_id: null,
    known_limitations: [],
    installation_state: "Ready",
    installation_reason: "Installed and verified.",
    installation_job_id: null,
    installed_asset_id: "registered-model:model-1",
    installed_path: "models/registered/model-1",
    installed_checksum: null,
    metadata_verified: true,
    provider_ready: true,
    provider_state: "unloaded",
    provider_failure_reason: null,
    capabilities: {
      point_prompt: true,
      negative_point_prompt: true,
      box_prompt: true,
      mixed_point_box_prompt: true,
    },
    latest_acceptance_status: "passed",
    advanced_only: false,
    requires_confirmation: false,
    selection_kind: "registered_model",
    architecture_reference: null,
    resolved_model_id: "model-1",
    compatibility_reasons: [],
  };
}

const modelCatalog: ModelCatalogResponse = {
  schema_version: 2,
  catalog_version: "2.0.0",
  application_version: "1.6.0",
  models: [promptAssistModel()],
  validation_warnings: [],
  rejected_entries: 0,
  source_path: "config/model_catalog.json",
  last_refresh_timestamp: "2026-07-19T00:00:00Z",
};

const baseSession: PromptAssistSession = {
  session_id: "assist-1",
  project_id: project.id,
  image_id: "image-1",
  model_id: "model-1",
  model_display_name: "SAM ViT-B",
  provider_name: "segment_anything",
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

function configureCanvas(
  svg: SVGSVGElement,
  coordinateTarget: SVGGraphicsElement = svg,
) {
  Object.defineProperty(svg, "getBoundingClientRect", {
    value: () => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 640,
      bottom: 480,
      width: 640,
      height: 480,
      toJSON: () => ({}),
    }),
  });
  Object.defineProperty(coordinateTarget, "getScreenCTM", {
    value: () => ({ inverse: () => ({}) }),
  });
}

function renderOverlay({
  activeWorkspace = "boxes",
  onAccepted = vi.fn(),
}: {
  activeWorkspace?: "boxes" | "masks" | "raster";
  onAccepted?: (kind: "raster_mask" | "polygon") => void;
} = {}) {
  const sidebar = document.createElement("aside");
  sidebar.className = "annotation-editor-sidebar";
  document.body.appendChild(sidebar);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("annotation-canvas");
  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  svg.appendChild(group);
  configureCanvas(svg, group);
  document.body.appendChild(svg);
  const polygonSvg = document.createElementNS(
    "http://www.w3.org/2000/svg",
    "svg",
  );
  polygonSvg.dataset.testid = "polygon-mask-layer";
  configureCanvas(polygonSvg);
  document.body.appendChild(polygonSvg);
  const rasterSvg = document.createElementNS(
    "http://www.w3.org/2000/svg",
    "svg",
  );
  rasterSvg.dataset.testid = "raster-brush-layer";
  configureCanvas(rasterSvg);
  document.body.appendChild(rasterSvg);

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
  const component = (workspace: "boxes" | "masks" | "raster") => (
    <QueryClientProvider client={queryClient}>
      <PromptPointAssistOverlay
        project={project}
        imageId="image-1"
        activeWorkspace={workspace}
        onAccepted={onAccepted}
        onClose={vi.fn()}
      />
    </QueryClientProvider>
  );
  const view = render(component(activeWorkspace));
  return {
    ...view,
    svg,
    polygonSvg,
    rasterSvg,
    sidebar,
    rerenderWorkspace: (workspace: "boxes" | "masks" | "raster") =>
      view.rerender(component(workspace)),
  };
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
    vi.mocked(getProjectModelCatalog).mockResolvedValue(modelCatalog);
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
    const refetchCounts: number[] = [];
    const onAccepted = vi.fn(() => {
      refetchCounts.push(vi.mocked(getAnnotationSession).mock.calls.length);
    });
    const { svg } = renderOverlay({ onAccepted });

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
      expect(applyPromptAssistPoints).toHaveBeenCalledWith(
        "assist-1",
        {
          positive_points: [{ x: 100, y: 120 }],
          negative_points: [],
          context_box: null,
        },
        expect.anything(),
      ),
    );
    expect(
      await screen.findByText(/candidate ready via segment_anything/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^accept mask$/i }));
    await waitFor(() =>
      expect(acceptPromptAssistSession).toHaveBeenCalledWith(
        "assist-1",
        "class-1",
        "raster_mask",
      ),
    );
    await waitFor(() => expect(onAccepted).toHaveBeenCalledWith("raster_mask"));
    expect(refetchCounts).toEqual([2]);
    expect(deletePromptAssistSession).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/no point prompts placed yet/i),
    ).toBeInTheDocument();
  });

  it("keeps a live remote session when the active workspace changes", async () => {
    const user = userEvent.setup();
    const { svg, rerenderWorkspace, unmount } = renderOverlay();
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );

    fireEvent.pointerDown(svg, { button: 0, clientX: 100, clientY: 120 });
    await user.click(
      screen.getByRole("button", { name: /generate mask preview/i }),
    );
    expect(
      await screen.findByText(/candidate ready via segment_anything/i),
    ).toBeInTheDocument();

    rerenderWorkspace("masks");
    await waitFor(() =>
      expect(screen.getByTestId("point-assist-overlay")).toBeInTheDocument(),
    );
    expect(deletePromptAssistSession).not.toHaveBeenCalled();

    unmount();
    expect(deletePromptAssistSession).toHaveBeenCalledWith("assist-1");
  });

  it("captures point input above a topmost sibling canvas", async () => {
    const { polygonSvg } = renderOverlay({ activeWorkspace: "masks" });
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );
    const topmostCanvas = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "svg",
    );
    const competingHandler = vi.fn();
    topmostCanvas.addEventListener("pointerdown", competingHandler);
    polygonSvg.insertAdjacentElement("afterend", topmostCanvas);

    fireEvent.pointerDown(topmostCanvas, {
      button: 0,
      clientX: 140,
      clientY: 160,
    });

    expect(await screen.findByText("1 include")).toBeInTheDocument();
    expect(competingHandler).not.toHaveBeenCalled();
  });

  it("captures polygon output at mutation time and locks output controls", async () => {
    const user = userEvent.setup();
    let resolveAccept!: () => void;
    vi.mocked(acceptPromptAssistSession).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveAccept = () =>
            resolve({
              session_id: baseSession.session_id,
              annotation: {},
              mask_annotation: {},
            });
        }),
    );
    const onAccepted = vi.fn();
    const { svg } = renderOverlay({ onAccepted });
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );
    fireEvent.pointerDown(svg, { button: 0, clientX: 100, clientY: 120 });
    await user.click(
      screen.getByRole("button", { name: /generate mask preview/i }),
    );
    await screen.findByText(/candidate ready via segment_anything/i);

    const polygonOutput = screen.getByLabelText("Accept as polygon");
    await user.click(polygonOutput);
    await user.click(screen.getByRole("button", { name: /^accept polygon$/i }));
    await waitFor(() =>
      expect(acceptPromptAssistSession).toHaveBeenCalledWith(
        "assist-1",
        "class-1",
        "polygon",
      ),
    );
    expect(polygonOutput).toBeDisabled();

    resolveAccept();
    await waitFor(() => expect(onAccepted).toHaveBeenCalledWith("polygon"));
    expect(deletePromptAssistSession).not.toHaveBeenCalled();
  });

  it("requires an include point before exclusion points", async () => {
    const user = userEvent.setup();
    const { svg } = renderOverlay();
    await screen.findByRole("heading", {
      name: /positive and negative points/i,
    });
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
      await screen.findByText(
        /place at least one include point before exclude/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("0 exclude")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /exclude point/i }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /close/i }));
  });

  it("supports a source-pixel box prompt without forcing a point", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );

    await user.click(screen.getByLabelText(/Use source-pixel context box/i));
    await user.clear(screen.getByLabelText("x_min"));
    await user.type(screen.getByLabelText("x_min"), "12");
    await user.clear(screen.getByLabelText("y_min"));
    await user.type(screen.getByLabelText("y_min"), "18");
    await user.click(
      screen.getByRole("button", { name: /generate mask preview/i }),
    );

    await waitFor(() =>
      expect(applyPromptAssistPoints).toHaveBeenCalledWith(
        "assist-1",
        {
          positive_points: [],
          negative_points: [],
          context_box: { x_min: 12, y_min: 18, x_max: 64, y_max: 64 },
        },
        expect.anything(),
      ),
    );
  });

  it("preserves only compatible prompts when switching providers", async () => {
    const user = userEvent.setup();
    const fastSam = {
      ...promptAssistModel(),
      catalog_id: "fastsam",
      display_name: "FastSAM",
      resolved_model_id: "model-2",
      installed_asset_id: "registered-model:model-2",
      capabilities: {
        point_prompt: true,
        negative_point_prompt: false,
        box_prompt: true,
        mixed_point_box_prompt: false,
      },
    };
    vi.mocked(getProjectModelCatalog).mockResolvedValue({
      ...modelCatalog,
      models: [promptAssistModel(), fastSam],
    });
    const { svg } = renderOverlay();
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );

    fireEvent.pointerDown(svg, { button: 0, clientX: 100, clientY: 120 });
    await user.click(screen.getByRole("button", { name: /Exclude point/i }));
    fireEvent.pointerDown(svg, { button: 0, clientX: 130, clientY: 150 });
    expect(await screen.findByText("1 exclude")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Assist model"), "model-2");
    await waitFor(() =>
      expect(screen.getByText("0 exclude")).toBeInTheDocument(),
    );
    expect(screen.getByText("1 include")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Exclude point/i }),
    ).toBeDisabled();
    expect(
      screen.getByLabelText(/Use source-pixel context box/i),
    ).toBeEnabled();
  });

  it("aborts an obsolete preview request when the provider changes", async () => {
    const user = userEvent.setup();
    const fastSam = {
      ...promptAssistModel(),
      catalog_id: "fastsam",
      display_name: "FastSAM",
      resolved_model_id: "model-2",
      installed_asset_id: "registered-model:model-2",
      capabilities: {
        point_prompt: true,
        negative_point_prompt: false,
        box_prompt: true,
        mixed_point_box_prompt: false,
      },
    };
    vi.mocked(getProjectModelCatalog).mockResolvedValue({
      ...modelCatalog,
      models: [promptAssistModel(), fastSam],
    });
    vi.mocked(applyPromptAssistPoints).mockImplementation(
      () => new Promise(() => undefined),
    );
    const { svg } = renderOverlay();
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );
    fireEvent.pointerDown(svg, { button: 0, clientX: 100, clientY: 120 });
    await user.click(
      screen.getByRole("button", { name: /generate mask preview/i }),
    );
    await waitFor(() => expect(applyPromptAssistPoints).toHaveBeenCalledOnce());
    const signal = vi.mocked(applyPromptAssistPoints).mock.calls[0][2];

    await user.selectOptions(screen.getByLabelText("Assist model"), "model-2");
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByText(/Candidate ready via/i)).not.toBeInTheDocument();
  });

  it("tracks the workspace default until the user chooses an output", async () => {
    const user = userEvent.setup();
    const { rerenderWorkspace } = renderOverlay({ activeWorkspace: "boxes" });
    await waitFor(() =>
      expect(screen.getByLabelText("Assist model")).toHaveValue("model-1"),
    );

    expect(screen.getByLabelText("Accept as raster mask")).toBeChecked();
    rerenderWorkspace("masks");
    await waitFor(() =>
      expect(screen.getByLabelText("Accept as polygon")).toBeChecked(),
    );

    await user.click(screen.getByLabelText("Accept as raster mask"));
    rerenderWorkspace("boxes");
    rerenderWorkspace("masks");
    expect(screen.getByLabelText("Accept as raster mask")).toBeChecked();
  });
});
