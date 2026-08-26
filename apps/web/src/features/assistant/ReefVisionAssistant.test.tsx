import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getProjectModelCatalog, type Project } from "../../api/client";
import {
  executeAdvancedProvider,
  listAdvancedProviderImages,
} from "../advanced-providers/advancedProvidersApi";
import { ReefVisionAssistant } from "./ReefVisionAssistant";

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

vi.mock("../advanced-providers/advancedProvidersApi", () => ({
  executeAdvancedProvider: vi.fn(),
  listAdvancedProviderImages: vi.fn(),
}));

const project = {
  id: "project-1",
  name: "Coral Study",
  description: "Test project",
  label_classes: [],
} as unknown as Project;

function renderAssistant(onNavigate = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ReefVisionAssistant
        project={project}
        activeView="models"
        onNavigate={onNavigate}
      />
    </QueryClientProvider>,
  );
  return onNavigate;
}

describe("ReefVisionAssistant", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(listAdvancedProviderImages).mockResolvedValue([
      {
        id: "image-1",
        original_filename: "coral.jpg",
        width_px: 1280,
        height_px: 960,
      },
    ]);
    vi.mocked(getProjectModelCatalog).mockResolvedValue({
      project_id: "project-1",
      models: [
        {
          catalog_id: "transformers/smolvlm/256m-instruct",
          display_name: "SmolVLM 256M Instruct",
          installation_state: "Ready",
        },
      ],
    } as never);
    vi.mocked(executeAdvancedProvider).mockResolvedValue({
      provider_id: "smolvlm",
      task: "visual_question",
      model_id: "HuggingFaceTB/SmolVLM-256M-Instruct",
      model_revision: "test",
      status: "succeeded",
      result: { text: "Visible branching coral structure." },
      warnings: [],
    });
  });

  it("provides deterministic navigation without invoking a model", async () => {
    const onNavigate = renderAssistant();

    fireEvent.click(screen.getByRole("button", { name: "Ask ReefVision" }));
    fireEvent.change(screen.getByLabelText("Question"), {
      target: { value: "How do I calibrate an image?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      await screen.findByText(/Calibration and scientific measurements live/),
    ).toBeInTheDocument();
    expect(executeAdvancedProvider).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Go to Images & annotation" }),
    );
    expect(onNavigate).toHaveBeenCalledWith("gallery");
  });

  it("uses SmolVLM only after explicit image opt-in", async () => {
    renderAssistant();

    fireEvent.click(screen.getByRole("button", { name: "Ask ReefVision" }));
    await screen.findByText(/SmolVLM status:/);

    await waitFor(() =>
      expect(
        screen.getByLabelText(/Ask SmolVLM about this image/),
      ).toBeEnabled(),
    );

    fireEvent.click(screen.getByLabelText(/Ask SmolVLM about this image/));
    fireEvent.change(screen.getByLabelText("Question"), {
      target: { value: "What is visible?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      await screen.findByText(/Visible branching coral structure/),
    ).toBeInTheDocument();
    expect(executeAdvancedProvider).toHaveBeenCalledWith(
      "project-1",
      "smolvlm",
      expect.objectContaining({
        task: "visual_question",
        allow_model_download: false,
        prompt_fields: expect.objectContaining({
          image_id: "image-1",
        }),
      }),
    );
  });
});
