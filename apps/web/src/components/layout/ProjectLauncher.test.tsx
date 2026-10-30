import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectSummary } from "../../api/client";
import { ProjectLauncher } from "./ProjectLauncher";

const project: ProjectSummary = {
  id: "project-1",
  name: "Mesophotic Coral Study",
  slug: "mesophotic-coral-study",
  description: "Scientist-reviewed octocoral imagery",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-05T00:00:00Z",
  archived_at: null,
  label_class_count: 6,
  active_label_class_count: 6,
};

function renderLauncher(
  projects: ProjectSummary[] = [project],
  projectsState: "pending" | "ready" | "error" = "ready",
) {
  const handlers = {
    onRetryProjects: vi.fn(),
    onCreateProject: vi.fn(),
    onQuickStart: vi.fn(),
    onOpenProject: vi.fn(),
    onImportPackage: vi.fn(),
    onOpenSystem: vi.fn(),
    onOpenOnboarding: vi.fn(),
  };

  render(
    <ProjectLauncher
      projects={projects}
      projectsState={projectsState}
      version="1.0.5"
      serviceState="ready"
      {...handlers}
    />,
  );

  return handlers;
}

describe("ProjectLauncher", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("opens a recent project from the scientist launcher", async () => {
    const handlers = renderLauncher();

    await userEvent.click(
      screen.getByRole("button", { name: "Open Mesophotic Coral Study" }),
    );

    expect(handlers.onOpenProject).toHaveBeenCalledWith("project-1");
    expect(screen.getByText("Local / offline-capable")).toBeInTheDocument();
  });

  it("persists pinned projects locally without changing project data", async () => {
    renderLauncher();

    await userEvent.click(screen.getByRole("button", { name: "Pin" }));

    expect(
      window.localStorage.getItem("reefvision.ui.pinned-projects.v1"),
    ).toContain("project-1");
    expect(screen.getByRole("button", { name: "Unpin" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("offers only blank scientific quick-start paths", async () => {
    const handlers = renderLauncher();

    await userEvent.click(
      screen.getByRole("button", { name: /General image analysis/ }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Video \+ pose study/ }),
    );

    expect(handlers.onQuickStart).toHaveBeenNthCalledWith(1, "blank");
    expect(handlers.onQuickStart).toHaveBeenNthCalledWith(2, "blank");
    expect(screen.queryByText(/six-class octocoral/i)).not.toBeInTheDocument();
  });

  it("does not mistake pending project summaries for an empty installation", () => {
    renderLauncher([], "pending");

    expect(
      screen.getByRole("heading", { name: "Loading local projects" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Loading projects")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "No projects yet" }),
    ).not.toBeInTheDocument();
  });

  it("shows a read-only retry instead of claiming lost projects on API failure", async () => {
    const handlers = renderLauncher([], "error");

    expect(
      screen.getByRole("heading", {
        name: "Local projects could not be loaded",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Project list unavailable")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "No projects yet" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(handlers.onRetryProjects).toHaveBeenCalledTimes(1);
    expect(handlers.onCreateProject).not.toHaveBeenCalled();
    expect(handlers.onOpenProject).not.toHaveBeenCalled();
  });

  it("allows project import on a fresh installation", async () => {
    const handlers = renderLauncher([]);

    const importButtons = screen.getAllByRole("button", {
      name: /Import (project|existing project)/,
    });

    expect(importButtons.length).toBeGreaterThan(0);
    expect(importButtons[0]).toBeEnabled();

    await userEvent.click(importButtons[0]);

    expect(handlers.onImportPackage).toHaveBeenCalled();
    expect(
      screen.getByRole("heading", { name: "No projects yet" }),
    ).toBeInTheDocument();
  });

  it("keeps projects beyond the twelve-card preview accessible without creating data", async () => {
    const manyProjects = Array.from({ length: 13 }, (_, index) => ({
      ...project,
      id: `project-${index + 1}`,
      name: index === 12 ? "Historical Survey" : `Coral Study ${index + 1}`,
      description: index === 12 ? "Deep Sea Transects" : "Recent coral imagery",
      updated_at: new Date(Date.UTC(2026, 9, 31 - index)).toISOString(),
    }));
    const handlers = renderLauncher(manyProjects);

    expect(
      screen.queryByRole("button", { name: "Open Historical Survey" }),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Show all 13 matching projects" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Open Historical Survey" }),
    );

    expect(handlers.onOpenProject).toHaveBeenCalledWith("project-13");
    expect(handlers.onCreateProject).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Show fewer projects" }),
    ).toBeInTheDocument();
  });

  it("finds older projects by name or description without changing saved records", async () => {
    const manyProjects = Array.from({ length: 13 }, (_, index) => ({
      ...project,
      id: `project-${index + 1}`,
      name: index === 12 ? "Historical Survey" : `Coral Study ${index + 1}`,
      description: index === 12 ? "Deep Sea Transects" : "Recent coral imagery",
      updated_at: new Date(Date.UTC(2026, 9, 31 - index)).toISOString(),
    }));
    const handlers = renderLauncher(manyProjects);
    const search = screen.getByRole("searchbox", {
      name: "Find a saved project",
    });

    await userEvent.type(search, "dEEP sEA");
    expect(
      screen.getByRole("button", { name: "Open Historical Survey" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open Coral Study 1" }),
    ).not.toBeInTheDocument();

    await userEvent.clear(search);
    await userEvent.type(search, "historical");
    expect(
      screen.getByRole("button", { name: "Open Historical Survey" }),
    ).toBeInTheDocument();
    expect(handlers.onCreateProject).not.toHaveBeenCalled();
    expect(handlers.onOpenProject).not.toHaveBeenCalled();
  });

  it("distinguishes an unmatched search from an empty project collection", async () => {
    const handlers = renderLauncher();
    await userEvent.type(
      screen.getByRole("searchbox", { name: "Find a saved project" }),
      "not-a-saved-study",
    );

    expect(
      screen.getByRole("heading", { name: "No matching projects" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "No projects yet" }),
    ).not.toBeInTheDocument();
    expect(handlers.onCreateProject).not.toHaveBeenCalled();
  });
});
