import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { getProject } from "../../api/client";
import { getModels } from "../phase456/api";
import {
  checkSam2SidecarHealth,
  registerSam2SidecarModel,
} from "./sam2SidecarApi";
import { registerSam3SidecarModel } from "./sam3SidecarApi";
import { Sam3WorkflowSetupPanel } from "./Sam3WorkflowSetupPanel";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>(
    "../../api/client",
  );
  return { ...actual, getProject: vi.fn() };
});
vi.mock("../phase456/api", () => ({ getModels: vi.fn() }));
vi.mock("./sam2SidecarApi", () => ({
  checkSam2SidecarHealth: vi.fn(),
  registerSam2SidecarModel: vi.fn(),
}));
vi.mock("./sam3SidecarApi", () => ({ registerSam3SidecarModel: vi.fn() }));

const project: Project = {
  id: "project-1",
  name: "Consensus project",
  slug: "consensus-project",
  description: null,
  storage_root: "projects/consensus-project",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-23T12:00:00Z",
  updated_at: "2026-07-23T12:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Octocoral",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#ffffff",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-23T12:00:00Z",
      updated_at: "2026-07-23T12:00:00Z",
    },
  ],
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Sam3WorkflowSetupPanel projectId={project.id} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getProject).mockResolvedValue(project);
  vi.mocked(getModels).mockResolvedValue([
    {
      id: "sam2-existing",
      purpose: "assist",
      task: "assist_segmentation",
      display_name: "Existing SAM 2",
      provider_name: "sam2",
      metadata_json: {},
    },
  ]);
  vi.mocked(checkSam2SidecarHealth).mockResolvedValue({
    status: "ok",
    provider: "sam2_sidecar",
    model_version: "sam2.1_hiera_large.pt",
    device: "cuda:0",
    endpoint: "http://127.0.0.1:8766",
    token_configured: true,
  });
  vi.mocked(registerSam2SidecarModel).mockResolvedValue({
    id: "sam2-sidecar-new",
    project_id: project.id,
    purpose: "assist",
    display_name: "SAM 2 Hiera Large sidecar",
    framework: "sam2-sidecar",
    task: "assist_segmentation",
    provider_name: "sam2_sidecar",
    provider_version: "1",
    managed_path: "projects/consensus-project/models/sam2.json",
    sha256: "a".repeat(64),
  });
  vi.mocked(registerSam3SidecarModel).mockResolvedValue({
    id: "sam3-model",
    project_id: project.id,
    purpose: "segmenter",
    display_name: "SAM 3 octocoral segmenter",
    managed_path: "projects/consensus-project/models/sam3.json",
    sha256: "b".repeat(64),
    framework: "sam3-sidecar",
    task: "segment",
    provider_name: "sam3_sidecar",
    provider_version: "sam3.1",
    class_map_json: {},
    metadata_json: {},
  });
});

describe("Sam3WorkflowSetupPanel", () => {
  it("tests and registers an isolated SAM 2 sidecar", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "Test SAM 2 connection" }),
    );
    await waitFor(() =>
      expect(checkSam2SidecarHealth).toHaveBeenCalledWith({
        endpoint: "http://127.0.0.1:8766",
        token_env: "REEFVISION_SAM2_SIDECAR_TOKEN",
        timeout_seconds: 120,
      }),
    );
    expect(await screen.findByText("SAM 2 sidecar is ready.")).toBeInTheDocument();
    expect(screen.getAllByText(/sam2\.1_hiera_large\.pt/)).not.toHaveLength(0);

    await user.click(
      screen.getByRole("button", { name: "Register SAM 2 sidecar" }),
    );
    await waitFor(() =>
      expect(registerSam2SidecarModel).toHaveBeenCalledWith(project.id, {
        display_name: "SAM 2 Hiera Large sidecar",
        endpoint: "http://127.0.0.1:8766",
        token_env: "REEFVISION_SAM2_SIDECAR_TOKEN",
        timeout_seconds: 120,
      }),
    );
    expect(
      await screen.findByText("SAM 2 Hiera Large sidecar registered."),
    ).toBeInTheDocument();
  });

  it("includes both in-process and sidecar SAM 2 providers", async () => {
    vi.mocked(getModels).mockResolvedValue([
      {
        id: "sam2-local",
        purpose: "assist",
        task: "assist_segmentation",
        display_name: "Local SAM 2",
        provider_name: "sam2",
        metadata_json: {},
      },
      {
        id: "sam2-sidecar",
        purpose: "assist",
        task: "assist_segmentation",
        display_name: "Isolated SAM 2",
        provider_name: "sam2_sidecar",
        metadata_json: {},
      },
    ]);
    renderPanel();

    expect(await screen.findByText(/Local SAM 2/)).toBeInTheDocument();
    expect(screen.getByText(/Isolated SAM 2/)).toBeInTheDocument();
  });
});
