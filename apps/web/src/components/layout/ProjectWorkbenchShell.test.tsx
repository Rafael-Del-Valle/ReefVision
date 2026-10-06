import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import {
  closeDetachedPanelWindow,
  openDetachedPanelWindow,
} from "./detachedPanelBridge";
import { ProjectWorkbenchShell } from "./ProjectWorkbenchShell";

vi.mock("./detachedPanelBridge", async () => {
  const actual = await vi.importActual<typeof import("./detachedPanelBridge")>(
    "./detachedPanelBridge",
  );

  return {
    ...actual,
    openDetachedPanelWindow: vi.fn(),
    closeDetachedPanelWindow: vi.fn(),
  };
});

const project: Project = {
  id: "project-1",
  name: "Fish tracking project",
  slug: "fish-tracking-project",
  description: "Video and pose review",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Fish",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#00aaff",
      is_active: true,
      archived_at: null,
      created_at: "2026-10-01T00:00:00Z",
      updated_at: "2026-10-01T00:00:00Z",
    },
  ],
};

function renderShell() {
  return render(
    <ProjectWorkbenchShell
      project={project}
      navigation={<nav aria-label="Mock project navigation">Navigation</nav>}
      contextTitle="Video & Tracking"
      contextDescription="Review canonical video and pose state."
      activePreset="pose"
      onPresetChange={vi.fn()}
      onHome={vi.fn()}
      onSystem={vi.fn()}
      onArchive={vi.fn()}
      inspector={
        <div data-testid="mock-scientist-inspector">Inspector content</div>
      }
    >
      <div>Central workspace</div>
    </ProjectWorkbenchShell>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();

  vi.mocked(openDetachedPanelWindow).mockResolvedValue({
    ok: true,
  });

  vi.mocked(closeDetachedPanelWindow).mockResolvedValue();
});

afterEach(() => {
  cleanup();
});

describe("ProjectWorkbenchShell detachable panels", () => {
  it("detaches the inspector without changing the central workspace", async () => {
    renderShell();

    expect(screen.getByTestId("mock-scientist-inspector")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Detach inspector",
      }),
    );

    await waitFor(() =>
      expect(openDetachedPanelWindow).toHaveBeenCalledWith({
        projectId: "project-1",
        panelId: "inspector",
        title: "Fish tracking project — ReefVision Inspector",
      }),
    );

    expect(
      screen.queryByLabelText("Workspace inspector"),
    ).not.toBeInTheDocument();

    expect(screen.getByText("Inspector detached")).toBeInTheDocument();

    expect(screen.getByText("Central workspace")).toBeInTheDocument();

    const stored = JSON.parse(
      window.localStorage.getItem(
        "reefvision.ui.workbench-layout.project-1.v1",
      ) ?? "{}",
    ) as {
      inspectorDetached?: boolean;
    };

    expect(stored.inspectorDetached).toBe(true);
  });

  it("docks the detached inspector back into the project workbench", async () => {
    renderShell();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Detach inspector",
      }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Dock inspector",
      }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Dock inspector",
      }),
    );

    await waitFor(() =>
      expect(closeDetachedPanelWindow).toHaveBeenCalledWith(
        "project-1",
        "inspector",
      ),
    );

    expect(screen.getByLabelText("Workspace inspector")).toBeInTheDocument();

    const stored = JSON.parse(
      window.localStorage.getItem(
        "reefvision.ui.workbench-layout.project-1.v1",
      ) ?? "{}",
    ) as {
      inspectorDetached?: boolean;
    };

    expect(stored.inspectorDetached).toBe(false);
  });

  it("restores the saved detached layout for the project", async () => {
    window.localStorage.setItem(
      "reefvision.ui.workbench-layout.project-1.v1",
      JSON.stringify({
        navigationCollapsed: false,
        inspectorCollapsed: false,
        inspectorDetached: true,
      }),
    );

    renderShell();

    await waitFor(() =>
      expect(openDetachedPanelWindow).toHaveBeenCalledWith({
        projectId: "project-1",
        panelId: "inspector",
        title: "Fish tracking project — ReefVision Inspector",
      }),
    );

    expect(
      screen.queryByLabelText("Workspace inspector"),
    ).not.toBeInTheDocument();

    expect(screen.getByText("Inspector detached")).toBeInTheDocument();
  });
});
