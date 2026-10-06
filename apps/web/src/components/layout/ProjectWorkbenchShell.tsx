import { useEffect, useState, type ReactNode } from "react";

import type { Project } from "../../api/client";
import {
  closeDetachedPanelWindow,
  detachedPanelChannelName,
  isDetachedInspectorMessage,
  openDetachedPanelWindow,
} from "./detachedPanelBridge";
import {
  WORKSPACE_PRESETS,
  workspacePreset,
  type WorkspacePresetId,
} from "./workspacePresets";

interface WorkbenchLayoutPreferences {
  navigationCollapsed: boolean;
  inspectorCollapsed: boolean;
  inspectorDetached: boolean;
}

function layoutStorageKey(projectId: string): string {
  return `reefvision.ui.workbench-layout.${projectId}.v1`;
}

function readLayoutPreferences(projectId: string): WorkbenchLayoutPreferences {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(layoutStorageKey(projectId)) ?? "{}",
    ) as Partial<WorkbenchLayoutPreferences>;

    return {
      navigationCollapsed: parsed.navigationCollapsed === true,
      inspectorCollapsed: parsed.inspectorCollapsed === true,
      inspectorDetached: parsed.inspectorDetached === true,
    };
  } catch {
    return {
      navigationCollapsed: false,
      inspectorCollapsed: false,
      inspectorDetached: false,
    };
  }
}

function persistLayoutPreferences(
  projectId: string,
  layout: WorkbenchLayoutPreferences,
): void {
  window.localStorage.setItem(
    layoutStorageKey(projectId),
    JSON.stringify(layout),
  );
}

export function ProjectWorkbenchShell({
  project,
  navigation,
  contextTitle,
  contextDescription,
  activePreset,
  onPresetChange,
  onHome,
  onSystem,
  onArchive,
  children,
  inspector,
}: {
  project: Project;
  navigation: ReactNode;
  contextTitle: string;
  contextDescription: string;
  activePreset: WorkspacePresetId;
  onPresetChange: (presetId: WorkspacePresetId) => void;
  onHome: () => void;
  onSystem: () => void;
  onArchive: () => void;
  children: ReactNode;
  inspector?: ReactNode;
}) {
  const [layout, setLayout] = useState<WorkbenchLayoutPreferences>(() =>
    readLayoutPreferences(project.id),
  );

  const [panelBusy, setPanelBusy] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  function patchLayout(patch: Partial<WorkbenchLayoutPreferences>): void {
    setLayout((current) => {
      const next = {
        ...current,
        ...patch,
      };

      persistLayoutPreferences(project.id, next);

      return next;
    });
  }

  useEffect(() => {
    const next = readLayoutPreferences(project.id);

    setLayout(next);
    setPanelError(null);

    if (next.inspectorDetached && inspector) {
      void openDetachedPanelWindow({
        projectId: project.id,
        panelId: "inspector",
        title: `${project.name} — ReefVision Inspector`,
      }).then((result) => {
        if (result.ok) {
          return;
        }

        const fallback = {
          ...next,
          inspectorDetached: false,
        };

        setLayout(fallback);
        persistLayoutPreferences(project.id, fallback);

        setPanelError(
          result.error ?? "The detached inspector could not be restored.",
        );
      });
    }

    return () => {
      void closeDetachedPanelWindow(project.id, "inspector");
    };
  }, [project.id, project.name, inspector]);

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") {
      return;
    }

    const channel = new BroadcastChannel(detachedPanelChannelName(project.id));

    const receive = (event: MessageEvent<unknown>) => {
      if (!isDetachedInspectorMessage(event.data)) {
        return;
      }

      if (
        event.data.projectId !== project.id ||
        event.data.kind !== "command" ||
        event.data.command.type !== "dock"
      ) {
        return;
      }

      patchLayout({
        inspectorCollapsed: false,
        inspectorDetached: false,
      });
    };

    channel.addEventListener("message", receive);

    return () => {
      channel.removeEventListener("message", receive);
      channel.close();
    };
  }, [project.id]);

  async function detachInspector(): Promise<void> {
    if (!inspector || panelBusy) {
      return;
    }

    setPanelBusy(true);
    setPanelError(null);

    try {
      const result = await openDetachedPanelWindow({
        projectId: project.id,
        panelId: "inspector",
        title: `${project.name} — ReefVision Inspector`,
      });

      if (!result.ok) {
        setPanelError(
          result.error ?? "The detached inspector could not be opened.",
        );
        return;
      }

      patchLayout({
        inspectorCollapsed: false,
        inspectorDetached: true,
      });
    } finally {
      setPanelBusy(false);
    }
  }

  async function dockInspector(): Promise<void> {
    if (panelBusy) {
      return;
    }

    setPanelBusy(true);
    setPanelError(null);

    try {
      await closeDetachedPanelWindow(project.id, "inspector");

      patchLayout({
        inspectorCollapsed: false,
        inspectorDetached: false,
      });
    } catch (error) {
      setPanelError(
        error instanceof Error
          ? error.message
          : "The detached inspector could not be docked.",
      );
    } finally {
      setPanelBusy(false);
    }
  }

  const preset = workspacePreset(activePreset);

  return (
    <section
      className={[
        "rv-project-workbench",
        layout.navigationCollapsed ? "navigation-collapsed" : "",
        layout.inspectorCollapsed ? "inspector-collapsed" : "",
        layout.inspectorDetached ? "inspector-detached" : "",
        activePreset === "review" ? "review-mode" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <aside
        className="rv-workbench-rail"
        aria-label="Project workspace navigation"
      >
        {layout.navigationCollapsed ? (
          <div className="rv-collapsed-rail">
            <button
              type="button"
              className="rv-home-button"
              onClick={onHome}
              aria-label="Back to ReefVision home"
            >
              <span aria-hidden="true">RV</span>
            </button>

            <button
              type="button"
              className="secondary"
              aria-label="Show project navigation"
              title="Show navigation"
              onClick={() =>
                patchLayout({
                  navigationCollapsed: false,
                })
              }
            >
              ☰
            </button>
          </div>
        ) : (
          <>
            <div className="rv-workbench-project">
              <button
                type="button"
                className="rv-home-button"
                onClick={onHome}
                aria-label="Back to ReefVision home"
              >
                <span aria-hidden="true">RV</span>
              </button>

              <div>
                <p className="eyebrow">Open project</p>
                <h2 title={project.name}>{project.name}</h2>
                <p>{project.description || "No project description."}</p>
              </div>
            </div>

            <div className="rv-preset-picker">
              <label>
                Workspace preset
                <select
                  value={activePreset}
                  onChange={(event) =>
                    onPresetChange(event.target.value as WorkspacePresetId)
                  }
                >
                  {WORKSPACE_PRESETS.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <small>{preset.description}</small>
            </div>

            {navigation}

            <div className="rv-workbench-rail-footer">
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  patchLayout({
                    navigationCollapsed: true,
                  })
                }
              >
                Collapse navigation
              </button>

              <button type="button" className="secondary" onClick={onSystem}>
                System status
              </button>

              <details>
                <summary>Project options</summary>
                <code>{project.storage_root}</code>

                <button
                  type="button"
                  className="danger-ghost"
                  onClick={onArchive}
                >
                  Archive project
                </button>
              </details>
            </div>
          </>
        )}
      </aside>

      <section className="rv-workbench-main">
        <header className="rv-workbench-toolbar">
          <div>
            <p className="eyebrow">
              {activePreset === "review"
                ? "Scientist review mode"
                : `${preset.label} workspace`}
            </p>

            <h3>{contextTitle}</h3>
            <p>{contextDescription}</p>
          </div>

          <div
            className="rv-workbench-toolbar-meta"
            aria-label="Workspace context"
          >
            <span>{preset.shortLabel}</span>
            <span>Local project</span>

            <span>
              {activePreset === "review"
                ? "Human verification boundary"
                : "Scientist review enabled"}
            </span>

            {inspector && (
              <div
                className="rv-panel-layout-actions"
                aria-label="Inspector layout controls"
              >
                {!layout.inspectorDetached && (
                  <button
                    type="button"
                    className="secondary"
                    aria-pressed={!layout.inspectorCollapsed}
                    onClick={() =>
                      patchLayout({
                        inspectorCollapsed: !layout.inspectorCollapsed,
                      })
                    }
                  >
                    {layout.inspectorCollapsed
                      ? "Show inspector"
                      : "Hide inspector"}
                  </button>
                )}

                {layout.inspectorDetached ? (
                  <button
                    type="button"
                    className="secondary"
                    disabled={panelBusy}
                    onClick={() => void dockInspector()}
                  >
                    {panelBusy ? "Docking…" : "Dock inspector"}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="secondary"
                    disabled={panelBusy}
                    onClick={() => void detachInspector()}
                  >
                    {panelBusy ? "Detaching…" : "Detach inspector"}
                  </button>
                )}
              </div>
            )}
          </div>
        </header>

        {panelError && (
          <div className="rv-panel-layout-error" role="alert">
            <strong>Inspector window unavailable</strong>
            <span>{panelError}</span>
          </div>
        )}

        {layout.inspectorDetached && (
          <div className="rv-detached-panel-banner" role="status">
            <div>
              <strong>Inspector detached</strong>
              <span>
                The contextual scientist inspector is open in a separate window.
                Scientific state remains owned by the canonical workspace.
              </span>
            </div>

            <button
              type="button"
              className="secondary"
              disabled={panelBusy}
              onClick={() => void dockInspector()}
            >
              Dock back
            </button>
          </div>
        )}

        {activePreset === "review" && (
          <div className="rv-review-mode-banner" role="status">
            <strong>Review Mode</strong>
            <span>
              Machine output remains provisional until a scientist explicitly
              verifies or corrects it.
            </span>
          </div>
        )}

        <div className="rv-workbench-stage">{children}</div>
      </section>

      {!layout.inspectorCollapsed && !layout.inspectorDetached && (
        <aside
          className="rv-workbench-inspector"
          aria-label="Workspace inspector"
        >
          <div className="rv-inspector-heading">
            <p className="eyebrow">Inspector</p>
            <h3>{contextTitle}</h3>
            <p>{contextDescription}</p>
          </div>

          {inspector ?? (
            <div className="rv-inspector-card">
              <strong>Project context</strong>

              <dl>
                <div>
                  <dt>Active classes</dt>
                  <dd>
                    {
                      project.label_classes.filter((item) => item.is_active)
                        .length
                    }
                  </dd>
                </div>

                <div>
                  <dt>Annotation type</dt>
                  <dd>{project.default_annotation_type}</dd>
                </div>

                <div>
                  <dt>Preset</dt>
                  <dd>{preset.label}</dd>
                </div>

                <div>
                  <dt>Truth policy</dt>
                  <dd>Scientist verified</dd>
                </div>
              </dl>

              <p>
                Tool-specific controls stay inside each validated ReefVision
                workspace. Layout visibility is saved locally for this project.
              </p>
            </div>
          )}
        </aside>
      )}
    </section>
  );
}
