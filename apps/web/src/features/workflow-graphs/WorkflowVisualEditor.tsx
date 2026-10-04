import { useEffect, useMemo, useState } from "react";

import type {
  WorkflowGraphPlan,
  WorkflowNodeDefinition,
  WorkflowRunDetail,
} from "./workflowGraphApi";

interface GraphNode {
  node_id: string;
  node_type: string;
  parameters?: Record<string, unknown>;
  position?: { x: number; y: number };
}

interface GraphEdge {
  edge_id: string;
  source_node_id: string;
  source_port_id: string;
  target_node_id: string;
  target_port_id: string;
}

interface FeedbackLoop {
  from_node_id: string;
  to_node_id: string;
  label?: string;
  description?: string;
}

interface GraphShape {
  graph_id: string;
  name: string;
  schema_version: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata?: Record<string, unknown>;
}

interface WorkflowVisualEditorProps {
  graph: Record<string, unknown>;
  registry: WorkflowNodeDefinition[];
  onChange: (graph: Record<string, unknown>) => void;
  plan?: WorkflowGraphPlan | null;
  runDetail?: WorkflowRunDetail | null;
}

interface PendingConnection {
  nodeId: string;
  portId: string;
  dataTypes: string[];
}

const NODE_WIDTH = 260;
const NODE_HEADER_HEIGHT = 74;
const MIN_CANVAS_WIDTH = 1800;
const MIN_CANVAS_HEIGHT = 820;

function asGraph(value: Record<string, unknown>): GraphShape | null {
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges)) return null;
  return value as unknown as GraphShape;
}

function asFeedbackLoop(
  metadata: Record<string, unknown> | undefined,
): FeedbackLoop | null {
  const raw = metadata?.feedback_loop;
  if (!raw || Array.isArray(raw) || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (
    typeof value.from_node_id !== "string" ||
    typeof value.to_node_id !== "string"
  ) {
    return null;
  }
  return {
    from_node_id: value.from_node_id,
    to_node_id: value.to_node_id,
    label: typeof value.label === "string" ? value.label : undefined,
    description:
      typeof value.description === "string" ? value.description : undefined,
  };
}

function slug(value: string): string {
  return value
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function defaultPosition(index: number): { x: number; y: number } {
  return {
    x: 40 + (index % 5) * 310,
    y: 40 + Math.floor(index / 5) * 230,
  };
}

function portCompatible(sourceTypes: string[], targetTypes: string[]): boolean {
  return sourceTypes.some((item) => targetTypes.includes(item));
}

function nodeKind(definition: WorkflowNodeDefinition | undefined): string {
  if (!definition) return "Automated";
  if (definition.category === "Human review") return "Scientist review";
  if (definition.category === "Scientific analysis")
    return "Scientific analysis";
  if (definition.category === "Active learning") return "Active learning";
  return "Automated";
}

function statusLabel(status: string | undefined): string | null {
  if (!status) return null;
  const labels: Record<string, string> = {
    pending: "Pending",
    queued: "Queued",
    running: "Running",
    waiting_for_review: "Waiting for scientist review",
    review_approved: "Review approved",
    succeeded: "Succeeded",
    failed: "Failed",
    cancelled: "Cancelled",
    cancel_requested: "Cancelling",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function isPrimitive(value: unknown): boolean {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

export function WorkflowVisualEditor({
  graph: rawGraph,
  registry,
  onChange,
  plan = null,
  runDetail = null,
}: WorkflowVisualEditorProps) {
  const graph = asGraph(rawGraph);
  const [pending, setPending] = useState<PendingConnection | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [parameterText, setParameterText] = useState("{}");
  const [message, setMessage] = useState<string | null>(null);

  const definitions = useMemo(
    () => new Map(registry.map((item) => [item.node_type, item])),
    [registry],
  );
  const runNodes = useMemo(
    () => new Map((runDetail?.nodes ?? []).map((item) => [item.node_id, item])),
    [runDetail],
  );
  const planSteps = useMemo(
    () => new Map((plan?.steps ?? []).map((item) => [item.node_id, item])),
    [plan],
  );

  const selectedNode = graph?.nodes.find(
    (item) => item.node_id === selectedNodeId,
  );
  const selectedDefinition = selectedNode
    ? definitions.get(selectedNode.node_type)
    : undefined;

  useEffect(() => {
    setParameterText(JSON.stringify(selectedNode?.parameters ?? {}, null, 2));
  }, [selectedNodeId, selectedNode?.parameters]);

  if (!graph) {
    return (
      <p className="form-error">
        Visual editing is unavailable until the graph JSON contains nodes and
        edges arrays.
      </p>
    );
  }

  const currentGraph = graph;
  const feedbackLoop = asFeedbackLoop(currentGraph.metadata);

  function emit(next: GraphShape): void {
    onChange(next as unknown as Record<string, unknown>);
  }

  function positionedNode(node: GraphNode, index: number): GraphNode {
    return node.position ? node : { ...node, position: defaultPosition(index) };
  }

  function addNode(nodeType: string): void {
    const definition = definitions.get(nodeType);
    if (!definition) return;
    const base = slug(nodeType) || "node";
    let suffix = currentGraph.nodes.length + 1;
    let nodeId = `${base}-${suffix}`;
    while (currentGraph.nodes.some((item) => item.node_id === nodeId)) {
      suffix += 1;
      nodeId = `${base}-${suffix}`;
    }
    const parameters: Record<string, unknown> = {
      ...definition.optional_parameters,
    };
    const node: GraphNode = {
      node_id: nodeId,
      node_type: nodeType,
      parameters,
      position: defaultPosition(currentGraph.nodes.length),
    };
    emit({ ...currentGraph, nodes: [...currentGraph.nodes, node] });
    setSelectedNodeId(nodeId);
    setMessage(`Added ${definition.display_name}.`);
  }

  function removeNode(nodeId: string): void {
    emit({
      ...currentGraph,
      nodes: currentGraph.nodes.filter((item) => item.node_id !== nodeId),
      edges: currentGraph.edges.filter(
        (edge) =>
          edge.source_node_id !== nodeId && edge.target_node_id !== nodeId,
      ),
    });
    if (selectedNodeId === nodeId) setSelectedNodeId(null);
    if (pending?.nodeId === nodeId) setPending(null);
  }

  function moveNode(nodeId: string, x: number, y: number): void {
    emit({
      ...currentGraph,
      nodes: currentGraph.nodes.map((node, index) => {
        const resolved = positionedNode(node, index);
        return resolved.node_id === nodeId
          ? {
              ...resolved,
              position: {
                x: Math.max(0, x),
                y: Math.max(0, y),
              },
            }
          : resolved;
      }),
    });
  }

  function arrangeNodes(): void {
    const orderedIds =
      plan?.steps.map((step) => step.node_id) ??
      currentGraph.nodes.map((node) => node.node_id);
    const order = new Map(orderedIds.map((nodeId, index) => [nodeId, index]));
    const nodes = currentGraph.nodes.map((node, index) => {
      const resolvedIndex = order.get(node.node_id) ?? index;
      return {
        ...node,
        position: defaultPosition(resolvedIndex),
      };
    });
    emit({ ...currentGraph, nodes });
    setMessage("Arranged nodes in execution order.");
  }

  function beginConnection(
    nodeId: string,
    portId: string,
    dataTypes: string[],
  ): void {
    setPending({ nodeId, portId, dataTypes });
    setMessage(`Select a compatible input for ${nodeId}.${portId}.`);
  }

  function finishConnection(
    targetNodeId: string,
    targetPortId: string,
    targetTypes: string[],
    multiple: boolean,
  ): void {
    if (!pending) return;
    if (pending.nodeId === targetNodeId) {
      setMessage("A workflow node cannot connect to itself.");
      return;
    }
    if (!portCompatible(pending.dataTypes, targetTypes)) {
      setMessage("Those ports have incompatible artifact types.");
      return;
    }
    const duplicate = currentGraph.edges.some(
      (edge) =>
        edge.source_node_id === pending.nodeId &&
        edge.source_port_id === pending.portId &&
        edge.target_node_id === targetNodeId &&
        edge.target_port_id === targetPortId,
    );
    if (duplicate) {
      setPending(null);
      setMessage("That connection already exists.");
      return;
    }
    const retainedEdges = multiple
      ? currentGraph.edges
      : currentGraph.edges.filter(
          (edge) =>
            !(
              edge.target_node_id === targetNodeId &&
              edge.target_port_id === targetPortId
            ),
        );
    const edgeBase = slug(
      `${pending.nodeId}-${pending.portId}-${targetNodeId}-${targetPortId}`,
    );
    let edgeId = edgeBase || `edge-${currentGraph.edges.length + 1}`;
    let suffix = 2;
    while (retainedEdges.some((edge) => edge.edge_id === edgeId)) {
      edgeId = `${edgeBase}-${suffix}`;
      suffix += 1;
    }
    emit({
      ...currentGraph,
      edges: [
        ...retainedEdges,
        {
          edge_id: edgeId,
          source_node_id: pending.nodeId,
          source_port_id: pending.portId,
          target_node_id: targetNodeId,
          target_port_id: targetPortId,
        },
      ],
    });
    setPending(null);
    setMessage(`Connected ${pending.nodeId} → ${targetNodeId}.`);
  }

  function replaceSelectedParameters(
    nextParameters: Record<string, unknown>,
  ): void {
    if (!selectedNode) return;
    emit({
      ...currentGraph,
      nodes: currentGraph.nodes.map((node) =>
        node.node_id === selectedNode.node_id
          ? { ...node, parameters: nextParameters }
          : node,
      ),
    });
  }

  function setSelectedParameter(key: string, value: unknown): void {
    replaceSelectedParameters({
      ...(selectedNode?.parameters ?? {}),
      [key]: value,
    });
  }

  function applyParameters(): void {
    if (!selectedNode) return;
    try {
      const value = JSON.parse(parameterText) as unknown;
      if (!value || Array.isArray(value) || typeof value !== "object") {
        throw new Error("Parameters must be a JSON object.");
      }
      replaceSelectedParameters(value as Record<string, unknown>);
      setMessage(`Updated parameters for ${selectedNode.node_id}.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Invalid parameter JSON.",
      );
    }
  }

  const positions = new Map(
    currentGraph.nodes.map((node, index) => {
      const resolved = positionedNode(node, index);
      return [
        resolved.node_id,
        resolved.position ?? defaultPosition(index),
      ] as const;
    }),
  );

  const maxX = Math.max(
    ...Array.from(positions.values()).map((position) => position.x),
    0,
  );
  const maxY = Math.max(
    ...Array.from(positions.values()).map((position) => position.y),
    0,
  );
  const canvasWidth = Math.max(MIN_CANVAS_WIDTH, maxX + NODE_WIDTH + 180);
  const canvasHeight = Math.max(MIN_CANVAS_HEIGHT, maxY + 300);

  const feedbackSource = feedbackLoop
    ? positions.get(feedbackLoop.from_node_id)
    : undefined;
  const feedbackTarget = feedbackLoop
    ? positions.get(feedbackLoop.to_node_id)
    : undefined;

  const parameterKeys = selectedNode
    ? Array.from(
        new Set([
          ...(selectedDefinition?.required_parameters ?? []),
          ...Object.keys(selectedDefinition?.optional_parameters ?? {}),
          ...Object.keys(selectedNode.parameters ?? {}),
        ]),
      )
    : [];

  return (
    <div className="workflow-editor-shell">
      <div className="workflow-editor-toolbar">
        <label>
          Add node
          <select
            defaultValue=""
            onChange={(event) => {
              if (event.target.value) addNode(event.target.value);
              event.target.value = "";
            }}
          >
            <option value="">Choose…</option>
            {registry.map((definition) => (
              <option key={definition.node_type} value={definition.node_type}>
                {definition.category} · {definition.display_name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="secondary" onClick={arrangeNodes}>
          Arrange by execution
        </button>
        {pending && (
          <button
            type="button"
            className="secondary"
            onClick={() => setPending(null)}
          >
            Cancel connection
          </button>
        )}
        <div className="workflow-legend" aria-label="Workflow node legend">
          <span className="workflow-legend-item automated">Automated</span>
          <span className="workflow-legend-item review">Scientist review</span>
          <span className="workflow-legend-item active-learning">
            Active learning
          </span>
          <span className="workflow-legend-item feedback">
            Next iteration cue
          </span>
        </div>
      </div>

      {feedbackLoop && (
        <div
          className="workflow-feedback-note"
          data-testid="workflow-feedback-note"
        >
          <strong>{feedbackLoop.label ?? "Next iteration"}</strong>
          <span>
            {feedbackLoop.description ??
              "The trained model can seed the next workflow iteration. This dashed cue is provenance guidance, not a cyclic execution edge."}
          </span>
        </div>
      )}

      {message && <p className="muted-copy">{message}</p>}

      <div className="workflow-editor-canvas-frame">
        <div
          className="workflow-editor-canvas"
          style={{
            width: canvasWidth,
            height: canvasHeight,
          }}
        >
          <svg
            width={canvasWidth}
            height={canvasHeight}
            className="workflow-edge-layer"
            aria-hidden="true"
          >
            <defs>
              <marker
                id="workflow-feedback-arrow"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path
                  d="M 0 0 L 10 5 L 0 10 z"
                  className="workflow-feedback-arrow"
                />
              </marker>
            </defs>
            {currentGraph.edges.map((edge) => {
              const source = positions.get(edge.source_node_id);
              const target = positions.get(edge.target_node_id);
              if (!source || !target) return null;
              const x1 = source.x + NODE_WIDTH;
              const y1 = source.y + NODE_HEADER_HEIGHT + 28;
              const x2 = target.x;
              const y2 = target.y + NODE_HEADER_HEIGHT + 28;
              const mid = (x1 + x2) / 2;
              return (
                <path
                  key={edge.edge_id}
                  d={`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`}
                  className="workflow-edge"
                />
              );
            })}
            {feedbackLoop && feedbackSource && feedbackTarget && (
              <path
                d={`M ${feedbackSource.x + NODE_WIDTH / 2} ${feedbackSource.y + 170}
                    C ${feedbackSource.x + NODE_WIDTH / 2} ${canvasHeight - 55},
                      ${feedbackTarget.x + NODE_WIDTH / 2} ${canvasHeight - 55},
                      ${feedbackTarget.x + NODE_WIDTH / 2} ${feedbackTarget.y + 170}`}
                className="workflow-feedback-edge"
                markerEnd="url(#workflow-feedback-arrow)"
                data-testid="workflow-feedback-edge"
              />
            )}
          </svg>

          {currentGraph.nodes.map((rawNode, index) => {
            const node = positionedNode(rawNode, index);
            const position = node.position ?? defaultPosition(index);
            const definition = definitions.get(node.node_type);
            const runNode = runNodes.get(node.node_id);
            const planStep = planSteps.get(node.node_id);
            const status = statusLabel(runNode?.status);
            const kind = nodeKind(definition);
            const reviewNode = definition?.category === "Human review";

            return (
              <div
                key={node.node_id}
                className={[
                  "workflow-node-card",
                  selectedNodeId === node.node_id ? "selected" : "",
                  reviewNode ? "is-review-node" : "",
                  definition?.category === "Active learning"
                    ? "is-active-learning-node"
                    : "",
                  runNode?.status ? `status-${runNode.status}` : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                style={{
                  left: position.x,
                  top: position.y,
                  width: NODE_WIDTH,
                }}
                data-node-id={node.node_id}
                data-node-status={runNode?.status ?? "not-run"}
              >
                <div
                  className="workflow-node-header"
                  onPointerDown={(event) => {
                    const element = event.currentTarget;
                    element.setPointerCapture(event.pointerId);
                    const originX = event.clientX;
                    const originY = event.clientY;
                    const start = position;
                    const handleMove = (moveEvent: PointerEvent) => {
                      moveNode(
                        node.node_id,
                        start.x + moveEvent.clientX - originX,
                        start.y + moveEvent.clientY - originY,
                      );
                    };
                    const handleUp = () => {
                      element.removeEventListener("pointermove", handleMove);
                      element.removeEventListener("pointerup", handleUp);
                    };
                    element.addEventListener("pointermove", handleMove);
                    element.addEventListener("pointerup", handleUp);
                  }}
                >
                  <div>
                    <strong>
                      {definition?.display_name ?? node.node_type}
                    </strong>
                    <small>{node.node_id}</small>
                  </div>
                  <span className="workflow-kind-chip">{kind}</span>
                </div>

                <div className="workflow-node-body">
                  {(status || planStep) && (
                    <div className="workflow-node-state">
                      {status && (
                        <span
                          className={`workflow-status-chip status-${runNode?.status}`}
                        >
                          {status}
                        </span>
                      )}
                      {!status && planStep && (
                        <span className="workflow-status-chip plan">
                          {planStep.executable ? "Plan ready" : "Plan blocked"}
                        </span>
                      )}
                    </div>
                  )}

                  {runNode?.error_message && (
                    <p className="workflow-node-error">
                      {runNode.error_message}
                    </p>
                  )}

                  <div className="workflow-port-group inputs">
                    {definition?.input_ports.map((port) => (
                      <button
                        key={`in-${port.port_id}`}
                        type="button"
                        className="workflow-port workflow-port-input"
                        title={`Input: ${port.accepted_types.join(", ")}`}
                        onClick={() =>
                          finishConnection(
                            node.node_id,
                            port.port_id,
                            port.accepted_types,
                            port.multiple,
                          )
                        }
                      >
                        ◀ {port.display_name}
                      </button>
                    ))}
                  </div>

                  <div className="workflow-port-group outputs">
                    {definition?.output_ports.map((port) => (
                      <button
                        key={`out-${port.port_id}`}
                        type="button"
                        className="workflow-port workflow-port-output"
                        title={`Output: ${port.accepted_types.join(", ")}`}
                        onClick={() =>
                          beginConnection(
                            node.node_id,
                            port.port_id,
                            port.accepted_types,
                          )
                        }
                      >
                        {port.display_name} ▶
                      </button>
                    ))}
                  </div>

                  <div className="button-row workflow-node-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setSelectedNodeId(node.node_id)}
                    >
                      Configure
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => removeNode(node.node_id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="workflow-editor-detail-grid">
        <div className="panel-card">
          <h5>Selected node parameters</h5>
          {selectedNode ? (
            <>
              <p>
                <strong>{selectedNode.node_id}</strong> ·{" "}
                {selectedNode.node_type}
              </p>
              {selectedDefinition && (
                <p className="muted-copy">{selectedDefinition.description}</p>
              )}

              {parameterKeys.length > 0 && (
                <div className="workflow-parameter-grid">
                  {parameterKeys.map((key) => {
                    const fallback =
                      selectedDefinition?.optional_parameters[key];
                    const value =
                      selectedNode.parameters &&
                      Object.prototype.hasOwnProperty.call(
                        selectedNode.parameters,
                        key,
                      )
                        ? selectedNode.parameters[key]
                        : fallback;
                    const required =
                      selectedDefinition?.required_parameters.includes(key) ??
                      false;
                    if (!isPrimitive(value)) {
                      return (
                        <div className="workflow-parameter-field" key={key}>
                          <strong>{key}</strong>
                          <small>
                            Nested setting · edit in Advanced parameter JSON.
                          </small>
                        </div>
                      );
                    }
                    if (typeof value === "boolean") {
                      return (
                        <label className="workflow-parameter-toggle" key={key}>
                          <input
                            type="checkbox"
                            checked={value}
                            onChange={(event) =>
                              setSelectedParameter(key, event.target.checked)
                            }
                          />
                          <span>
                            {key}
                            {required ? " *" : ""}
                          </span>
                        </label>
                      );
                    }
                    return (
                      <label className="workflow-parameter-field" key={key}>
                        <span>
                          {key}
                          {required ? " *" : ""}
                        </span>
                        <input
                          type={typeof value === "number" ? "number" : "text"}
                          value={
                            value === null || value === undefined
                              ? ""
                              : String(value)
                          }
                          onChange={(event) => {
                            const next =
                              typeof value === "number"
                                ? Number(event.target.value)
                                : event.target.value;
                            setSelectedParameter(key, next);
                          }}
                        />
                      </label>
                    );
                  })}
                </div>
              )}

              <details className="advanced-disclosure">
                <summary>Advanced parameter JSON</summary>
                <textarea
                  rows={12}
                  value={parameterText}
                  onChange={(event) => setParameterText(event.target.value)}
                  spellCheck={false}
                />
                <div className="button-row">
                  <button type="button" onClick={applyParameters}>
                    Apply JSON
                  </button>
                </div>
              </details>
            </>
          ) : (
            <p>Select Configure on a node to edit its parameters.</p>
          )}
        </div>

        <div className="panel-card">
          <h5>Connections</h5>
          {currentGraph.edges.length ? (
            <ul className="workflow-connection-list">
              {currentGraph.edges.map((edge) => (
                <li key={edge.edge_id}>
                  <code>
                    {edge.source_node_id}.{edge.source_port_id} →{" "}
                    {edge.target_node_id}.{edge.target_port_id}
                  </code>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      emit({
                        ...currentGraph,
                        edges: currentGraph.edges.filter(
                          (candidate) => candidate.edge_id !== edge.edge_id,
                        ),
                      })
                    }
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>
              No connections yet. Select an output port, then a compatible input
              port.
            </p>
          )}
          {feedbackLoop && (
            <div className="workflow-feedback-legend">
              <strong>Iteration cue</strong>
              <p>
                {feedbackLoop.from_node_id} ⇢ {feedbackLoop.to_node_id}
              </p>
              <small>
                Dashed feedback cues never create a cyclic execution edge.
              </small>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
