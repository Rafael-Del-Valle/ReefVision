import { describe, expect, it } from "vitest";

import {
  WORKSPACE_PRESETS,
  workspacePreset,
} from "./workspacePresets";

describe("workspace presets", () => {
  it("exposes every scientist workspace promised by the Phase 12 design", () => {
    expect(WORKSPACE_PRESETS.map((preset) => preset.id)).toEqual([
      "annotation",
      "detection",
      "segmentation",
      "pose",
      "morphometrics",
      "workflow",
      "review",
      "custom",
    ]);
  });

  it("routes presets into existing canonical feature workspaces", () => {
    expect(workspacePreset("annotation").defaultView).toBe("gallery");
    expect(workspacePreset("detection").defaultView).toBe("gallery");
    expect(workspacePreset("segmentation").defaultView).toBe(
      "advanced_providers",
    );
    expect(workspacePreset("pose").defaultView).toBe("video");
    expect(workspacePreset("workflow").defaultView).toBe("workflows");
    expect(workspacePreset("review").defaultView).toBe("review_queue");
  });

  it("falls back safely to annotation for an unknown persisted value", () => {
    expect(workspacePreset("unknown" as never).id).toBe("annotation");
  });
});
