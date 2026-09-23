import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  JobRecord,
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
    category: "pretrained_catalog",
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
      state === "Ready" ? "Installed and verified." : "Not installed yet.",
    installation_job_id: null,
    installed_asset_id:
      state === "Ready" ? "catalog_model:ultralytics/yolo11/detect/x" : null,
    installed_path:
      state === "Ready" ? "models/catalog-models/yolo11x.pt" : null,
    installed_checksum: state === "Ready" ? "7".repeat(64) : null,
    advanced_only: false,
    requires_confirmation: true,
    selection_kind: "managed_catalog_model",
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
  it("renders returned entries and never reports zero while loading", async () => {
    let resolveCatalog: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/model-catalog")) {
        return new Promise<Response>((resolve) => {
          resolveCatalog = resolve;
        });
      }
      return new Promise<Response>(() => undefined);
    });
    renderManager();

    expect(screen.getByText("Loading catalog...")).toBeInTheDocument();
    expect(screen.queryByText("0 catalog entries")).not.toBeInTheDocument();

    resolveCatalog?.(jsonResponse(catalog("Not Installed")));
    expect(
      await screen.findByRole("heading", { name: "YOLO11 X" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 catalog entries")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install" })).toBeInTheDocument();
    const pretrained = screen
      .getByRole("heading", { name: "Validated presets" })
      .closest("section");
    expect(pretrained).not.toBeNull();
    expect(
      within(pretrained as HTMLElement).queryByLabelText(/Checkpoint file/i),
    ).toBeNull();
  });

  it("confirms installation, shows progress, and cancels the background job", async () => {
    const modelCatalog = catalog("Not Installed");
    let jobStatus: JobRecord["status"] = "running";
    let jobPollUrl = "";
    let jobPollCache: RequestCache | undefined;
    const job: JobRecord = {
      id: "job-1",
      project_id: project.id,
      job_type: "model_install",
      status: "queued",
      progress_current: 0,
      progress_total: 114_636_239,
      request_json: { catalog_id: entry("Not Installed").catalog_id },
      result_json: { stage: "queued" },
      error_message: null,
      created_at: "2026-07-11T00:00:00Z",
      started_at: null,
      completed_at: null,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/model-catalog")) return jsonResponse(modelCatalog);
      if (url.includes("/model-hub/bootstrap"))
        return jsonResponse(bootstrap(modelCatalog));
      if (url.includes("/models/provider-preflight"))
        return jsonResponse({ providers: [] });
      if (url.includes("/runtime-providers/status")) return jsonResponse([]);
      if (url.includes("/training-registry/summary"))
        return new Promise<Response>(() => undefined);
      if (url.includes("/model-installs/") && init?.method === "POST") {
        return jsonResponse(job);
      }
      if (
        url.includes("/jobs/job-1?poll=") &&
        (!init?.method || init.method === "GET")
      ) {
        jobPollUrl = url;
        jobPollCache = init?.cache;
        return jsonResponse({
          ...job,
          status: jobStatus,
          progress_current: 57_318_119,
          result_json: { stage: "downloading" },
        });
      }
      if (url.endsWith("/jobs/job-1/cancel")) {
        jobStatus = "cancelled";
        return jsonResponse({
          ...job,
          status: "cancelled",
          result_json: { stage: "cancelled" },
        });
      }
      return jsonResponse({ detail: "Unexpected request" }, 404);
    });
    renderManager();

    await userEvent.click(
      await screen.findByRole("button", { name: "Install" }),
    );
    const dialog = screen.getByRole("dialog", { name: "YOLO11 X" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText(/109\.3 MB/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm Install" }),
    );
    expect(
      await screen.findByRole("button", { name: "Cancel" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/50%/)).toBeInTheDocument());
    expect(jobPollUrl).toContain("/jobs/job-1?poll=");
    expect(jobPollCache).toBe("no-store");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(jobStatus).toBe("cancelled"));
  });

  it("selects a ready managed model for Training", async () => {
    const modelCatalog = catalog("Ready");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/model-catalog")) return jsonResponse(modelCatalog);
      if (url.includes("/model-hub/bootstrap"))
        return jsonResponse(bootstrap(modelCatalog));
      if (url.includes("/models/provider-preflight"))
        return jsonResponse({ providers: [] });
      if (url.includes("/runtime-providers/status")) return jsonResponse([]);
      return new Promise<Response>(() => undefined);
    });
    const onSelect = renderManager();

    await userEvent.click(
      await screen.findByRole("button", { name: "Select" }),
    );

    expect(onSelect).toHaveBeenCalledWith("ultralytics/yolo11/detect/x");
  });
});
