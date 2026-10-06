import { useEffect, useRef, useState } from "react";

import { ScientistWorkspaceInspector } from "./ScientistWorkspaceInspector";
import {
  closeCurrentDetachedPanelWindow,
  detachedPanelChannelName,
  isDesktopRuntime,
  isDetachedInspectorMessage,
  saveDetachedPanelGeometry,
  type DetachedInspectorCommand,
  type DetachedInspectorMessage,
  type DetachedInspectorSnapshot,
} from "./detachedPanelBridge";

export function DetachedInspectorSurface({
  snapshot,
  onCommand,
  onDock,
}: {
  snapshot: DetachedInspectorSnapshot;
  onCommand: (command: DetachedInspectorCommand) => void;
  onDock: () => void;
}) {
  return (
    <main className="rv-detached-inspector-window">
      <header className="rv-detached-inspector-toolbar">
        <div>
          <p className="eyebrow">Detached scientist panel</p>
          <strong>{snapshot.contextTitle}</strong>
          <span>{snapshot.projectName}</span>
        </div>

        <button type="button" className="secondary" onClick={onDock}>
          Dock inspector
        </button>
      </header>

      <div className="rv-detached-inspector-status">
        <strong>Presentation-only panel</strong>
        <span>
          Scientific records remain owned by ReefVision's canonical project
          workspaces and backend.
        </span>
      </div>

      <section className="rv-detached-inspector-content">
        <ScientistWorkspaceInspector
          activeView={snapshot.activeView}
          activePreset={snapshot.activePreset}
          activeClassCount={snapshot.activeClassCount}
          annotationType={snapshot.annotationType}
          projectId={snapshot.projectId}
          inferenceSelectedImageIds={snapshot.inferenceSelectedImageIds}
          focusedImageId={snapshot.focusedImageId}
          selectedReviewQueueId={snapshot.selectedReviewQueueId}
          videoWorkspaceContext={snapshot.videoWorkspaceContext}
          onOpenMeasurements={(imageId) =>
            onCommand({
              type: "open_measurements",
              imageId,
            })
          }
          onOpenReviewItem={(item) =>
            onCommand({
              type: "open_review_item",
              item,
            })
          }
          onVideoSelect={(videoId) =>
            onCommand({
              type: "video_select",
              videoId,
            })
          }
          onVideoFrameChange={(frameIndex) =>
            onCommand({
              type: "video_frame",
              frameIndex,
            })
          }
          onVideoTrackChange={(trackId) =>
            onCommand({
              type: "video_track",
              trackId,
            })
          }
          onNavigate={(view) =>
            onCommand({
              type: "navigate",
              view,
            })
          }
        />
      </section>
    </main>
  );
}

export function DetachedInspectorWindow({ projectId }: { projectId: string }) {
  const channelRef = useRef<BroadcastChannel | null>(null);
  const [snapshot, setSnapshot] = useState<DetachedInspectorSnapshot | null>(
    null,
  );
  const [connectionError, setConnectionError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") {
      setConnectionError(
        "This runtime does not support the detached-panel communication channel.",
      );
      return;
    }

    const channel = new BroadcastChannel(detachedPanelChannelName(projectId));

    channelRef.current = channel;

    const receive = (event: MessageEvent<unknown>) => {
      if (!isDetachedInspectorMessage(event.data)) {
        return;
      }

      if (event.data.projectId !== projectId) {
        return;
      }

      if (event.data.kind === "snapshot") {
        setSnapshot(event.data.snapshot);
        setConnectionError(null);
      }
    };

    channel.addEventListener("message", receive);

    const readyMessage: DetachedInspectorMessage = {
      kind: "ready",
      projectId,
    };

    channel.postMessage(readyMessage);

    return () => {
      channel.removeEventListener("message", receive);
      channel.close();

      if (channelRef.current === channel) {
        channelRef.current = null;
      }
    };
  }, [projectId]);

  useEffect(() => {
    const sendDock = () => {
      const channel = channelRef.current;

      if (!channel) {
        return;
      }

      const message: DetachedInspectorMessage = {
        kind: "command",
        projectId,
        command: {
          type: "dock",
        },
      };

      channel.postMessage(message);
    };

    if (!isDesktopRuntime()) {
      const saveBrowserGeometry = () => {
        saveDetachedPanelGeometry(projectId, "inspector", {
          x: window.screenX,
          y: window.screenY,
          width: window.outerWidth,
          height: window.outerHeight,
        });
      };

      const handleBeforeUnload = () => {
        saveBrowserGeometry();
        sendDock();
      };

      window.addEventListener("resize", saveBrowserGeometry);
      window.addEventListener("beforeunload", handleBeforeUnload);

      return () => {
        window.removeEventListener("resize", saveBrowserGeometry);
        window.removeEventListener("beforeunload", handleBeforeUnload);
      };
    }

    let disposed = false;
    const unlisten: Array<() => void> = [];

    void import("@tauri-apps/api/window")
      .then(async ({ getCurrentWindow }) => {
        const current = getCurrentWindow();

        const saveNativeGeometry = async () => {
          try {
            const [position, size, scaleFactor] = await Promise.all([
              current.outerPosition(),
              current.outerSize(),
              current.scaleFactor(),
            ]);

            saveDetachedPanelGeometry(projectId, "inspector", {
              x: position.x / scaleFactor,
              y: position.y / scaleFactor,
              width: size.width / scaleFactor,
              height: size.height / scaleFactor,
            });
          } catch {
            // Geometry persistence must never block panel use.
          }
        };

        const moved = await current.onMoved(() => {
          void saveNativeGeometry();
        });

        if (disposed) {
          moved();
        } else {
          unlisten.push(moved);
        }

        const resized = await current.onResized(() => {
          void saveNativeGeometry();
        });

        if (disposed) {
          resized();
        } else {
          unlisten.push(resized);
        }

        const closing = await current.onCloseRequested(() => {
          sendDock();
          void saveNativeGeometry();
        });

        if (disposed) {
          closing();
        } else {
          unlisten.push(closing);
        }

        await saveNativeGeometry();
      })
      .catch(() => {
        // Native geometry listeners are an enhancement only.
      });

    return () => {
      disposed = true;

      for (const dispose of unlisten) {
        dispose();
      }
    };
  }, [projectId]);

  function sendCommand(command: DetachedInspectorCommand): void {
    const channel = channelRef.current;

    if (!channel) {
      setConnectionError("The main ReefVision workspace is not connected.");
      return;
    }

    const message: DetachedInspectorMessage = {
      kind: "command",
      projectId,
      command,
    };

    channel.postMessage(message);
  }

  async function dockInspector(): Promise<void> {
    sendCommand({
      type: "dock",
    });

    try {
      await closeCurrentDetachedPanelWindow();
    } catch (error) {
      setConnectionError(
        error instanceof Error
          ? error.message
          : "Unable to close the detached panel.",
      );
    }
  }

  if (connectionError && !snapshot) {
    return (
      <main className="rv-detached-inspector-window">
        <div className="rv-detached-panel-state" role="alert">
          <strong>Detached inspector unavailable</strong>
          <p>{connectionError}</p>

          <button
            type="button"
            className="secondary"
            onClick={() => void dockInspector()}
          >
            Close panel
          </button>
        </div>
      </main>
    );
  }

  if (!snapshot) {
    return (
      <main className="rv-detached-inspector-window">
        <div className="rv-detached-panel-state">
          <strong>Connecting to project workspace…</strong>
          <p>
            Waiting for the main ReefVision window to publish the current
            scientist-inspector context.
          </p>
        </div>
      </main>
    );
  }

  return (
    <>
      {connectionError && (
        <div className="rv-detached-panel-error" role="alert">
          {connectionError}
        </div>
      )}

      <DetachedInspectorSurface
        snapshot={snapshot}
        onCommand={sendCommand}
        onDock={() => void dockInspector()}
      />
    </>
  );
}
