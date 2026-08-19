import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { InteroperabilityWorkspace } from "./InteroperabilityWorkspace";
import * as exchangeApi from "./projectExchangeApi";

vi.mock("./projectExchangeApi", async () => {
  const actual = await vi.importActual<typeof import("./projectExchangeApi")>(
    "./projectExchangeApi",
  );
  return {
    ...actual,
    createProjectExchange: vi.fn(),
    getProjectExchangePackages: vi.fn(),
    inspectProjectExchange: vi.fn(),
    importProjectExchange: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Source reef project",
  slug: "source-reef-project",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <InteroperabilityWorkspace project={project} />
    </QueryClientProvider>,
  );
}

describe("InteroperabilityWorkspace", () => {
  beforeEach(() => {
    vi.mocked(exchangeApi.getProjectExchangePackages).mockResolvedValue([]);
    vi.mocked(exchangeApi.inspectProjectExchange).mockResolvedValue({
      compatible: true,
      format_name: "reefvision-project-exchange",
      format_version: "1.0",
      application_version: "1.0.0",
      manifest_sha256: "a".repeat(64),
      project_name: "Portable reef",
      section_counts: { images: 3, workflow_graphs: 2 },
      included_media_count: 3,
      warnings: [],
      errors: [],
    });
    vi.mocked(exchangeApi.importProjectExchange).mockResolvedValue({
      project_id: "project-imported",
      project_name: "Portable reef imported",
      project_slug: "portable-reef-imported",
      source_manifest_sha256: "a".repeat(64),
      imported_counts: { images: 3, workflow_graphs: 2 },
      copied_media_count: 3,
      warnings: [],
      package: {
        id: "package-imported",
        project_id: "project-imported",
        job_id: null,
        direction: "import",
        status: "complete",
        format_version: "1.0",
        manifest_json: {},
        manifest_sha256: "a".repeat(64),
        archive_path: "projects/project-imported/exchanges/imported.zip",
        options_json: {},
        error_message: null,
        created_at: "2026-08-18T00:00:00Z",
        completed_at: "2026-08-18T00:00:01Z",
      },
    });
  });

  it("inspects a package and imports it as a new project", async () => {
    const { container } = renderWorkspace();
    const file = new File(["exchange"], "reef.reefvision.zip", {
      type: "application/zip",
    });
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: "Inspect safely" }));
    expect(await screen.findByText("Portable reef")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Imported project name (optional)"), {
      target: { value: "Portable reef imported" },
    });
    const importButton = screen.getByRole("button", {
      name: "Import as new project",
    });
    expect(importButton).toBeEnabled();
    fireEvent.click(importButton);

    await waitFor(() => {
      expect(exchangeApi.importProjectExchange).toHaveBeenCalledWith(
        file,
        "Portable reef imported",
      );
    });
    expect(await screen.findByText("Portable reef imported")).toBeInTheDocument();
    expect(screen.getByText("portable-reef-imported")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });
});
