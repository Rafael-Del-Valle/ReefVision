import type { WorkspaceInspectorView } from "./workspaceInspector";
import type { WorkspacePresetId } from "./workspacePresets";

const builtInPanels = [
  { id: "workflow-context", label: "Scientist workflow context" },
  { id: "image-inference", label: "Image inference" },
  { id: "morphometrics", label: "Morphometrics" },
  { id: "training-monitor", label: "Training monitor" },
  { id: "review-queue", label: "Review queue" },
  { id: "video-pose", label: "Video and pose" },
  { id: "truth-boundary", label: "Scientific truth boundary" },
  { id: "preset-guidance", label: "Workspace preset guidance" },
  { id: "related-workspaces", label: "Related workspaces" },
  { id: "project-context", label: "Project context" },
] as const;

export interface PanelPreferenceEntry {
  id: string;
  label: string;
  pluginRecordId?: string;
}

export interface ContextualPanelPreferences {
  order: string[];
  hidden: string[];
  plugins: Array<{ pluginRecordId: string; label: string }>;
}

export function emptyPanelPreferences(): ContextualPanelPreferences {
  return { order: [], hidden: [], plugins: [] };
}

export function contextualPanelKey(projectId: string): string {
  return `reefvision.ui.contextual-panels.${projectId}.v1`;
}

function panelEntries(plugins: ContextualPanelPreferences["plugins"]) {
  return [
    ...builtInPanels,
    ...plugins.map((item) => ({
      ...item,
      id: `plugin:${item.pluginRecordId}`,
    })),
  ];
}

export function readPanelPreferences(
  raw: string | null,
): ContextualPanelPreferences {
  try {
    const saved: unknown = JSON.parse(raw ?? "{}");
    if (saved === null || typeof saved !== "object" || Array.isArray(saved)) {
      return emptyPanelPreferences();
    }
    const fields = saved as Record<string, unknown>;
    const plugins = new Map<
      string,
      { pluginRecordId: string; label: string }
    >();
    if (Array.isArray(fields.plugins)) {
      for (const entry of fields.plugins) {
        if (
          typeof entry?.pluginRecordId === "string" &&
          /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(
            entry.pluginRecordId,
          ) &&
          typeof entry.label === "string" &&
          entry.label.trim()
        ) {
          plugins.set(entry.pluginRecordId, {
            pluginRecordId: entry.pluginRecordId,
            label: entry.label,
          });
        }
      }
    }
    const retained = [...plugins.values()];
    const ids = new Set(panelEntries(retained).map((panel) => panel.id));
    function knownIds(value: unknown): string[] {
      return Array.isArray(value)
        ? [
            ...new Set(
              value.filter(
                (id): id is string => typeof id === "string" && ids.has(id),
              ),
            ),
          ]
        : [];
    }
    return {
      order: knownIds(fields.order),
      hidden: knownIds(fields.hidden),
      plugins: retained,
    };
  } catch {
    return emptyPanelPreferences();
  }
}

function panelOrder(
  preferences: ContextualPanelPreferences,
): PanelPreferenceEntry[] {
  const entries = panelEntries(preferences.plugins);
  const ranks = new Map(
    [
      ...new Set([...preferences.order, ...entries.map((entry) => entry.id)]),
    ].map((id, index) => [id, index]),
  );
  return entries.sort(
    (a, b) => (ranks.get(a.id) ?? 0) - (ranks.get(b.id) ?? 0),
  );
}

export function supportsContextualPlugins(
  view: WorkspaceInspectorView,
): boolean {
  return (
    view === "gallery" || view === "advanced_providers" || view === "workflows"
  );
}

export function contextualPanels(
  preferences: ContextualPanelPreferences,
  view: WorkspaceInspectorView,
  preset: WorkspacePresetId,
): PanelPreferenceEntry[] {
  return panelOrder(preferences).filter((panel) => {
    switch (panel.id) {
      case "image-inference":
        return view === "gallery" && preset !== "morphometrics";
      case "morphometrics":
        return view === "gallery" && preset === "morphometrics";
      case "training-monitor":
        return view === "training";
      case "review-queue":
        return view === "review_queue";
      case "video-pose":
        return view === "video";
      default:
        return !panel.pluginRecordId || supportsContextualPlugins(view);
    }
  });
}

export function moveContextualPanel(
  preferences: ContextualPanelPreferences,
  panels: PanelPreferenceEntry[],
  id: string,
  offset: -1 | 1,
): ContextualPanelPreferences {
  const index = panels.findIndex((panel) => panel.id === id);
  const target = index >= 0 && panels[index + offset];
  if (!target) return preferences;
  const order = panelOrder(preferences)
    .map((panel) => panel.id)
    .filter((key) => key !== id);
  order.splice(order.indexOf(target.id) + (offset === 1 ? 1 : 0), 0, id);
  return { ...preferences, order };
}
