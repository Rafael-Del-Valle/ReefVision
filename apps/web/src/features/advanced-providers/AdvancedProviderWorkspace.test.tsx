import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as apiClient from "../../api/client";
import type { Project } from "../../api/client";
import { AdvancedProviderWorkspace } from "./AdvancedProviderWorkspace";
import * as providerApi from "./advancedProvidersApi";

vi.mock("./advancedProvidersApi", async () => {
  const actual = await vi.importActual<typeof import("./advancedProvidersApi")>(
    "./advancedProvidersApi",
  );

  return {
    ...actual,
    getAdvancedProviderManifests: vi.fn(),
    listAdvancedProviderImages: vi.fn(),
    preflightAdvancedProvider: vi.fn(),
    executeAdvancedProvider: vi.fn(),
  };
});

vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>(
      "../../api/client",
    );

  return {
    ...actual,
    getProjectModelCatalog: vi.fn(),
  };
});

const project = {
  id: "project-1",
  name: "Provider test project",
} as Project;

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <AdvancedProviderWorkspace project={project} />
    </QueryClientProvider>,
  );
}

describe("AdvancedProviderWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(providerApi.getAdvancedProviderManifests).mockResolvedValue([
      {
        provider_id: "grounding_dino",
        display_name: "Grounding DINO",
        maturity: "ready",
        execution_supported: true,
        execution_surface: "provider_lab",
        supported_tasks: ["open_vocabulary_detect", "phrase_grounding"],
        prompt_fields_by_task: {
          open_vocabulary_detect: ["image_id", "text_prompts", "confidence"],
          phrase_grounding: ["image_id", "text_prompts", "confidence"],
        },
        output_contracts_by_task: {
          open_vocabulary_detect: ["prediction_proposals"],
          phrase_grounding: ["prediction_proposals"],
        },
        required_model_extensions: [],
        required_packages: [],
        recommended_devices: ["cuda", "cpu"],
        known_limitations: [],
        integration_notes: [],
        source_kind: "built_in",
        manifest_version: null,
        declared_capabilities: [],
        availability_status: "ready",
        availability_reason: null,
        source_filename: null,
        source_sha256: null,
        discovery_status: "built_in",
        discovery_errors: [],
      },
      {
        provider_id: "segment_anything",
        display_name: "Segment Anything / Smart Mask",
        maturity: "ready",
        execution_supported: true,
        execution_surface: "existing_workflow",
        supported_tasks: ["assist_segmentation"],
        prompt_fields_by_task: {
          assist_segmentation: ["image_id", "prompt_type"],
        },
        output_contracts_by_task: {
          assist_segmentation: ["mask_candidate"],
        },
        required_model_extensions: [],
        required_packages: [],
        recommended_devices: ["cuda", "cpu"],
        known_limitations: [],
        integration_notes: [],
        source_kind: "built_in",
        manifest_version: null,
        declared_capabilities: [],
        availability_status: "ready",
        availability_reason: null,
        source_filename: null,
        source_sha256: null,
        discovery_status: "built_in",
        discovery_errors: [],
      },
    ]);

    vi.mocked(providerApi.listAdvancedProviderImages).mockResolvedValue([]);

    vi.mocked(apiClient.getProjectModelCatalog).mockResolvedValue({
      models: [
        {
          catalog_id: "transformers/grounding_dino/tiny",
          display_name: "Grounding DINO",
          installation_state: "Ready",
          checkpoint_identifier: "pinned-test",
        },
      ],
    } as unknown as Awaited<
      ReturnType<typeof apiClient.getProjectModelCatalog>
    >);
  });

  it("requires local registration when an optional provider has no model", async () => {
    vi.mocked(apiClient.getProjectModelCatalog).mockResolvedValue({
      models: [],
    } as unknown as apiClient.ModelCatalogResponse);
    renderWorkspace();
    expect(
      await screen.findByText(
        /Model required — register a compatible model to use this feature/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run provider" })).toBeDisabled();
    expect(providerApi.executeAdvancedProvider).not.toHaveBeenCalled();
  });

  it("distinguishes Provider Lab execution from an existing workflow", async () => {
    renderWorkspace();

    await screen.findByText(/runs here in Advanced Provider Lab/i);

    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: "Run provider",
        }),
      ).toBeEnabled();
    });

    fireEvent.change(screen.getByLabelText("Provider"), {
      target: {
        value: "segment_anything",
      },
    });

    await screen.findByText(
      /available through an existing ReefVision workflow/i,
    );

    expect(
      screen.getByRole("button", {
        name: "Run provider",
      }),
    ).toBeDisabled();
  });

  it("inspects a local manifest without offering preflight or execution", async () => {
    vi.mocked(providerApi.getAdvancedProviderManifests).mockResolvedValue([
      {
        provider_id: "local_depth",
        display_name: "Local Depth Inspector",
        maturity: "unavailable",
        execution_supported: false,
        execution_surface: "blocked",
        supported_tasks: ["relative_depth"],
        prompt_fields_by_task: { relative_depth: [] },
        output_contracts_by_task: { relative_depth: [] },
        required_model_extensions: [],
        required_packages: [],
        recommended_devices: [],
        known_limitations: [
          "Local provider manifests are inspect-only in ReefVision 1.5; no provider code was loaded.",
        ],
        integration_notes: ["Inspection only"],
        source_kind: "local_manifest",
        manifest_version: 1,
        declared_capabilities: ["image_semantic_segmentation", "cpu_inference"],
        availability_status: "unavailable",
        availability_reason: "A reviewed ReefVision adapter is not installed.",
        source_filename: "local-depth.json",
        source_sha256: "a".repeat(64),
        discovery_status: "valid",
        discovery_errors: [],
      },
    ] as unknown as providerApi.AdvancedProviderManifest[]);

    renderWorkspace();

    expect(
      await screen.findByRole("heading", { name: "Local provider manifest" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Source file").closest("p")).toHaveTextContent(
      "local-depth.json",
    );
    expect(screen.getByText("Schema version 1")).toBeInTheDocument();
    expect(screen.getByText("image semantic segmentation")).toBeInTheDocument();
    expect(screen.getByText("cpu inference")).toBeInTheDocument();
    expect(
      screen.getByText("A reviewed ReefVision adapter is not installed."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no provider code was loaded/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Run preflight" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run provider" })).toBeDisabled();
  });

  it("shows isolated local manifest validation errors", async () => {
    vi.mocked(providerApi.getAdvancedProviderManifests).mockResolvedValue([
      {
        provider_id: "local_manifest_deadbeef",
        display_name: "Unavailable local manifest: broken.json",
        maturity: "invalid",
        execution_supported: false,
        execution_surface: "blocked",
        supported_tasks: [],
        prompt_fields_by_task: {},
        output_contracts_by_task: {},
        required_model_extensions: [],
        required_packages: [],
        recommended_devices: [],
        known_limitations: [],
        integration_notes: [],
        source_kind: "local_manifest",
        manifest_version: null,
        declared_capabilities: [],
        availability_status: "invalid",
        availability_reason: "Manifest JSON is invalid at line 1, column 2",
        source_filename: "broken.json",
        source_sha256: "b".repeat(64),
        discovery_status: "invalid",
        discovery_errors: ["Manifest JSON is invalid at line 1, column 2"],
      },
    ] as unknown as providerApi.AdvancedProviderManifest[]);

    renderWorkspace();

    expect(
      await screen.findByText("Manifest validation failed"),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("Manifest JSON is invalid at line 1, column 2"),
    ).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Run preflight" }),
    ).toBeDisabled();
  });
});
