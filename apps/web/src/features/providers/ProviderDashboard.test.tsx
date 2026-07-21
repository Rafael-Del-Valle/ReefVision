import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getImages, type Project } from "../../api/client";
import {
  cancelProviderRequest,
  diagnoseProviderModel,
  discoverProviderModels,
  healthCheckProviderModel,
  inferProviderModel,
  listProviderAcceptance,
  listProviderModels,
  loadProviderModel,
  unloadProviderModel,
  verifyProviderModel,
  type ProviderModelAsset,
} from "./api";
import { ProviderDashboard } from "./ProviderDashboard";

vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>(
      "../../api/client",
    );
  return { ...actual, getImages: vi.fn() };
});

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    cancelProviderRequest: vi.fn(),
    diagnoseProviderModel: vi.fn(),
    discoverProviderModels: vi.fn(),
    healthCheckProviderModel: vi.fn(),
    inferProviderModel: vi.fn(),
    listProviderAcceptance: vi.fn(),
    listProviderModels: vi.fn(),
    loadProviderModel: vi.fn(),
    unloadProviderModel: vi.fn(),
    verifyProviderModel: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Provider acceptance",
  slug: "provider-acceptance",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-21T12:00:00Z",
  updated_at: "2026-07-21T12:00:00Z",
  archived_at: null,
  label_classes: [],
};

function asset(
  id: string,
  modelId: string,
  overrides: Partial<ProviderModelAsset> = {},
): ProviderModelAsset {
  return {
    id,
    provider_id: "ultralytics",
    provider_version: "8.3.228",
    model_id: modelId,
    architecture: "YOLO",
    task: "detect",
    capabilities: { detection: true, inference: true },
    checkpoint_path: `models/catalog-models/${id}.pt`,
    checkpoint_path_kind: "managed",
    checkpoint_sha256: "a".repeat(64),
    checkpoint_size_bytes: 1_048_576,
    checkpoint_format: "pytorch_pt",
    source: "managed_catalog",
    revision: "ultralytics-assets-v8.3.0",
    required_packages: ["ultralytics"],
    optional_packages: [],
    supported_devices: ["cpu", "cuda"],
    preferred_device: "auto",
    estimated_vram_bytes: null,
    input_types: ["image"],
    output_types: ["boxes"],
    prompt_types: [],
    supports_training: true,
    supports_inference: true,
    supports_video: false,
    state: "unloaded",
    failure_reason: null,
    verification: { verified: true },
    last_health_check: {},
    last_health_check_at: null,
    last_successful_load_at: "2026-07-21T12:00:00Z",
    last_successful_inference_at: "2026-07-21T12:01:00Z",
    metadata: {},
    latest_acceptance_status: "passed",
    created_at: "2026-07-21T12:00:00Z",
    updated_at: "2026-07-21T12:01:00Z",
    ...overrides,
  };
}

const world = asset("world", "ultralytics/yolo_world/base", {
  architecture: "YOLO-World v2",
  task: "open_vocabulary_detect",
  capabilities: { text_prompt: true, detection: true, inference: true },
  prompt_types: ["text"],
  supports_training: false,
});
const fastSam = asset("fastsam", "ultralytics/fastsam/s", {
  architecture: "FastSAM",
  task: "assist_segmentation",
  capabilities: {
    point_prompt: true,
    box_prompt: true,
    mixed_point_box_prompt: true,
    negative_point_prompt: false,
    inference: true,
  },
  output_types: ["source_aligned_mask", "polygon"],
  prompt_types: ["positive_point", "box", "mixed"],
  supports_training: false,
});
const unavailable = asset("sam2", "ultralytics/sam2/b", {
  architecture: "SAM 2",
  task: "assist_segmentation",
  state: "unavailable",
  failure_reason: "The sam2 runtime package is not installed.",
  verification: { verified: true },
  latest_acceptance_status: null,
});

function action(assetValue: ProviderModelAsset, actionName: string) {
  return {
    asset: assetValue,
    action: actionName,
    state: assetValue.state,
    resolved_device: "cpu",
    details: {},
    warnings: [],
  };
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProviderDashboard project={project} />
    </QueryClientProvider>,
  );
}

describe("ProviderDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listProviderModels).mockResolvedValue({
      items: [world, fastSam, unavailable],
      total: 3,
      limit: 200,
      offset: 0,
      duplicate_checksum_groups: [],
    });
    vi.mocked(getImages).mockResolvedValue({
      items: [
        {
          id: "image-1",
          project_id: project.id,
          original_filename: "reef.png",
          thumbnail_path: null,
          width_px: 80,
          height_px: 60,
          group_key: "fragment-a",
          annotation_status: "unannotated",
          annotation_revision: 0,
          annotation_count: 0,
          created_at: "2026-07-21T12:00:00Z",
          updated_at: "2026-07-21T12:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });
    vi.mocked(listProviderAcceptance).mockResolvedValue({
      items: [
        {
          id: "acceptance-1",
          run_id: "run-1",
          provider_asset_id: world.id,
          provider_id: world.provider_id,
          model_id: world.model_id,
          checkpoint_sha256: world.checkpoint_sha256,
          device: "cuda",
          runtime_versions: { ultralytics: "8.3.228" },
          load_result: "passed",
          inference_result: "passed",
          unload_result: "passed",
          peak_memory_bytes: 2_097_152,
          execution_time_ms: 1234,
          warnings: [],
          failure_reason: null,
          test_input_identifier: "generated-gradient-v1",
          validation_kind: "software_acceptance",
          recorded_at: "2026-07-21T12:02:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(discoverProviderModels).mockResolvedValue({
      discovered_count: 3,
      warnings: [],
    });
    vi.mocked(verifyProviderModel).mockResolvedValue(action(world, "verify"));
    vi.mocked(diagnoseProviderModel).mockResolvedValue(
      action(world, "diagnose"),
    );
    vi.mocked(loadProviderModel).mockResolvedValue(action(world, "load"));
    vi.mocked(unloadProviderModel).mockImplementation(async (assetId) =>
      action(assetId === world.id ? world : fastSam, "unload"),
    );
    vi.mocked(healthCheckProviderModel).mockResolvedValue(
      action(world, "health_check"),
    );
    vi.mocked(cancelProviderRequest).mockResolvedValue({
      request_id: "request-1",
      cancellation_requested: true,
    });
    vi.mocked(inferProviderModel).mockResolvedValue({
      request_id: "request-1",
      provider_id: world.provider_id,
      model_id: world.model_id,
      task: world.task,
      resolved_device: "cuda",
      outputs: [],
      metadata: { empty_result: true },
      warnings: [],
    });
  });

  it("renders truthful lifecycle, acceptance, and capability-specific controls", async () => {
    const user = userEvent.setup();
    renderDashboard();

    expect(await screen.findByText("3 registered")).toBeInTheDocument();
    expect(screen.getByText("2 provider-ready")).toBeInTheDocument();
    expect(screen.getByText("1 unavailable/failed")).toBeInTheDocument();
    expect(
      await screen.findByLabelText(/Required text classes/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Negative point/i)).not.toBeInTheDocument();
    expect(
      await screen.findByText(/passed\/passed\/passed/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not coral scientific validation/i),
    ).toBeInTheDocument();

    await user.selectOptions(
      screen.getByLabelText("Health check kind"),
      "load",
    );
    await user.click(screen.getByRole("button", { name: "Run health check" }));
    await waitFor(() =>
      expect(healthCheckProviderModel).toHaveBeenCalledWith(world.id, {
        device: "auto",
        kind: "load",
        keep_loaded: true,
      }),
    );

    await user.click(screen.getByRole("button", { name: /FastSAM/i }));
    expect(await screen.findByLabelText("Positive point")).toBeEnabled();
    expect(screen.getByLabelText("Negative point")).toBeDisabled();
    expect(screen.getByLabelText(/Box prompt/i)).toBeEnabled();
    expect(
      screen.queryByLabelText(/Required text classes/i),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(unloadProviderModel).toHaveBeenCalledWith(world.id),
    );
  });

  it("cancels obsolete inference and ignores its late result when providers switch", async () => {
    let resolveInference:
      | ((value: Awaited<ReturnType<typeof inferProviderModel>>) => void)
      | undefined;
    vi.mocked(inferProviderModel).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveInference = resolve;
        }),
    );
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByLabelText(/Required text classes/i);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Run managed inference/i }),
      ).toBeEnabled(),
    );
    await user.click(
      screen.getByRole("button", { name: /Run managed inference/i }),
    );
    await waitFor(() => expect(inferProviderModel).toHaveBeenCalledOnce());

    await user.click(screen.getByRole("button", { name: /FastSAM/i }));
    await waitFor(() => expect(cancelProviderRequest).toHaveBeenCalledOnce());
    expect(unloadProviderModel).toHaveBeenCalledWith(world.id);

    resolveInference?.({
      request_id: "late-request",
      provider_id: world.provider_id,
      model_id: world.model_id,
      task: world.task,
      resolved_device: "cuda",
      outputs: [{ box: [1, 1, 2, 2] }],
      metadata: {},
      warnings: [],
    });
    await waitFor(() =>
      expect(
        screen.queryByText(/normalized proposals/i),
      ).not.toBeInTheDocument(),
    );
  });
});
