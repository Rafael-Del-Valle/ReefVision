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
});
