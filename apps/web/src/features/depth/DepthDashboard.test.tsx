import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAnnotationSession,
  type AnnotationSession,
  type Project,
} from "../../api/client";
import { getImages, getJob } from "../phase456/api";
import {
  getDepthProviderReadiness,
  listDepthMaps,
  measureMaskDepth,
  queueDepthMap,
  type DepthMapRecord,
  type DepthProviderReadiness,
} from "./api";
import { DepthDashboard } from "./DepthDashboard";

vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>(
      "../../api/client",
    );
  return { ...actual, getAnnotationSession: vi.fn() };
});

vi.mock("../phase456/api", async () => {
  const actual =
    await vi.importActual<typeof import("../phase456/api")>("../phase456/api");
  return { ...actual, getImages: vi.fn(), getJob: vi.fn() };
});

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getDepthProviderReadiness: vi.fn(),
    listDepthMaps: vi.fn(),
    measureMaskDepth: vi.fn(),
    queueDepthMap: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Depth project",
  slug: "depth-project",
  description: null,
  storage_root: "projects/depth-project",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

const annotationSession: AnnotationSession = {
  image: {
    id: "image-1",
    project_id: project.id,
    original_filename: "coral.png",
    managed_path: "projects/depth-project/images/coral.png",
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
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
  },
  label_classes: [],
  annotations: [],
  counts_by_class: [],
  previous_image_id: null,
  next_image_id: null,
};

function readiness(
  overrides: Partial<DepthProviderReadiness> = {},
): DepthProviderReadiness {
  return {
    provider_id: "depth_anything_v2_relative",
    model_id: "depth-anything/Depth-Anything-V2-Small-hf",
    ready: true,
    resolved_device: "cpu",
    model_source: "huggingface_cache",
    requires_network: false,
    reason: null,
    dependencies: {
      torch: true,
      transformers: true,
      huggingface_hub: true,
    },
    ...overrides,
  };
}

const depthMap: DepthMapRecord = {
  id: "depth-1",
  project_id: project.id,
  image_id: "image-1",
  provider_id: "depth_anything_v2_relative",
  model_id: "depth-anything/Depth-Anything-V2-Small-hf",
  model_checksum: null,
  depth_kind: "relative",
  unit: null,
  minimum_depth: 0,
  maximum_depth: 1,
  median_depth: 0.5,
  valid_pixel_count: 307_200,
  metadata_json: {},
  created_at: "2026-07-20T00:00:00Z",
};

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DepthDashboard project={project} />
    </QueryClientProvider>,
  );
}

describe("DepthDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getDepthProviderReadiness).mockImplementation(
      async ({ device }) =>
        device === "cuda"
          ? readiness({
              ready: false,
              resolved_device: "cuda",
              model_source: "missing",
              reason:
                "The selected provider cannot use an available CUDA device.",
            })
          : readiness(),
    );
    vi.mocked(getImages).mockResolvedValue({
      items: [
        {
          id: "image-1",
          original_filename: "coral.png",
          annotation_status: "unannotated",
          annotation_count: 0,
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });
    vi.mocked(getAnnotationSession).mockResolvedValue(annotationSession);
    vi.mocked(listDepthMaps).mockResolvedValue([]);
    vi.mocked(queueDepthMap).mockResolvedValue({
      depth_map_id: "depth-1",
      job: {
        id: "job-1",
        status: "queued",
        progress_current: 0,
        progress_total: 1,
      },
    });
    vi.mocked(getJob).mockResolvedValue({
      id: "job-1",
      status: "succeeded",
      progress_current: 1,
      progress_total: 1,
    } as Awaited<ReturnType<typeof getJob>>);
    vi.mocked(measureMaskDepth).mockRejectedValue(
      new Error("Measurement should not run without a selected mask."),
    );
  });

  it("uses provider readiness and available devices without path heuristics", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const generate = screen.getByRole("button", {
      name: "Generate aligned depth map",
    });

    await waitFor(() => expect(generate).toBeEnabled());
    expect(screen.getByLabelText("Model ID or local path")).toHaveValue(
      "depth-anything/Depth-Anything-V2-Small-hf",
    );
    expect(
      screen.getByLabelText("Use installed/local checkpoints only"),
    ).toBeChecked();

    await user.selectOptions(screen.getByLabelText("Device"), "cpu");
    expect(generate).toBeEnabled();
    await user.selectOptions(screen.getByLabelText("Device"), "cuda");
    expect(generate).toBeDisabled();
    expect(
      screen.getByText(/cannot use an available cuda device/i),
    ).toBeInTheDocument();
  });

  it("blocks unavailable providers with backend remediation", async () => {
    vi.mocked(getDepthProviderReadiness).mockResolvedValue(
      readiness({
        ready: false,
        model_source: "missing",
        reason:
          "Transformers is not installed. Install the Depth Anything provider pack.",
        dependencies: {
          torch: true,
          transformers: false,
          huggingface_hub: true,
        },
      }),
    );
    renderDashboard();

    const generate = screen.getByRole("button", {
      name: "Generate aligned depth map",
    });
    await waitFor(() => expect(generate).toBeDisabled());
    expect(
      await screen.findByText(/transformers is not installed/i),
    ).toHaveTextContent("Install the Depth Anything provider pack.");
  });

  it("keeps generation blocked while provider readiness is loading", async () => {
    vi.mocked(getDepthProviderReadiness).mockReturnValue(
      new Promise<DepthProviderReadiness>(() => undefined),
    );
    renderDashboard();

    expect(
      await screen.findByRole("status", {
        name: "",
      }),
    ).toHaveTextContent("Checking Depth Anything dependencies and devices...");
    expect(
      screen.getByRole("button", { name: "Generate aligned depth map" }),
    ).toBeDisabled();
  });

  it("shows provider errors and enables generation after retry", async () => {
    const user = userEvent.setup();
    vi.mocked(getDepthProviderReadiness)
      .mockRejectedValueOnce(new Error("Capability endpoint unavailable."))
      .mockResolvedValueOnce(readiness());
    renderDashboard();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Capability endpoint unavailable.",
    );
    const generate = screen.getByRole("button", {
      name: "Generate aligned depth map",
    });
    expect(generate).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "Retry provider check" }),
    );
    await waitFor(() => expect(generate).toBeEnabled());
  });

  it("recovers a failed depth preview with a cache-busting retry", async () => {
    const user = userEvent.setup();
    vi.mocked(listDepthMaps).mockResolvedValue([depthMap]);
    renderDashboard();

    const firstPreview = await screen.findByAltText("Depth map preview");
    fireEvent.error(firstPreview);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Preview failed to load",
    );

    await user.click(screen.getByRole("button", { name: "Retry preview" }));
    const retriedPreview = await screen.findByAltText("Depth map preview");
    expect(retriedPreview.getAttribute("src")).toContain("revision=1");
    fireEvent.load(retriedPreview);
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
  });
});
