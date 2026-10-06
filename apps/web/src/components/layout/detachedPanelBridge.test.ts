import { beforeEach, describe, expect, it } from "vitest";

import {
  detachedPanelChannelName,
  detachedPanelUrl,
  detachedPanelWindowLabel,
  parseDetachedPanelRequest,
  readDetachedPanelGeometry,
  saveDetachedPanelGeometry,
} from "./detachedPanelBridge";

describe("detachedPanelBridge", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("creates stable Tauri-safe panel labels and channels", () => {
    expect(detachedPanelWindowLabel("project with spaces?!", "inspector")).toBe(
      "reefvision-panel-inspector-project-with-spaces-",
    );

    expect(detachedPanelChannelName("project-1")).toBe(
      "reefvision.ui.detached-panel.project-1.v1",
    );
  });

  it("creates and parses the detached inspector URL contract", () => {
    const url = detachedPanelUrl("project-1", "inspector", "/index.html");

    expect(url).toContain("/index.html?");
    expect(url).toContain("reefvisionDetachedPanel=inspector");
    expect(url).toContain("projectId=project-1");

    expect(
      parseDetachedPanelRequest(
        "?reefvisionDetachedPanel=inspector&projectId=project-1",
      ),
    ).toEqual({
      panelId: "inspector",
      projectId: "project-1",
    });

    expect(
      parseDetachedPanelRequest(
        "?reefvisionDetachedPanel=unknown&projectId=project-1",
      ),
    ).toBeNull();
  });

  it("persists detached panel geometry for multi-monitor restoration", () => {
    saveDetachedPanelGeometry("project-1", "inspector", {
      x: -1450.4,
      y: 95.2,
      width: 518.8,
      height: 900.6,
    });

    expect(readDetachedPanelGeometry("project-1", "inspector")).toEqual({
      x: -1450,
      y: 95,
      width: 519,
      height: 901,
    });
  });
});
