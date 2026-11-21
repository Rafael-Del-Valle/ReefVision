import { useState } from "react";

import { pluginLabel } from "../../features/plugins/pluginApi";
import {
  panelPluginStatus,
  useContextualPanelLayout,
} from "./ContextualPanelLayout";

export function ContextualPanelManager({
  id,
  onReset,
  resetPending,
}: {
  id: string;
  onReset: () => void;
  resetPending: boolean;
}) {
  const layout = useContextualPanelLayout();
  const [selectedPluginId, setSelectedPluginId] = useState("");
  if (!layout) return null;
  const unpinned = layout.pluginRecords.filter(
    (record) =>
      !layout.panels.some((panel) => panel.pluginRecordId === record.id),
  );
  const selected = unpinned.some((record) => record.id === selectedPluginId)
    ? selectedPluginId
    : "";

  return (
    <section
      className="rv-contextual-panel-manager"
      id={id}
      aria-label="Panels"
    >
      <div className="rv-contextual-panel-manager-heading">
        <h4>Panels</h4>
        <button
          type="button"
          className="secondary"
          onClick={onReset}
          disabled={resetPending}
        >
          Reset layout
        </button>
      </div>
      {layout.storageFailed && (
        <p role="alert">This layout could not be saved on this device.</p>
      )}
      <ol className="rv-contextual-panel-order">
        {layout.panels.map((panel, index) => (
          <li key={panel.id}>
            <label className="inline-check">
              <input
                type="checkbox"
                checked={!layout.hidden.includes(panel.id)}
                onChange={(event) =>
                  layout.setVisible(panel.id, event.currentTarget.checked)
                }
              />
              Show {panel.label}
            </label>
            {panel.pluginRecordId && (
              <small>{panelPluginStatus(layout, panel)}</small>
            )}
            <div className="button-row">
              <button
                type="button"
                className="secondary"
                aria-label={`Move ${panel.label} up`}
                disabled={index === 0}
                onClick={(event) => {
                  if (index === 1)
                    event.currentTarget
                      .closest("li")
                      ?.querySelector("input")
                      ?.focus();
                  layout.move(panel.id, -1);
                }}
              >
                Up
              </button>
              <button
                type="button"
                className="secondary"
                aria-label={`Move ${panel.label} down`}
                disabled={index === layout.panels.length - 1}
                onClick={(event) => {
                  if (index === layout.panels.length - 2)
                    event.currentTarget
                      .closest("li")
                      ?.querySelector("input")
                      ?.focus();
                  layout.move(panel.id, 1);
                }}
              >
                Down
              </button>
              {panel.pluginRecordId && (
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Remove ${panel.label} panel`}
                  onClick={() => layout.removePlugin(panel)}
                >
                  Remove panel
                </button>
              )}
            </div>
          </li>
        ))}
      </ol>
      {layout.supportsPlugins && (
        <div className="button-row">
          <label>
            Local plugin panel
            <select
              value={selected}
              onChange={(event) =>
                setSelectedPluginId(event.currentTarget.value)
              }
            >
              <option value="">Choose a plugin</option>
              {unpinned.map((record) => (
                <option key={record.id} value={record.id}>
                  {pluginLabel(record)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!selected}
            onClick={() => {
              layout.addPlugin(selected);
              setSelectedPluginId("");
            }}
          >
            Add plugin panel
          </button>
          {layout.catalogPending && <p role="status">Loading local plugins…</p>}
          {layout.catalogFailed && (
            <p role="alert">Could not open the local plugin catalog.</p>
          )}
          {!layout.catalogPending &&
            !layout.catalogFailed &&
            layout.pluginRecords.length === 0 && (
              <p>No local plugins installed.</p>
            )}
        </div>
      )}
    </section>
  );
}
