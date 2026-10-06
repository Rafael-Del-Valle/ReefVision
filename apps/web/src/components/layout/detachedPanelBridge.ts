import type { ReviewQueueItem } from "../../api/client";
import type { VideoWorkspaceContext } from "../../features/video/videoWorkspaceBridge";
import type { WorkspaceInspectorView } from "./workspaceInspector";
import type { WorkspacePresetId } from "./workspacePresets";

export type DetachablePanelId = "inspector";

export interface DetachedPanelRequest {
  panelId: DetachablePanelId;
  projectId: string;
}

export interface DetachedPanelGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DetachedInspectorSnapshot {
  projectId: string;
  projectName: string;
  contextTitle: string;
  contextDescription: string;

  activeView: WorkspaceInspectorView;
  activePreset: WorkspacePresetId;

  activeClassCount: number;
  annotationType: string;

  inferenceSelectedImageIds: string[];
  focusedImageId: string | null;
  selectedReviewQueueId: string | null;
  videoWorkspaceContext: VideoWorkspaceContext | null;
}

export type DetachedInspectorCommand =
  | {
      type: "navigate";
      view: WorkspaceInspectorView;
    }
  | {
      type: "open_measurements";
      imageId: string;
    }
  | {
      type: "open_review_item";
      item: ReviewQueueItem;
    }
  | {
      type: "video_select";
      videoId: string;
    }
  | {
      type: "video_frame";
      frameIndex: number;
    }
  | {
      type: "video_track";
      trackId: string;
    }
  | {
      type: "dock";
    };

export type DetachedInspectorMessage =
  | {
      kind: "ready";
      projectId: string;
    }
  | {
      kind: "snapshot";
      projectId: string;
      snapshot: DetachedInspectorSnapshot;
    }
  | {
      kind: "command";
      projectId: string;
      command: DetachedInspectorCommand;
    };

export interface DetachedPanelOpenResult {
  ok: boolean;
  error?: string;
}

const browserWindows = new Map<string, Window>();

function safeLabelPart(value: string): string {
  const sanitized = value
    .replace(/[^a-zA-Z0-9\-/:_]/g, "-")
    .replace(/-+/g, "-");

  return sanitized.length > 0 ? sanitized.slice(0, 80) : "project";
}

function geometryStorageKey(
  projectId: string,
  panelId: DetachablePanelId,
): string {
  return `reefvision.ui.detached-panel.${projectId}.${panelId}.geometry.v1`;
}

export function detachedPanelChannelName(projectId: string): string {
  return `reefvision.ui.detached-panel.${projectId}.v1`;
}

export function detachedPanelWindowLabel(
  projectId: string,
  panelId: DetachablePanelId,
): string {
  return `reefvision-panel-${panelId}-${safeLabelPart(projectId)}`;
}

export function detachedPanelUrl(
  projectId: string,
  panelId: DetachablePanelId,
  pathname = typeof window === "undefined"
    ? "/"
    : window.location.pathname || "/",
): string {
  const parameters = new URLSearchParams({
    reefvisionDetachedPanel: panelId,
    projectId,
  });

  return `${pathname || "/"}?${parameters.toString()}`;
}

export function parseDetachedPanelRequest(
  search: string,
): DetachedPanelRequest | null {
  const parameters = new URLSearchParams(search);
  const panelId = parameters.get("reefvisionDetachedPanel");
  const projectId = parameters.get("projectId")?.trim() ?? "";

  if (panelId !== "inspector" || projectId.length === 0) {
    return null;
  }

  return {
    panelId,
    projectId,
  };
}

export function isDetachedInspectorMessage(
  value: unknown,
): value is DetachedInspectorMessage {
  if (!value || typeof value !== "object") {
    return false;
  }

  const message = value as Partial<DetachedInspectorMessage>;

  return (
    typeof message.kind === "string" &&
    typeof message.projectId === "string" &&
    ["ready", "snapshot", "command"].includes(message.kind)
  );
}

export function isDesktopRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function readDetachedPanelGeometry(
  projectId: string,
  panelId: DetachablePanelId,
): DetachedPanelGeometry | null {
  try {
    const raw = window.localStorage.getItem(
      geometryStorageKey(projectId, panelId),
    );

    if (!raw) {
      return null;
    }

    const value = JSON.parse(raw) as Partial<DetachedPanelGeometry>;

    if (
      !Number.isFinite(value.x) ||
      !Number.isFinite(value.y) ||
      !Number.isFinite(value.width) ||
      !Number.isFinite(value.height)
    ) {
      return null;
    }

    if ((value.width as number) < 320 || (value.height as number) < 420) {
      return null;
    }

    return {
      x: value.x as number,
      y: value.y as number,
      width: value.width as number,
      height: value.height as number,
    };
  } catch {
    return null;
  }
}

export function saveDetachedPanelGeometry(
  projectId: string,
  panelId: DetachablePanelId,
  geometry: DetachedPanelGeometry,
): void {
  if (
    !Number.isFinite(geometry.x) ||
    !Number.isFinite(geometry.y) ||
    !Number.isFinite(geometry.width) ||
    !Number.isFinite(geometry.height)
  ) {
    return;
  }

  window.localStorage.setItem(
    geometryStorageKey(projectId, panelId),
    JSON.stringify({
      x: Math.round(geometry.x),
      y: Math.round(geometry.y),
      width: Math.max(320, Math.round(geometry.width)),
      height: Math.max(420, Math.round(geometry.height)),
    }),
  );
}

export async function openDetachedPanelWindow({
  projectId,
  panelId,
  title,
}: {
  projectId: string;
  panelId: DetachablePanelId;
  title: string;
}): Promise<DetachedPanelOpenResult> {
  const label = detachedPanelWindowLabel(projectId, panelId);
  const url = detachedPanelUrl(projectId, panelId);
  const geometry = readDetachedPanelGeometry(projectId, panelId);

  if (isDesktopRuntime()) {
    try {
      const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");

      const existing = await WebviewWindow.getByLabel(label);

      if (existing) {
        return { ok: true };
      }

      const options = {
        url,
        title,
        width: geometry?.width ?? 420,
        height: geometry?.height ?? 860,
        minWidth: 340,
        minHeight: 520,
        resizable: true,
        ...(geometry
          ? {
              x: geometry.x,
              y: geometry.y,
            }
          : {}),
      };

      const child = new WebviewWindow(label, options);

      return await new Promise<DetachedPanelOpenResult>((resolve) => {
        let settled = false;

        const finish = (result: DetachedPanelOpenResult) => {
          if (settled) {
            return;
          }

          settled = true;
          resolve(result);
        };

        void child
          .once("tauri://created", () => {
            finish({ ok: true });
          })
          .catch((error: unknown) => {
            finish({
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            });
          });

        void child
          .once("tauri://error", (event) => {
            finish({
              ok: false,
              error:
                typeof event.payload === "string"
                  ? event.payload
                  : "Tauri could not create the detached panel window.",
            });
          })
          .catch((error: unknown) => {
            finish({
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            });
          });

        window.setTimeout(() => {
          finish({ ok: true });
        }, 1500);
      });
    } catch (error) {
      return {
        ok: false,
        error:
          error instanceof Error
            ? error.message
            : "Unable to create detached desktop panel.",
      };
    }
  }

  const features = [
    "popup=yes",
    `width=${geometry?.width ?? 420}`,
    `height=${geometry?.height ?? 860}`,
    "resizable=yes",
    "scrollbars=yes",
    ...(geometry ? [`left=${geometry.x}`, `top=${geometry.y}`] : []),
  ].join(",");

  const popup = window.open(url, label, features);

  if (!popup) {
    return {
      ok: false,
      error: "The browser blocked the detached inspector window.",
    };
  }

  browserWindows.set(label, popup);

  return { ok: true };
}

export async function closeDetachedPanelWindow(
  projectId: string,
  panelId: DetachablePanelId,
): Promise<void> {
  const label = detachedPanelWindowLabel(projectId, panelId);

  if (isDesktopRuntime()) {
    try {
      const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");

      const existing = await WebviewWindow.getByLabel(label);

      if (existing) {
        await existing.close();
      }
    } catch {
      // The panel may already have been closed by the user.
    }

    return;
  }

  const popup = browserWindows.get(label);

  if (popup && !popup.closed) {
    popup.close();
  }

  browserWindows.delete(label);
}

export async function closeCurrentDetachedPanelWindow(): Promise<void> {
  if (isDesktopRuntime()) {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");

    await getCurrentWindow().close();
    return;
  }

  window.close();
}
