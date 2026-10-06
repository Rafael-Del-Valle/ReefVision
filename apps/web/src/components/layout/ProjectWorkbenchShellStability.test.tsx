import { cleanup, render, waitFor } from "@testing-library/react";
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
  id: "phase12e-project",
  name: "Phase 12E project",
  slug: "phase12e-project",
  description: "UI acceptance",
  storage_root: "projects/phase12e-project",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-05T00:00:00Z",
  updated_at: "2026-10-05T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

function shell(inspectorLabel: string) {
  return (
    <ProjectWorkbenchShell
      project={project}
      navigation={<nav>Navigation</nav>}
      contextTitle="Gallery"
      contextDescription="Image review"
      activePreset="annotation"
      onPresetChange={vi.fn()}
      onHome={vi.fn()}
      onSystem={vi.fn()}
      onArchive={vi.fn()}
      inspector={<div data-testid="inspector-content">{inspectorLabel}</div>}
    >
      <div>Central scientific workspace</div>
    </ProjectWorkbenchShell>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();

  window.localStorage.setItem(
    "reefvision.ui.workbench-layout.phase12e-project.v1",
    JSON.stringify({
      navigationCollapsed: false,
      inspectorCollapsed: false,
      inspectorDetached: true,
    }),
  );

  vi.mocked(openDetachedPanelWindow).mockResolvedValue({
    ok: true,
  });

  vi.mocked(closeDetachedPanelWindow).mockResolvedValue();
});

afterEach(() => {
  cleanup();
});

describe("ProjectWorkbenchShell detached-panel stability", () => {
  it("does not close and reopen a detached native window when inspector content rerenders", async () => {
    const view = render(shell("Initial inspector"));

    await waitFor(() =>
      expect(openDetachedPanelWindow).toHaveBeenCalledTimes(1),
    );

    view.rerender(shell("Updated live inspector"));

    await Promise.resolve();

    expect(openDetachedPanelWindow).toHaveBeenCalledTimes(1);

    expect(closeDetachedPanelWindow).not.toHaveBeenCalled();
  });
});
