import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ModelCatalogEntry,
  ModelCatalogResponse,
  Project,
} from "../../api/client";
import { ModelManager } from "./ModelManager";

const project: Project = {
  id: "project-1",
  name: "Reef study",
  slug: "reef-study",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bounding_box",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-07-11T00:00:00Z",
  updated_at: "2026-07-11T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

function entry(
  state: ModelCatalogEntry["installation_state"],
): ModelCatalogEntry {
  return {
    catalog_id: "ultralytics/yolo11/detect/x",
    display_name: "YOLO11 X",
    display_summary: "Official verified YOLO11 X detector.",
    category: "architecture",
    provider_id: "ultralytics",
    architecture: "YOLO11",
    variant: "x",
    task: "detect",
    trainable: true,
    inference_supported: true,
    checkpoint_identifier: "yolo11x.pt",
    download_source_type: "trusted_https_release",
    expected_files: [
      {
        filename: "yolo11x.pt",
        source_url:
          "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x.pt",
        revision: "ultralytics-assets-v8.3.0",
        sha256: "7".repeat(64),
        size_bytes: 114_636_239,
      },
    ],
    expected_size: 114_636_239,
    license_summary: "Ultralytics AGPL-3.0 or enterprise license.",
    provider_pack_id: "ultralytics-base",
    recommended_ram: 24,
    recommended_vram: 12,
    supported_devices: ["cpu", "cuda"],
    supported_runtimes: ["pytorch"],
    desktop_support: "base_sidecar_provider",
    availability: "available",
    provider: "ultralytics",
    provider_version: "8.3.228",
    architecture_family: "YOLO11",
    model_variant: "detect",
    model_size: "x",
    inference: true,
    video_compatibility: false,
    prompt_assist_compatibility: false,
    tiling_compatibility: false,
    tuning_compatibility: false,
    checkpoint_source: "trusted_https_release",
    expected_checksum: "7".repeat(64),
    expected_file_size: 114_636_239,
    model_weight_license: "Ultralytics weights",
    package_license: "Ultralytics package terms",
    required_provider_pack: "ultralytics-base",
    required_package_versions: ["ultralytics==8.3.228"],
    supported_runtime: ["pytorch"],
    supported_precision: ["fp32", "amp"],
    expected_input_size: { width: 640, height: 640 },
    minimum_recommended_ram_gb: 24,
    minimum_recommended_vram_gb: 12,
    desktop_package_status: "base_sidecar_provider",
    clean_machine_verification_status: "verified",
    deprecation_status: "active",
    replacement_model_id: null,
    known_limitations: [],
    installation_state: state,
    installation_reason:
      state === "Available" ? "Weight-free architecture configuration." : null,
    installation_job_id: null,
    installed_asset_id:
      state === "Ready" ? "catalog_model:ultralytics/yolo11/detect/x" : null,
    installed_path:
      state === "Ready" ? "models/catalog-models/yolo11x.pt" : null,
    installed_checksum: state === "Ready" ? "7".repeat(64) : null,
    advanced_only: false,
    requires_confirmation: true,
    selection_kind: "builtin_architecture",
    architecture_reference: "yolo11x.yaml",
    resolved_model_id: null,
  };
}

function catalog(
  state: ModelCatalogEntry["installation_state"],
): ModelCatalogResponse {
  return {
    schema_version: 2,
    catalog_version: "2.0.0",
    application_version: "1.0.1",
    models: [entry(state)],
    validation_warnings: [],
    rejected_entries: 0,
    source_path: "config/model_catalog.json",
    last_refresh_timestamp: "2026-07-11T00:00:00Z",
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function bootstrap(modelCatalog: ModelCatalogResponse) {
  return {
    application_version: "1.0.1",
    catalog: modelCatalog,
    models: [],
    providers: [],
    provider_preflight: null,
    runtime_statuses: [],
    training_compatibility: null,
    provider_summary_states: {},
    validation_warnings: [],
    last_refresh_timestamp: "2026-07-11T00:00:00Z",
    provider_catalog_checked_at: null,
    provider_preflight_checked_at: null,
    runtime_statuses_checked_at: null,
    training_compatibility_checked_at: null,
  };
}

function renderManager(onSelectCatalogModel = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ModelManager
        project={project}
        onSelectCatalogModel={onSelectCatalogModel}
      />
    </QueryClientProvider>,
  );
  return onSelectCatalogModel;
}

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("ModelManager catalog", () => {
  function serve(modelCatalog: ModelCatalogResponse) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/model-catalog")) return jsonResponse(modelCatalog);
      if (url.includes("/model-hub/bootstrap"))
        return jsonResponse(bootstrap(modelCatalog));
      if (url.includes("/models/provider-preflight"))
        return jsonResponse({ providers: [] });
      if (url.includes("/runtime-providers/status")) return jsonResponse([]);
      return new Promise<Response>(() => undefined);
    });
  }
  it("separates architectures and registered models and selects scratch training without acquisition", async () => {
    const fetchSpy = serve(catalog("Available"));
    const onSelect = renderManager();
    expect(
      await screen.findByRole("heading", { name: "Architectures" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Registered Models" }),
    ).toBeInTheDocument();
    const card = (
      await screen.findByRole("heading", { name: "YOLO11 X" })
    ).closest("article")!;
    expect(
      within(card).getByText(/architecture.*Available/i),
    ).toBeInTheDocument();
    expect(within(card).queryByText(/Installed|Ready/)).not.toBeInTheDocument();
    await userEvent.click(
      within(card).getByRole("button", { name: "Train New Model" }),
    );
    expect(onSelect).toHaveBeenCalledWith("ultralytics/yolo11/detect/x");
    expect(
      fetchSpy.mock.calls.every(
        ([input, init]) =>
          !String(input).includes("/model-installs") &&
          (!init?.method || init.method === "GET"),
      ),
    ).toBe(true);
  });
  it("never exposes acquisition actions for legacy catalog states", async () => {
    const modelCatalog = catalog("Not Installed");
    Object.assign(modelCatalog.models[0], {
      category: "pretrained_catalog",
      selection_kind: "managed_catalog_model",
    });
    const fetchSpy = serve(modelCatalog);
    renderManager();
    await screen.findByRole("heading", { name: "YOLO11 X" });
    expect(
      screen.queryByRole("button", {
        name: /^(Install|Install Provider and Model|Update|Repair|Retry|Confirm Install)$/,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText(
        /Model required .*register a compatible model to use this feature/,
      ).length,
    ).toBeGreaterThan(0);
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        String(input).includes("/model-installs"),
      ),
    ).toBe(false);
  });
  it("offers registration for provider capabilities requiring researcher models", async () => {
    const modelCatalog = catalog("Model Required");
    Object.assign(modelCatalog.models[0], {
      category: "provider_requirement",
      selection_kind: "model_required",
      trainable: false,
    });
    serve(modelCatalog);
    renderManager();
    const card = (
      await screen.findByRole("heading", { name: "YOLO11 X" })
    ).closest("article")!;
    expect(
      within(card).getByText(/Model required .*register a compatible model/),
    ).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: "Train New Model" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(card).getByRole("button", { name: "Register Existing Model" }),
    );
    expect(screen.getByLabelText("Checkpoint file")).toBeVisible();
  });
  it("preserves registered checkpoint identity, class bindings and project provenance", async () => {
    const response = bootstrap(catalog("Available"));
    const registered = {
      id: "registered-1",
      project_id: project.id,
      purpose: "detector",
      display_name: "Researcher coral model",
      source_filename: "coral-custom.pt",
      file_size_bytes: 2048,
      framework: "ultralytics",
      task: "detect",
      provider_name: "ultralytics",
      sha256: "abcdef123456".repeat(5),
      class_map_json: { labels: ["Coral"], mapping: { Coral: "class-1" } },
      metadata_json: {},
      created_at: "2026-10-07T12:00:00Z",
      notes: "Researcher-provided checkpoint",
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/model-hub/bootstrap"))
        return jsonResponse({ ...response, models: [registered] });
      if (String(input).includes("/model-catalog"))
        return jsonResponse(response.catalog);
      return new Promise<Response>(() => undefined);
    });
    renderManager();
    const card = (
      await screen.findByRole("heading", { name: registered.display_name })
    ).closest("article")!;
    expect(within(card).getByText("coral-custom.pt")).toBeInTheDocument();
    expect(within(card).getByText(/abcdef123456/)).toBeInTheDocument();
    expect(within(card).getByText("Coral")).toBeInTheDocument();
    expect(within(card).getByText("Mapped")).toBeInTheDocument();
    expect(
      within(card).getByText(`Project: ${project.id}`),
    ).toBeInTheDocument();
    expect(within(card).getByText(/Registered: /)).toBeInTheDocument();
  });

  it("routes pose architectures to their schema-aware workflow", async () => {
    const modelCatalog = catalog("Available");
    Object.assign(modelCatalog.models[0], {
      task: "pose",
      architecture_reference: "yolo11x-pose.yaml",
    });
    serve(modelCatalog);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const poseTraining = vi.fn();
    const detectorTraining = vi.fn();
    render(
      <QueryClientProvider client={queryClient}>
        <ModelManager
          project={project}
          onSelectCatalogModel={detectorTraining}
          onTrainPoseArchitecture={poseTraining}
        />
      </QueryClientProvider>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Train New Model" }),
    );
    expect(poseTraining).toHaveBeenCalledWith("yolo11x-pose.yaml");
    expect(detectorTraining).not.toHaveBeenCalled();
  });

  it("registers a researcher provider bundle locally and displays its provenance", async () => {
    const modelCatalog = catalog("Model Required");
    Object.assign(modelCatalog.models[0], {
      category: "provider_requirement",
      provider_id: "smolvlm",
      provider: "smolvlm",
      selection_kind: "model_required",
      trainable: false,
    });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        if (url.endsWith("/provider-models/smolvlm/register"))
          return jsonResponse({
            id: "provider-model-1",
            provider_id: "smolvlm",
            task: "visual_question",
            original_filename: "my-smolvlm.zip",
            sha256: "b".repeat(64),
            project_id: project.id,
            registered_at: "2026-10-07T12:00:00Z",
          });
        if (url.includes("/model-hub/bootstrap"))
          return jsonResponse(bootstrap(modelCatalog));
        if (url.includes("/model-catalog")) return jsonResponse(modelCatalog);
        return new Promise<Response>(() => undefined);
      });
    renderManager();
    const card = (
      await screen.findByRole("heading", { name: "YOLO11 X" })
    ).closest("article")!;
    await userEvent.click(
      within(card).getByRole("button", { name: "Register Existing Model" }),
    );
    expect(screen.getByLabelText("Optional model provider")).toHaveValue(
      "smolvlm",
    );
    const file = new File(["local checkpoint bundle"], "my-smolvlm.zip", {
      type: "application/zip",
    });
    await userEvent.upload(screen.getByLabelText("Provider model file"), file);
    await userEvent.click(
      screen.getByRole("button", { name: "Register provider model" }),
    );
    expect(
      await screen.findByText(/Registered my-smolvlm.zip/),
    ).toBeInTheDocument();
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
    const upload = fetchSpy.mock.calls.find(([input]) =>
      String(input).includes("/provider-models/smolvlm/register"),
    );
    expect(upload?.[1]?.method).toBe("POST");
    const uploadedFile = (upload?.[1]?.body as FormData).get("file");
    expect(uploadedFile).toBeInstanceOf(File);
    expect((uploadedFile as File).name).toBe("my-smolvlm.zip");
    expect((uploadedFile as File).size).toBe(file.size);
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        String(input).includes("/model-installs"),
      ),
    ).toBe(false);
  });

  it("never reports zero catalog entries while loading", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );
    renderManager();
    expect(screen.getByText("Loading catalog...")).toBeInTheDocument();
    expect(screen.queryByText("0 catalog entries")).not.toBeInTheDocument();
  });
});
