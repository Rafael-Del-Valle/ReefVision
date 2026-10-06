import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DetachedInspectorSnapshot } from "./detachedPanelBridge";
import { DetachedInspectorSurface } from "./DetachedInspectorWindow";

const snapshot: DetachedInspectorSnapshot = {
  projectId: "project-1",
  projectName: "Jellyfish behavior",
  contextTitle: "Classes",
  contextDescription: "Manage stable project classes.",
  activeView: "classes",
  activePreset: "annotation",
  activeClassCount: 4,
  annotationType: "bbox",
  inferenceSelectedImageIds: [],
  focusedImageId: null,
  selectedReviewQueueId: null,
  videoWorkspaceContext: null,
};

afterEach(() => {
  cleanup();
});

describe("DetachedInspectorSurface", () => {
  it("renders the canonical scientist inspector in a detached shell", () => {
    render(
      <DetachedInspectorSurface
        snapshot={snapshot}
        onCommand={vi.fn()}
        onDock={vi.fn()}
      />,
    );

    expect(screen.getByText("Detached scientist panel")).toBeInTheDocument();

    expect(screen.getByText("Jellyfish behavior")).toBeInTheDocument();

    expect(screen.getByText("Presentation-only panel")).toBeInTheDocument();

    expect(
      screen.getByLabelText("Scientific truth boundary"),
    ).toBeInTheDocument();

    expect(screen.getByText("Canonical workspace")).toBeInTheDocument();
  });

  it("requests docking without mutating scientific state", async () => {
    const onDock = vi.fn();

    render(
      <DetachedInspectorSurface
        snapshot={snapshot}
        onCommand={vi.fn()}
        onDock={onDock}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", {
        name: "Dock inspector",
      }),
    );

    expect(onDock).toHaveBeenCalledTimes(1);
  });
});
