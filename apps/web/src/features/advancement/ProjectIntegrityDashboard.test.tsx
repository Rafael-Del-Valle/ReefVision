import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { inspectProjectIntegrity } from "./api";
import { ProjectIntegrityDashboard } from "./ProjectIntegrityDashboard";

vi.mock("./api", () => ({
  inspectProjectIntegrity: vi.fn(),
}));

const project: Project = {
  id: "project-1",
  name: "Integrity project",
  slug: "integrity-project",
  description: "Project integrity test",
  storage_root: "projects/integrity-project",
  default_annotation_type: "bounding_box",
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectIntegrityDashboard project={project} />
    </QueryClientProvider>,
  );
}

describe("ProjectIntegrityDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(inspectProjectIntegrity).mockResolvedValue({
      project_id: project.id,
      project_name: project.name,
      checked_at: "2026-07-18T12:00:00Z",
      verify_checksums: true,
      stale_job_minutes: 60,
      valid: false,
      error_count: 1,
      warning_count: 1,
      total_referenced_files: 3,
      existing_referenced_files: 2,
      missing_referenced_files: 1,
      total_existing_bytes: 2048,
      categories: [
        {
          resource_kind: "image",
          record_count: 2,
          referenced_file_count: 2,
          existing_file_count: 1,
          missing_file_count: 1,
          total_existing_bytes: 2048,
          checksum_verified_count: 1,
          checksum_mismatch_count: 0,
        },
      ],
      issues: [
        {
          severity: "error",
          code: "managed_path_missing",
          resource_kind: "image",
          record_id: "image-2",
          managed_path: "projects/integrity-project/images/missing.png",
          message: "The managed image is missing.",
          repairable: false,
        },
        {
          severity: "warning",
          code: "stale_active_job",
          resource_kind: "job",
          record_id: "job-1",
          managed_path: null,
          message: "A training job is stale.",
          repairable: true,
        },
      ],
    });
  });

  it("runs a checksum-aware inspection and renders findings", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(
      screen.getByLabelText(/verify image, video, and model sha-256/i),
    );
    await user.click(screen.getByRole("button", { name: /inspect project/i }));

    await waitFor(() =>
      expect(inspectProjectIntegrity).toHaveBeenCalledWith(
        project.id,
        true,
        60,
      ),
    );
    expect(await screen.findByText("Attention required")).toBeInTheDocument();
    expect(screen.getByText(/managed path missing/i)).toBeInTheDocument();
    expect(screen.getByText(/stale active job/i)).toBeInTheDocument();
    expect(screen.getByText("1 missing")).toBeInTheDocument();
  });
});
