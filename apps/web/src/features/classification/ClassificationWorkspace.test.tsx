import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
  };
});

const project: Project = {
  id: "project-1",
  name: "Classification project",
  slug: "classification-project",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
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
        project_id: "project-1",
        version_number: 1,
        name: "Reviewed images",
        notes: null,
        parent_version_id: null,
        status: "complete",
        requested_split_method: "random",
        resolved_split_method: "random",
        eligible_annotation_statuses_json: ["reviewed"],
        requested_ratios_json: { train: 0.7, validation: 0.2, test: 0.1 },
        achieved_ratios_json: { train: 1, validation: 0, test: 0 },
        split_seed: 42,
        reuse_parent_assignments: false,
        missing_group_key_count: 0,
        image_count: 1,
        annotation_count: 0,
        mask_annotation_count: 0,
        per_class_counts_json: [],
        manifest_path: "manifest.json",
        manifest_sha256: "a".repeat(64),
        split_manifest_sha256: "b".repeat(64),
        class_map_json: [],
        schema_version: "0007",
        app_version: "1.7.0",
        created_by: "local_user",
        created_at: "2026-07-18T00:00:00Z",
        completed_at: "2026-07-18T00:00:00Z",
      },
    ]);
    vi.mocked(api.getClassificationDatasets).mockResolvedValue([]);
    vi.mocked(api.getClassifierModels).mockResolvedValue([]);
    vi.mocked(api.getImageClassificationLabels).mockResolvedValue([]);
    vi.mocked(api.getClassificationPredictions).mockResolvedValue([]);
  });

  it("shows label, dataset, training, and inference sections", async () => {
    renderWorkspace();

    expect(await screen.findByText("Image classification labels")).toBeInTheDocument();
    expect(screen.getByText("Classification dataset")).toBeInTheDocument();
    expect(screen.getByText("Ultralytics classifier")).toBeInTheDocument();
    expect(screen.getByText("Top-k predictions")).toBeInTheDocument();
    expect(await screen.findByText("coral.jpg")).toBeInTheDocument();
  });
});
