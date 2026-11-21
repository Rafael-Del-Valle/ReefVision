import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import {
  closeDetachedPanelWindow,
  openDetachedPanelWindow,
} from "./detachedPanelBridge";
import { ProjectWorkbenchShell } from "./ProjectWorkbenchShell";
import { ScientistWorkspaceInspector } from "./ScientistWorkspaceInspector";

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

it("reorders and hides contextual panels, restores defaults, and preserves an open draft", async () => {
  function shell() {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <ProjectWorkbenchShell
          project={project}
          navigation={<nav>Navigation</nav>}
          contextTitle="Models"
          contextDescription="Review registered models."
          activePreset="annotation"
          activeInspectorView="models"
          onPresetChange={vi.fn()}
          onHome={vi.fn()}
          onSystem={vi.fn()}
          onArchive={vi.fn()}
          inspector={
            <ScientistWorkspaceInspector
              activeView="models"
              activePreset="annotation"
              activeClassCount={1}
              annotationType="bbox"
              projectId={project.id}
              onNavigate={vi.fn()}
            />
          }
        >
          <label>
            Unsaved workflow name
            <input defaultValue="" />
          </label>
        </ProjectWorkbenchShell>
      </QueryClientProvider>,
    );
  }

  function panelNames() {
    return Array.from(
      screen
        .getByRole("complementary", { name: "Workspace inspector" })
        .querySelectorAll("[data-contextual-panel]"),
      (panel) => panel.getAttribute("data-contextual-panel"),
    );
  }

  const view = shell();
  const draft = screen.getByRole("textbox", { name: "Unsaved workflow name" });
  await userEvent.type(draft, "Uncommitted graph edit");
  await userEvent.click(screen.getByRole("button", { name: "Panels" }));
  expect(panelNames().slice(0, 2)).toEqual([
    "workflow-context",
    "truth-boundary",
  ]);
  await userEvent.click(
    screen.getByRole("button", { name: "Move Scientific truth boundary up" }),
  );
  expect(panelNames().slice(0, 2)).toEqual([
    "truth-boundary",
    "workflow-context",
  ]);
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Show Related workspaces" }),
  );
  expect(panelNames()).not.toContain("related-workspaces");
  await userEvent.click(screen.getByRole("button", { name: "Reset layout" }));
  expect(panelNames().slice(0, 2)).toEqual([
    "workflow-context",
    "truth-boundary",
  ]);
  expect(panelNames()).toContain("related-workspaces");
  expect(draft).toBe(
    screen.getByRole("textbox", { name: "Unsaved workflow name" }),
  );
  expect(draft).toHaveValue("Uncommitted graph edit");

  await userEvent.click(
    screen.getByRole("checkbox", { name: "Show Related workspaces" }),
  );
  view.unmount();
  shell();
  expect(panelNames()).not.toContain("related-workspaces");
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
