import { useEffect, useState, type ReactNode } from "react";

import type { Project } from "../../api/client";
import {
  WORKSPACE_PRESETS,
  workspacePreset,
  type WorkspacePresetId,
} from "./workspacePresets";

interface WorkbenchLayoutPreferences {
  navigationCollapsed: boolean;
  inspectorCollapsed: boolean;
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
    };
  } catch {
    return {
      navigationCollapsed: false,
      inspectorCollapsed: false,
    };
  }
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

  useEffect(() => {
    setLayout(readLayoutPreferences(project.id));
  }, [project.id]);

  function updateLayout(next: WorkbenchLayoutPreferences): void {
    setLayout(next);
    window.localStorage.setItem(
      layoutStorageKey(project.id),
      JSON.stringify(next),
    );
  }

  const preset = workspacePreset(activePreset);

  return (
    <section
      className={[
        "rv-project-workbench",
        layout.navigationCollapsed ? "navigation-collapsed" : "",
        layout.inspectorCollapsed ? "inspector-collapsed" : "",
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
                updateLayout({ ...layout, navigationCollapsed: false })
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
                  updateLayout({ ...layout, navigationCollapsed: true })
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
            <button
              type="button"
              className="secondary"
              aria-pressed={!layout.inspectorCollapsed}
              onClick={() =>
                updateLayout({
                  ...layout,
                  inspectorCollapsed: !layout.inspectorCollapsed,
                })
              }
            >
              {layout.inspectorCollapsed ? "Show inspector" : "Hide inspector"}
            </button>
          </div>
        </header>

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

      {!layout.inspectorCollapsed && (
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
