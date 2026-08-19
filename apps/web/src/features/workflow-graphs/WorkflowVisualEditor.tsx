import { useEffect, useMemo, useState } from "react";

import type { WorkflowNodeDefinition } from "./workflowGraphApi";

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
}

interface PendingConnection {
  nodeId: string;
  portId: string;
  dataTypes: string[];
}

const NODE_WIDTH = 240;
const NODE_HEADER_HEIGHT = 52;
const CANVAS_WIDTH = 1800;
const CANVAS_HEIGHT = 900;

function asGraph(value: Record<string, unknown>): GraphShape | null {
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges)) return null;
  return value as unknown as GraphShape;
}

function slug(value: string): string {
  return value
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function defaultPosition(index: number): { x: number; y: number } {
  return {
    x: 40 + (index % 5) * 300,
    y: 40 + Math.floor(index / 5) * 220,
  };
}

function portCompatible(sourceTypes: string[], targetTypes: string[]): boolean {
  return sourceTypes.some((item) => targetTypes.includes(item));
}

export function WorkflowVisualEditor({
  graph: rawGraph,
  registry,
  onChange,
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
  const selectedNode = graph?.nodes.find(
    (item) => item.node_id === selectedNodeId,
  );

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
                x: Math.max(0, Math.min(CANVAS_WIDTH - NODE_WIDTH, x)),
                y: Math.max(0, Math.min(CANVAS_HEIGHT - 160, y)),
              },
            }
          : resolved;
      }),
    });
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

  function applyParameters(): void {
    if (!selectedNode) return;
    try {
      const value = JSON.parse(parameterText) as unknown;
      if (!value || Array.isArray(value) || typeof value !== "object") {
        throw new Error("Parameters must be a JSON object.");
      }
      emit({
        ...currentGraph,
        nodes: currentGraph.nodes.map((node) =>
          node.node_id === selectedNode.node_id
            ? { ...node, parameters: value as Record<string, unknown> }
            : node,
        ),
      });
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

  return (
    <div>
      <div className="button-row" style={{ alignItems: "center" }}>
        <label>
          Add node{" "}
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
        {pending && (
          <button
            type="button"
            className="secondary"
            onClick={() => setPending(null)}
          >
            Cancel connection
          </button>
        )}
      </div>
      {message && <p className="muted-copy">{message}</p>}

      <div
        style={{
          border: "1px solid var(--border-color, #777)",
          borderRadius: 8,
          overflow: "auto",
          minHeight: 560,
          maxHeight: 720,
          position: "relative",
        }}
      >
        <div
          style={{
            width: CANVAS_WIDTH,
            height: CANVAS_HEIGHT,
            position: "relative",
            backgroundImage:
              "linear-gradient(to right, rgba(127,127,127,.12) 1px, transparent 1px), linear-gradient(to bottom, rgba(127,127,127,.12) 1px, transparent 1px)",
            backgroundSize: "24px 24px",
          }}
        >
          <svg
            width={CANVAS_WIDTH}
            height={CANVAS_HEIGHT}
            style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
          >
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
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  opacity={0.55}
                />
              );
            })}
          </svg>

          {currentGraph.nodes.map((rawNode, index) => {
            const node = positionedNode(rawNode, index);
            const position = node.position ?? defaultPosition(index);
            const definition = definitions.get(node.node_type);
            return (
              <div
                key={node.node_id}
                style={{
                  position: "absolute",
                  left: position.x,
                  top: position.y,
                  width: NODE_WIDTH,
                  border:
                    selectedNodeId === node.node_id
                      ? "2px solid currentColor"
                      : "1px solid #777",
                  borderRadius: 8,
                  background: "var(--panel-background, Canvas)",
                  boxShadow: "0 4px 16px rgba(0,0,0,.12)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    minHeight: NODE_HEADER_HEIGHT,
                    padding: "8px 10px",
                    cursor: "grab",
                    background: "rgba(127,127,127,.12)",
                  }}
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
                  <strong>{definition?.display_name ?? node.node_type}</strong>
                  <br />
                  <small>{node.node_id}</small>
                </div>
                <div style={{ padding: 8 }}>
                  <div>
                    {definition?.input_ports.map((port) => (
                      <button
                        key={`in-${port.port_id}`}
                        type="button"
                        className="secondary"
                        style={{ margin: 2, fontSize: 11 }}
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
                        ◀ {port.port_id}
                      </button>
                    ))}
                  </div>
                  <div>
                    {definition?.output_ports.map((port) => (
                      <button
                        key={`out-${port.port_id}`}
                        type="button"
                        className="secondary"
                        style={{ margin: 2, fontSize: 11 }}
                        title={`Output: ${port.accepted_types.join(", ")}`}
                        onClick={() =>
                          beginConnection(
                            node.node_id,
                            port.port_id,
                            port.accepted_types,
                          )
                        }
                      >
                        {port.port_id} ▶
                      </button>
                    ))}
                  </div>
                  <div className="button-row" style={{ marginTop: 6 }}>
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

      <div className="feature-grid" style={{ marginTop: 12 }}>
        <div className="panel-card">
          <h5>Selected node parameters</h5>
          {selectedNode ? (
            <>
              <p>
                <strong>{selectedNode.node_id}</strong> ·{" "}
                {selectedNode.node_type}
              </p>
              <textarea
                rows={12}
                value={parameterText}
                onChange={(event) => setParameterText(event.target.value)}
                spellCheck={false}
              />
              <div className="button-row">
                <button type="button" onClick={applyParameters}>
                  Apply parameters
                </button>
              </div>
            </>
          ) : (
            <p>Select Configure on a node to edit its parameter JSON.</p>
          )}
        </div>
        <div className="panel-card">
          <h5>Connections</h5>
          {currentGraph.edges.length ? (
            <ul>
              {currentGraph.edges.map((edge) => (
                <li key={edge.edge_id}>
                  <code>
                    {edge.source_node_id}.{edge.source_port_id} →{" "}
                    {edge.target_node_id}.{edge.target_port_id}
                  </code>{" "}
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
        </div>
      </div>
    </div>
  );
}
