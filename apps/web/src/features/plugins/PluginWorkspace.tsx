import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";

import samplePackageUrl from "../../../../../examples/plugins/green-fraction.rvplugin.json?url&inline";
import {
  saveWorkflowGraph,
  type WorkflowGraphRecord,
} from "../workflow-graphs/workflowGraphApi";
import { PluginMeasurementControls } from "./PluginMeasurementControls";
import {
  installPlugin,
  listPluginMeasurements,
  listPlugins,
  measurePluginImage,
  pluginAvailability,
  pluginCatalogKey,
  pluginLabel,
  pluginMeasurementsKey,
  pluginPageSize,
  setPluginEnabled,
  type PluginMeasurementInput,
  type PluginRecord,
} from "./pluginApi";

interface Props {
  projectId: string;
  onOpenWorkflow?: (graph: WorkflowGraphRecord) => void;
}

function readPackage(file: File): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () =>
      reject(new Error("Could not read the plugin package."));
    reader.onload = () => {
      try {
        const bundle: unknown = JSON.parse(String(reader.result));
        if (
          bundle === null ||
          typeof bundle !== "object" ||
          Array.isArray(bundle)
        ) {
          throw new Error("The package must be a JSON object.");
        }
        resolve(bundle);
      } catch {
        reject(new Error("Choose a plugin package containing a JSON object."));
      }
    };
    reader.readAsText(file);
  });
}

function Pagination({
  label,
  offset,
  total,
  onChange,
}: {
  label: string;
  offset: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total <= pluginPageSize) return null;
  return (
    <div className="button-row" aria-label={`${label} pages`}>
      <button
        type="button"
        className="secondary"
        disabled={offset === 0}
        onClick={() => onChange(offset - pluginPageSize)}
      >
        Previous {label}
      </button>
      <span>
        {offset + 1}–{Math.min(total, offset + pluginPageSize)} of {total}
      </span>
      <button
        type="button"
        className="secondary"
        disabled={offset + pluginPageSize >= total}
        onClick={() => onChange(offset + pluginPageSize)}
      >
        Next {label}
      </button>
    </div>
  );
}

export function PluginWorkspace({ projectId, onOpenWorkflow }: Props) {
  const heading = useId();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [catalogOffset, setCatalogOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [pins, setPins] = useState<Partial<PluginMeasurementInput>>({});
  const [pauseForReview, setPauseForReview] = useState(true);

  const catalog = useQuery({
    queryKey: [...pluginCatalogKey, catalogOffset],
    queryFn: ({ signal }) => listPlugins(catalogOffset, signal),
  });
  const historyKey = pluginMeasurementsKey(projectId);
  const history = useQuery({
    queryKey: [...historyKey, historyOffset],
    queryFn: ({ signal }) =>
      listPluginMeasurements(projectId, historyOffset, signal),
  });

  const install = useMutation({
    mutationFn: async (selected: File) =>
      installPlugin(await readPackage(selected)),
    onSuccess: async () => {
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setCatalogOffset(0);
      await queryClient.invalidateQueries({ queryKey: pluginCatalogKey });
    },
  });
  const toggle = useMutation({
    mutationFn: (record: PluginRecord) =>
      setPluginEnabled(record, !record.enabled),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: pluginCatalogKey }),
  });
  const measure = useMutation({
    mutationFn: (input: PluginMeasurementInput) =>
      measurePluginImage(projectId, input),
    onSuccess: async () => {
      setHistoryOffset(0);
      await queryClient.invalidateQueries({ queryKey: historyKey });
    },
  });
  const saveGraph = useMutation({
    mutationFn: ({
      input,
      pauseForReview,
    }: {
      input: PluginMeasurementInput;
      pauseForReview: boolean;
    }) =>
      saveWorkflowGraph(projectId, {
        schema_version: "workflow-graph-0001",
        graph_id: "plugin-image-measurement",
        name: "Plugin image measurement",
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "measure-image",
            node_type: "plugin_image_measurement",
            parameters: input,
          },
          ...(pauseForReview
            ? [
                {
                  node_id: "review-measurement",
                  node_type: "measurement_review_gate",
                },
              ]
            : []),
        ],
        edges: [
          {
            edge_id: "project-to-measurement",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "measure-image",
            target_port_id: "project",
          },
          ...(pauseForReview
            ? [
                {
                  edge_id: "measurement-to-review",
                  source_node_id: "measure-image",
                  source_port_id: "measurement",
                  target_node_id: "review-measurement",
                  target_port_id: "measurement",
                },
              ]
            : []),
        ],
      }),
    onSuccess: (graph) => onOpenWorkflow?.(graph),
  });

  return (
    <section aria-labelledby={heading} className="feature-workspace">
      <h4 id={heading}>Local plugins</h4>
      <div className="feature-grid">
        <div className="panel-card">
          <h5>Installed packages</h5>
          <p>
            <a href={samplePackageUrl} download="green-fraction.rvplugin.json">
              Download sample plugin
            </a>
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (file && !install.isPending) install.mutate(file);
            }}
          >
            <label>
              Plugin package (JSON)
              <input
                ref={fileInput}
                type="file"
                accept=".json,application/json"
                disabled={install.isPending}
                onChange={(event) => {
                  setFile(event.currentTarget.files?.[0] ?? null);
                  install.reset();
                }}
              />
            </label>
            <button type="submit" disabled={!file || install.isPending}>
              {install.isPending ? "Installing…" : "Install plugin"}
            </button>
          </form>
          {catalog.isPending && <p role="status">Loading local plugins…</p>}
          {install.isSuccess && (
            <p role="status">Installed {pluginLabel(install.data)}.</p>
          )}
          {install.error && <p role="alert">{install.error.message}</p>}
          {catalog.error && <p role="alert">{catalog.error.message}</p>}
          {toggle.error && <p role="alert">{toggle.error.message}</p>}
          {catalog.data?.total === 0 && <p>No local plugins installed.</p>}
          {catalog.data?.items.length ? (
            <ul className="record-list">
              {catalog.data.items.map((record) => (
                <li key={record.id}>
                  <p>
                    <strong>{pluginLabel(record)}</strong> ·{" "}
                    {pluginAvailability(record)}
                  </p>
                  {record.manifest.description && (
                    <p>{record.manifest.description}</p>
                  )}
                  <p>
                    {record.manifest.abi} · {record.manifest.license}
                  </p>
                  <p>Permission · Read RGB summary and pixel count</p>
                  <p>
                    Package SHA-256 <code>{record.package_sha256}</code>
                  </p>
                  {record.reason && <p>{record.reason}</p>}
                  <button
                    type="button"
                    className="secondary"
                    disabled={
                      toggle.isPending || (!record.available && !record.enabled)
                    }
                    onClick={() => toggle.mutate(record)}
                  >
                    {record.enabled ? "Disable" : "Enable"}{" "}
                    {pluginLabel(record)}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <Pagination
            label="packages"
            offset={catalogOffset}
            total={catalog.data?.total ?? 0}
            onChange={setCatalogOffset}
          />
        </div>

        <div className="panel-card">
          <h5>Measure an image</h5>
          <PluginMeasurementControls
            projectId={projectId}
            pins={pins}
            onChange={setPins}
            actions={(input) => (
              <>
                {onOpenWorkflow && (
                  <label className="inline-check">
                    <input
                      type="checkbox"
                      checked={pauseForReview}
                      onChange={(event) =>
                        setPauseForReview(event.target.checked)
                      }
                    />
                    Pause for measurement review
                  </label>
                )}
                <div className="button-row">
                  <button
                    type="button"
                    disabled={!input || measure.isPending}
                    onClick={() => input && measure.mutate(input)}
                  >
                    {measure.isPending ? "Measuring…" : "Run measurement"}
                  </button>
                  {onOpenWorkflow && (
                    <button
                      type="button"
                      className="secondary"
                      disabled={!input || saveGraph.isPending}
                      onClick={() =>
                        input && saveGraph.mutate({ input, pauseForReview })
                      }
                    >
                      Open in Workflow Builder
                    </button>
                  )}
                </div>
              </>
            )}
          />
          {measure.isSuccess && <p role="status">Measurement saved.</p>}
          {measure.error && <p role="alert">{measure.error.message}</p>}
          {saveGraph.error && <p role="alert">{saveGraph.error.message}</p>}
        </div>
      </div>

      <div className="panel-card">
        <h5>Saved plugin measurements</h5>
        {history.isPending && <p role="status">Loading saved measurements…</p>}
        {history.error && <p role="alert">{history.error.message}</p>}
        {history.data?.total === 0 && (
          <p>No plugin measurements in this project.</p>
        )}
        {history.data?.items.length ? (
          <ul className="record-list">
            {history.data.items.map((row) => {
              const parameters = row.provenance.processing_parameters ?? {};
              const provenance = {
                Plugin: parameters.plugin_id,
                Version: parameters.plugin_version,
                "Package SHA-256": parameters.package_sha256,
                "Module SHA-256": parameters.module_sha256,
                "Original image SHA-256": parameters.image_sha256,
              };
              return (
                <li key={row.id}>
                  <h6>{row.variable}</h6>
                  <p>
                    <strong>
                      {row.value} {row.unit}
                    </strong>{" "}
                    · {row.qc ?? "unassessed"}
                  </p>
                  <p>
                    Measurement SHA-256 <code>{row.content_sha256}</code>
                  </p>
                  <details>
                    <summary>Measurement provenance</summary>
                    <dl>
                      {Object.entries(provenance).map(
                        ([label, value]) =>
                          typeof value === "string" && (
                            <div key={label}>
                              <dt>{label}</dt>
                              <dd>
                                <code>{value}</code>
                              </dd>
                            </div>
                          ),
                      )}
                    </dl>
                  </details>
                </li>
              );
            })}
          </ul>
        ) : null}
        <Pagination
          label="measurements"
          offset={historyOffset}
          total={history.data?.total ?? 0}
          onChange={setHistoryOffset}
        />
      </div>
    </section>
  );
}
