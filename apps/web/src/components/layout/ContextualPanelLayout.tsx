import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  listPlugins,
  pluginCatalogKey,
  pluginLabel,
  pluginPageSize,
  type PluginRecord,
} from "../../features/plugins/pluginApi";
import {
  contextualPanelKey,
  contextualPanels,
  emptyPanelPreferences,
  moveContextualPanel,
  readPanelPreferences,
  supportsContextualPlugins,
  type ContextualPanelPreferences,
  type PanelPreferenceEntry,
} from "./contextualPanelPreferences";
import type { WorkspaceInspectorView } from "./workspaceInspector";
import type { WorkspacePresetId } from "./workspacePresets";

interface ContextualPanelLayoutValue {
  panels: PanelPreferenceEntry[];
  hidden: string[];
  pluginRecords: PluginRecord[];
  supportsPlugins: boolean;
  catalogPending: boolean;
  catalogFailed: boolean;
  storageFailed: boolean;
  managerOpen: boolean;
  setManagerOpen: (open: boolean) => void;
  setVisible: (id: string, visible: boolean) => void;
  move: (id: string, offset: -1 | 1) => void;
  addPlugin: (id: string) => void;
  removePlugin: (panel: PanelPreferenceEntry) => void;
  reset: () => void;
}

const PanelLayoutContext = createContext<ContextualPanelLayoutValue | null>(
  null,
);

export function useContextualPanelLayout() {
  return useContext(PanelLayoutContext);
}

async function readPluginCatalog(signal: AbortSignal) {
  const records: PluginRecord[] = [];
  for (let offset = 0; ; offset += pluginPageSize) {
    const page = await listPlugins(offset, signal);
    records.push(...page.items);
    if (offset + pluginPageSize >= page.total) return records;
  }
}

function loadPreferences(key: string) {
  try {
    return readPanelPreferences(window.localStorage.getItem(key));
  } catch {
    return emptyPanelPreferences();
  }
}

export function ContextualPanelLayoutProvider({
  projectId,
  view,
  preset,
  children,
}: {
  projectId: string;
  view: WorkspaceInspectorView;
  preset: WorkspacePresetId;
  children: ReactNode;
}) {
  const key = contextualPanelKey(projectId);
  const [preferences, setPreferences] = useState(() => loadPreferences(key));
  const [storageFailed, setStorageFailed] = useState(false);
  const [managerOpen, setManagerOpen] = useState(false);
  const hasPluginPanels = preferences.plugins.length > 0;
  const supportsPlugins = supportsContextualPlugins(view);
  const catalog = useQuery({
    queryKey: [...pluginCatalogKey, "contextual-panels"],
    queryFn: ({ signal }) => readPluginCatalog(signal),
    enabled: supportsPlugins && (managerOpen || hasPluginPanels),
  });
  const panels = contextualPanels(preferences, view, preset);
  const pluginRecords = catalog.data ?? [];

  useEffect(() => {
    function synchronize(event: StorageEvent) {
      if (event.key === key || event.key === null) {
        setPreferences(loadPreferences(key));
      }
    }
    window.addEventListener("storage", synchronize);
    return () => window.removeEventListener("storage", synchronize);
  }, [key]);

  function write(next: ContextualPanelPreferences, reset = false) {
    setPreferences(next);
    try {
      if (reset) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, JSON.stringify(next));
      setStorageFailed(false);
    } catch {
      setStorageFailed(true);
    }
  }

  return (
    <PanelLayoutContext.Provider
      value={{
        panels,
        hidden: preferences.hidden,
        pluginRecords,
        supportsPlugins,
        catalogPending: catalog.isPending,
        catalogFailed: catalog.isError,
        storageFailed,
        managerOpen,
        setManagerOpen,
        setVisible: (id, visible) =>
          write({
            ...preferences,
            hidden: visible
              ? preferences.hidden.filter((item) => item !== id)
              : [...preferences.hidden, id],
          }),
        move: (id, offset) =>
          write(moveContextualPanel(preferences, panels, id, offset)),
        addPlugin: (id) => {
          const selected = pluginRecords.find((plugin) => plugin.id === id);
          if (
            !selected ||
            preferences.plugins.some((item) => item.pluginRecordId === id)
          )
            return;
          write({
            ...preferences,
            plugins: [
              ...preferences.plugins,
              { pluginRecordId: id, label: pluginLabel(selected) },
            ],
          });
        },
        removePlugin: (panel) =>
          write({
            order: preferences.order.filter((id) => id !== panel.id),
            hidden: preferences.hidden.filter((id) => id !== panel.id),
            plugins: preferences.plugins.filter(
              (item) => item.pluginRecordId !== panel.pluginRecordId,
            ),
          }),
        reset: () => write(emptyPanelPreferences(), true),
      }}
    >
      {children}
    </PanelLayoutContext.Provider>
  );
}

export function panelPluginStatus(
  layout: ContextualPanelLayoutValue,
  panel: PanelPreferenceEntry,
) {
  if (layout.catalogFailed) return "Plugin catalog unavailable.";
  const plugin = layout.pluginRecords.find(
    (record) => record.id === panel.pluginRecordId,
  );
  if (plugin && !plugin.available)
    return plugin.reason ?? "Plugin unavailable.";
  if (plugin && !plugin.enabled) return "Plugin disabled.";
  if (plugin) return "Plugin enabled.";
  if (layout.catalogPending) return "Checking plugin availability…";
  return "Plugin missing. Reinstall its package to recover this panel.";
}
