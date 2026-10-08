import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { ClassificationWorkspace } from "./ClassificationWorkspace";
import * as api from "./classificationApi";

vi.mock("./classificationApi", async () => {
  const actual = await vi.importActual<typeof import("./classificationApi")>(
    "./classificationApi",
  );
  return {
    ...actual,
    getClassificationImages: vi.fn(),
    getClassificationVersions: vi.fn(),
    getClassificationDatasets: vi.fn(),
    getClassifierModels: vi.fn(),
    getImageClassificationLabels: vi.fn(),
    getClassificationPredictions: vi.fn(),
    createClassificationTrainingJob: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Classification project",
  slug: "classification-project",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Swiftia exserta",
      scientific_name: "Swiftia exserta",
      state_name: "open",
      description: null,
      display_color: "#ff0000",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-18T00:00:00Z",
      updated_at: "2026-07-18T00:00:00Z",
    },
  ],
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ClassificationWorkspace project={project} />
    </QueryClientProvider>,
  );
}

describe("ClassificationWorkspace", () => {
  beforeEach(() => {
    vi.mocked(api.getClassificationImages).mockResolvedValue({
      items: [
        {
          id: "image-1",
          project_id: "project-1",
          original_filename: "coral.jpg",
          thumbnail_path: "thumb.jpg",
          width_px: 100,
          height_px: 80,
          group_key: null,
          annotation_status: "reviewed",
          annotation_revision: 1,
          annotation_count: 0,
          created_at: "2026-07-18T00:00:00Z",
          updated_at: "2026-07-18T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });
    vi.mocked(api.getClassificationVersions).mockResolvedValue([
      {
        id: "version-1",
        version_number: 1,
        name: "Reviewed images",
      },
    ] as unknown as Awaited<ReturnType<typeof api.getClassificationVersions>>);
    vi.mocked(api.getClassificationDatasets).mockResolvedValue([]);
    vi.mocked(api.getClassifierModels).mockResolvedValue([]);
    vi.mocked(api.getImageClassificationLabels).mockResolvedValue([]);
    vi.mocked(api.getClassificationPredictions).mockResolvedValue([]);
  });

  it("trains from a YAML architecture rather than a downloadable checkpoint", async () => {
    vi.mocked(api.getClassificationDatasets).mockResolvedValue([
      { id: "dataset-1", mode: "whole_image", sample_count: 2 },
    ] as Awaited<ReturnType<typeof api.getClassificationDatasets>>);
    vi.mocked(api.createClassificationTrainingJob).mockResolvedValue({
      id: "job-1",
    } as Awaited<ReturnType<typeof api.createClassificationTrainingJob>>);
    renderWorkspace();
    expect(screen.getByLabelText("Model size")).toHaveValue("yolo11n-cls.yaml");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Launch classification training" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Launch classification training" }),
    );
    await waitFor(() =>
      expect(api.createClassificationTrainingJob).toHaveBeenCalledWith(
        project.id,
        expect.objectContaining({ architecture: "yolo11n-cls.yaml" }),
      ),
    );
  });

  it("shows label, dataset, training, and inference sections", async () => {
    renderWorkspace();

    expect(
      await screen.findByText("Image classification labels"),
    ).toBeInTheDocument();
    expect(screen.getByText("Classification dataset")).toBeInTheDocument();
    expect(screen.getByText("Ultralytics classifier")).toBeInTheDocument();
    expect(screen.getByText("Top-k predictions")).toBeInTheDocument();
    expect(await screen.findByText("coral.jpg")).toBeInTheDocument();
  });
});
