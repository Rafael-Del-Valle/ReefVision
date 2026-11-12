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
  window.localStorage?.clear();
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

  it("shows ReefPose anatomy and training provenance and offers pose inference", async () => {
    const response = bootstrap(catalog("Available"));
    const usePoseModel = vi.fn();
    const registered = {
      id: "reefpose-model-1",
      project_id: project.id,
      purpose: "detector",
      display_name: "Fish ReefPose-S",
      source_filename: "best.pt",
      managed_path: "projects/project-1/models/best.pt",
      file_size_bytes: 4096,
      framework: "pytorch",
      task: "pose",
      provider_name: "reefpose",
      provider_version: "1",
      sha256: "f".repeat(64),
      class_map_json: {},
      input_size_json: { width: 256, height: 256 },
      metadata_json: {
        source_architecture: "reefpose-s",
        source_training_run_id: "run-1",
        source_pose_training_dataset_id: "dataset-1",
        source_pose_training_dataset_manifest_sha256: "d".repeat(64),
        source_training_config: { epochs: 10, batch: 4 },
        source_metrics: { validation_loss: 0.42 },
        source_checkpoint_sha256: "f".repeat(64),
        source_checkpoint_size_bytes: 4096,
        pose_landmark_schema: {
          schema_name: "Fish anatomy",
          schema_id: "schema-1",
          schema_revision: 3,
          content_hash: "a".repeat(64),
          keypoint_count: 7,
        },
      },
      created_at: "2026-11-07T12:00:00Z",
      updated_at: "2026-11-07T12:00:00Z",
      notes: null,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/model-hub/bootstrap"))
        return jsonResponse({ ...response, models: [registered] });
      if (String(input).includes("/model-catalog"))
        return jsonResponse(response.catalog);
      return new Promise<Response>(() => undefined);
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ModelManager project={project} onUsePoseModel={usePoseModel} />
      </QueryClientProvider>,
    );

    const card = (
      await screen.findByRole("heading", { name: "Fish ReefPose-S" })
    ).closest("article")!;
    expect(
      within(card).getByText(/Fish anatomy.*revision 3/),
    ).toBeInTheDocument();
    expect(
      within(card).getByText(/7 anatomical keypoints/),
    ).toBeInTheDocument();
    expect(within(card).getByText(/run-1/)).toBeInTheDocument();
    expect(within(card).getByText(/validation_loss/)).toBeInTheDocument();
    await userEvent.click(
      within(card).getByRole("button", { name: "Use in Pose Tracking" }),
    );
    expect(usePoseModel).toHaveBeenCalledWith("reefpose-model-1");
  });

  it("runs a held-out ReefPose evaluation and displays scientific metrics", async () => {
    const response = bootstrap(catalog("Available"));
    const registered = {
      id: "reefpose-model-1",
      project_id: project.id,
      purpose: "detector",
      display_name: "Fish ReefPose-S",
      source_filename: "best.pt",
      managed_path: "projects/project-1/models/best.pt",
      file_size_bytes: 4096,
      framework: "pytorch",
      task: "pose",
      provider_name: "reefpose",
      provider_version: "1",
      sha256: "f".repeat(64),
      class_map_json: {},
      input_size_json: { width: 256, height: 256 },
      metadata_json: {
        source_pose_training_dataset_id: "training-dataset",
        source_pose_validation_dataset_id: "validation-dataset",
        source_pose_schema_id: "schema-1",
        source_pose_schema_revision: 3,
        source_pose_schema_content_hash: "a".repeat(64),
        pose_landmark_schema: {
          schema_name: "Fish anatomy",
          schema_id: "schema-1",
          schema_revision: 3,
          content_hash: "a".repeat(64),
          keypoint_count: 7,
        },
      },
      created_at: "2026-11-07T12:00:00Z",
      updated_at: "2026-11-07T12:00:00Z",
      notes: null,
    };
    const evaluation = {
      id: "evaluation-1",
      project_id: project.id,
      model_id: registered.id,
      evaluation_dataset_id: "held-out-dataset",
      schema_version: "reefpose-evaluation-run-0001",
      status: "completed",
      configuration_json: { pck_thresholds: [0.1, 0.2] },
      metrics_json: {
        pck: { "0.1": 0.75, "0.2": 0.9 },
        nme: 0.08,
        mean_euclidean_error: 2.5,
        localization_coverage: 0.95,
        oks: null,
      },
      predictions_json: [],
      provenance_json: { truth_policy: "scientist_verified_only" },
      warnings_json: ["OKS omitted without explicit sigmas."],
      result_sha256: "e".repeat(64),
      inference_latency_ms: 4.2,
      images_per_second: 238.1,
      created_at: "2026-11-12T12:00:00Z",
    };
    let completed = false;
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/model-hub/bootstrap"))
          return jsonResponse({ ...response, models: [registered] });
        if (url.includes("/model-catalog"))
          return jsonResponse(response.catalog);
        if (url.includes("/pose-training-datasets"))
          return jsonResponse([
            {
              id: "training-dataset",
              project_id: project.id,
              name: "Training set",
              status: "complete",
              pose_schema_id: "schema-1",
              pose_schema_revision: 3,
              pose_schema_content_hash: "a".repeat(64),
              manifest_sha256: "1".repeat(64),
              item_count: 10,
              source_round_id: "round-1",
              schema_version: "pose-training-dataset-0001",
              source_selection_sha256: "2".repeat(64),
              source_retraining_manifest_sha256: "3".repeat(64),
              manifest_json: {},
              created_by: "scientist",
              created_at: "2026-11-10T12:00:00Z",
            },
            {
              id: "held-out-dataset",
              project_id: project.id,
              name: "Held-out fish",
              status: "complete",
              pose_schema_id: "schema-1",
              pose_schema_revision: 3,
              pose_schema_content_hash: "a".repeat(64),
              manifest_sha256: "4".repeat(64),
              item_count: 5,
              source_round_id: "round-2",
              schema_version: "pose-training-dataset-0001",
              source_selection_sha256: "5".repeat(64),
              source_retraining_manifest_sha256: "6".repeat(64),
              manifest_json: {},
              created_by: "scientist",
              created_at: "2026-11-11T12:00:00Z",
            },
          ]);
        if (url.includes("/pose-evaluations") && init?.method === "POST") {
          completed = true;
          expect(JSON.parse(String(init.body))).toMatchObject({
            model_id: registered.id,
            evaluation_dataset_id: "held-out-dataset",
          });
          return jsonResponse(evaluation);
        }
        if (url.includes("/pose-evaluations"))
          return jsonResponse(completed ? [evaluation] : []);
        return new Promise<Response>(() => undefined);
      });
    renderManager();

    const card = (
      await screen.findByRole("heading", { name: "Fish ReefPose-S" })
    ).closest("article")!;
    await userEvent.selectOptions(
      await within(card).findByLabelText("Held-out evaluation dataset"),
      "held-out-dataset",
    );
    expect(
      within(card).queryByRole("option", { name: /Training set/ }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(card).getByRole("button", { name: "Evaluate ReefPose" }),
    );
    expect(await within(card).findByText(/PCK@0.1: 0.750/)).toBeInTheDocument();
    expect(within(card).getByText(/NME: 0.080/)).toBeInTheDocument();
    expect(within(card).getByText(/4.20 ms/)).toBeInTheDocument();
    expect(
      within(card).getByRole("link", { name: "Export CSV" }),
    ).toHaveAttribute("href", expect.stringContaining("format=csv"));
    expect(fetchSpy).toHaveBeenCalled();
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
