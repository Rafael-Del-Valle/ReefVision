import {
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { WorkflowNodeDefinition } from "./api";
import "./workflowGraphEditor.css";

export interface EditableWorkflowNode {
  id: string;
  node_type: string;
  label?: string | null;
  configuration: Record<string, unknown>;
}

export interface EditableWorkflowEdge {
  source_node_id: string;
  source_port: string;
  target_node_id: string;
  target_port: string;
}

export interface EditableWorkflow {
  name: string;
  nodes: EditableWorkflowNode[];
  edges: EditableWorkflowEdge[];
}

interface Position {
  x: number;
  y: number;
}

interface PendingConnection {
  nodeId: string;
  port: string;
  dataType: string;
}

interface NodeDrag {
  nodeId: string;
  offsetX: number;
  offsetY: number;
}

const NODE_WIDTH = 230;
const NODE_HEADER_HEIGHT = 48;
const PORT_ROW_HEIGHT = 28;
const DEFAULT_CANVAS_WIDTH = 1200;
const DEFAULT_CANVAS_HEIGHT = 720;

function positionOf(node: EditableWorkflowNode, index: number): Position {
  const value = node.configuration.__ui_position;
  if (
    value &&
    typeof value === "object" &&
    typeof (value as Position).x === "number" &&
    typeof (value as Position).y === "number"
  ) {
    return value as Position;
  }
  return {
    x: 40 + (index % 4) * 270,
    y: 50 + Math.floor(index / 4) * 220,
  };
}

function withPosition(
  node: EditableWorkflowNode,
  position: Position,
): EditableWorkflowNode {
  return {
    ...node,
    configuration: {
      ...node.configuration,
      __ui_position: {
        x: Math.round(position.x),
        y: Math.round(position.y),
      },
    },
  };
}

function nextNodeId(nodeType: string, nodes: EditableWorkflowNode[]): string {
  const normalized = nodeType.replaceAll(/[^a-zA-Z0-9_-]/g, "-");
  const ids = new Set(nodes.map((node) => node.id));
  let suffix = 1;
  let candidate = normalized;
  while (ids.has(candidate)) {
    suffix += 1;
    candidate = `${normalized}-${suffix}`;
  }
  return candidate;
}

function nodeHeight(definition: WorkflowNodeDefinition | undefined): number {
  const rows = Math.max(
    definition?.inputs.length ?? 0,
    definition?.outputs.length ?? 0,
    1,
  );
  return NODE_HEADER_HEIGHT + rows * PORT_ROW_HEIGHT + 24;
}

function edgeKey(edge: EditableWorkflowEdge): string {
  return `${edge.source_node_id}:${edge.source_port}->${edge.target_node_id}:${edge.target_port}`;
}

export function WorkflowGraphEditor({
  workflow,
  definitions,
  onChange,
}: {
  workflow: EditableWorkflow;
  definitions: WorkflowNodeDefinition[];
  onChange: (workflow: EditableWorkflow) => void;
}) {
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [drag, setDrag] = useState<NodeDrag | null>(null);
  const [pendingConnection, setPendingConnection] =
    useState<PendingConnection | null>(null);
  const [configurationText, setConfigurationText] = useState("{}");
  const [configurationError, setConfigurationError] = useState<string | null>(null);
  const [edgeSourceNode, setEdgeSourceNode] = useState("");
  const [edgeSourcePort, setEdgeSourcePort] = useState("");
  const [edgeTargetNode, setEdgeTargetNode] = useState("");
  const [edgeTargetPort, setEdgeTargetPort] = useState("");

  const definitionByType = useMemo(
    () => new Map(definitions.map((definition) => [definition.node_type, definition])),
    [definitions],
  );
  const nodeById = useMemo(
    () => new Map(workflow.nodes.map((node) => [node.id, node])),
    [workflow.nodes],
  );
  const positionById = useMemo(
    () =>
      new Map(
        workflow.nodes.map((node, index) => [node.id, positionOf(node, index)]),
      ),
    [workflow.nodes],
  );
  const selectedNode = selectedNodeId
    ? (nodeById.get(selectedNodeId) ?? null)
    : null;

  useEffect(() => {
    setConfigurationText(
      JSON.stringify(selectedNode?.configuration ?? {}, null, 2),
    );
    setConfigurationError(null);
  }, [selectedNode]);

  const updateNode = useCallback(
    (nodeId: string, updater: (node: EditableWorkflowNode) => EditableWorkflowNode) => {
      onChange({
        ...workflow,
        nodes: workflow.nodes.map((node) =>
          node.id === nodeId ? updater(node) : node,
        ),
      });
    },
    [onChange, workflow],
  );

  const removeNode = useCallback(
    (nodeId: string) => {
      onChange({
        ...workflow,
        nodes: workflow.nodes.filter((node) => node.id !== nodeId),
        edges: workflow.edges.filter(
          (edge) =>
            edge.source_node_id !== nodeId && edge.target_node_id !== nodeId,
        ),
      });
      setSelectedNodeId((current) => (current === nodeId ? null : current));
      setPendingConnection((current) =>
        current?.nodeId === nodeId ? null : current,
      );
    },
    [onChange, workflow],
  );

  useEffect(() => {
    if (!drag) return;
    const move = (event: PointerEvent) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const bounds = canvas.getBoundingClientRect();
      const node = nodeById.get(drag.nodeId);
      if (!node) return;
      const definition = definitionByType.get(node.node_type);
      const maximumX = Math.max(0, bounds.width - NODE_WIDTH);
      const maximumY = Math.max(0, bounds.height - nodeHeight(definition));
      updateNode(drag.nodeId, (current) =>
        withPosition(current, {
          x: Math.max(0, Math.min(maximumX, event.clientX - bounds.left - drag.offsetX)),
          y: Math.max(0, Math.min(maximumY, event.clientY - bounds.top - drag.offsetY)),
        }),
      );
    };
    const finish = () => setDrag(null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
    };
  }, [definitionByType, drag, nodeById, updateNode]);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (!selectedNodeId) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        removeNode(selectedNodeId);
        return;
      }
      const delta: Position = { x: 0, y: 0 };
      const amount = event.shiftKey ? 25 : 5;
      if (event.key === "ArrowLeft") delta.x = -amount;
      if (event.key === "ArrowRight") delta.x = amount;
      if (event.key === "ArrowUp") delta.y = -amount;
      if (event.key === "ArrowDown") delta.y = amount;
      if (!delta.x && !delta.y) return;
      event.preventDefault();
      updateNode(selectedNodeId, (node) => {
        const current = positionOf(
          node,
          workflow.nodes.findIndex((item) => item.id === selectedNodeId),
        );
        return withPosition(node, {
          x: Math.max(0, current.x + delta.x),
          y: Math.max(0, current.y + delta.y),
        });
      });
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [removeNode, selectedNodeId, updateNode, workflow.nodes]);

  function addNode(nodeType: string, position?: Position) {
    const definition = definitionByType.get(nodeType);
    const id = nextNodeId(nodeType, workflow.nodes);
    const node = withPosition(
      {
        id,
        node_type: nodeType,
        label: definition?.display_name ?? nodeType,
        configuration: {},
      },
      position ?? { x: 50, y: 50 },
    );
    onChange({ ...workflow, nodes: [...workflow.nodes, node] });
    setSelectedNodeId(id);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData("application/x-reefvision-node");
    if (!nodeType) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    addNode(nodeType, {
      x: Math.max(0, event.clientX - bounds.left - NODE_WIDTH / 2),
      y: Math.max(0, event.clientY - bounds.top - NODE_HEADER_HEIGHT / 2),
    });
  }

  function beginNodeDrag(
    event: ReactPointerEvent<HTMLDivElement>,
    nodeId: string,
  ) {
    if (event.button !== 0) return;
    const position = positionById.get(nodeId);
    const canvas = canvasRef.current;
    if (!position || !canvas) return;
    const bounds = canvas.getBoundingClientRect();
    setSelectedNodeId(nodeId);
    setDrag({
      nodeId,
      offsetX: event.clientX - bounds.left - position.x,
      offsetY: event.clientY - bounds.top - position.y,
    });
  }

  function connectTo(nodeId: string, port: string, dataType: string) {
    if (!pendingConnection) return;
    if (pendingConnection.nodeId === nodeId) {
      setPendingConnection(null);
      return;
    }
    if (pendingConnection.dataType !== dataType) {
      return;
    }
    const edge: EditableWorkflowEdge = {
      source_node_id: pendingConnection.nodeId,
      source_port: pendingConnection.port,
      target_node_id: nodeId,
      target_port: port,
    };
    const nextEdges = workflow.edges.filter(
      (item) =>
        !(
          item.target_node_id === nodeId &&
          item.target_port === port
        ),
    );
    if (!nextEdges.some((item) => edgeKey(item) === edgeKey(edge))) {
      nextEdges.push(edge);
    }
    onChange({ ...workflow, edges: nextEdges });
    setPendingConnection(null);
  }

  function addAccessibleEdge() {
    if (!edgeSourceNode || !edgeSourcePort || !edgeTargetNode || !edgeTargetPort) {
      return;
    }
    const sourceDefinition = definitionByType.get(
      nodeById.get(edgeSourceNode)?.node_type ?? "",
    );
    const targetDefinition = definitionByType.get(
      nodeById.get(edgeTargetNode)?.node_type ?? "",
    );
    const source = sourceDefinition?.outputs.find(
      (port) => port.name === edgeSourcePort,
    );
    const target = targetDefinition?.inputs.find(
      (port) => port.name === edgeTargetPort,
    );
    if (!source || !target || source.data_type !== target.data_type) return;
    const edge: EditableWorkflowEdge = {
      source_node_id: edgeSourceNode,
      source_port: edgeSourcePort,
      target_node_id: edgeTargetNode,
      target_port: edgeTargetPort,
    };
    const edges = workflow.edges.filter(
      (item) =>
        !(
          item.target_node_id === edgeTargetNode &&
          item.target_port === edgeTargetPort
        ),
    );
    if (!edges.some((item) => edgeKey(item) === edgeKey(edge))) edges.push(edge);
    onChange({ ...workflow, edges });
  }

  function saveConfiguration() {
    if (!selectedNodeId) return;
    try {
      const parsed = JSON.parse(configurationText) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Configuration must be a JSON object");
      }
      setConfigurationError(null);
      updateNode(selectedNodeId, (node) => ({
        ...node,
        configuration: parsed as Record<string, unknown>,
      }));
    } catch (error) {
      setConfigurationError(
        error instanceof Error ? error.message : "Configuration JSON is invalid",
      );
    }
  }

  const sourcePorts = definitionByType.get(
    nodeById.get(edgeSourceNode)?.node_type ?? "",
  )?.outputs ?? [];
  const targetPorts = definitionByType.get(
    nodeById.get(edgeTargetNode)?.node_type ?? "",
  )?.inputs ?? [];

  return (
    <div className="workflow-graph-layout" data-testid="workflow-graph-editor">
      <aside className="workflow-graph-palette" aria-label="Workflow node palette">
        <h5>Node palette</h5>
        <p>Drag a node onto the canvas or add it with the keyboard-accessible button.</p>
        {definitions.map((definition) => (
          <div
            key={definition.node_type}
            className="workflow-palette-item"
            draggable
            onDragStart={(event) => {
              event.dataTransfer.setData(
                "application/x-reefvision-node",
                definition.node_type,
              );
              event.dataTransfer.effectAllowed = "copy";
            }}
          >
            <strong>{definition.display_name}</strong>
            <small>
              {definition.inputs.length} in · {definition.outputs.length} out
            </small>
            <button type="button" onClick={() => addNode(definition.node_type)}>
              Add
            </button>
          </div>
        ))}
      </aside>

      <div className="workflow-graph-center">
        <div className="workflow-graph-toolbar">
          <label>
            Workflow name
            <input
              value={workflow.name}
              onChange={(event) =>
                onChange({ ...workflow, name: event.target.value })
              }
            />
          </label>
          <span>{workflow.nodes.length} nodes · {workflow.edges.length} edges</span>
          {pendingConnection && (
            <button
              type="button"
              className="secondary"
              onClick={() => setPendingConnection(null)}
            >
              Cancel connection
            </button>
          )}
        </div>
        <div
          ref={canvasRef}
          className="workflow-graph-canvas"
          tabIndex={0}
          role="application"
          aria-label="Workflow graph canvas. Use the node palette to add nodes. Select a node and use arrow keys to move it."
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
          }}
          onDrop={handleDrop}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) setSelectedNodeId(null);
          }}
        >
          <svg
            className="workflow-edge-layer"
            viewBox={`0 0 ${canvasRef.current?.clientWidth ?? DEFAULT_CANVAS_WIDTH} ${canvasRef.current?.clientHeight ?? DEFAULT_CANVAS_HEIGHT}`}
            aria-hidden="true"
          >
            {workflow.edges.map((edge) => {
              const source = nodeById.get(edge.source_node_id);
              const target = nodeById.get(edge.target_node_id);
              if (!source || !target) return null;
              const sourceDefinition = definitionByType.get(source.node_type);
              const targetDefinition = definitionByType.get(target.node_type);
              const sourceIndex = Math.max(
                0,
                sourceDefinition?.outputs.findIndex(
                  (port) => port.name === edge.source_port,
                ) ?? 0,
              );
              const targetIndex = Math.max(
                0,
                targetDefinition?.inputs.findIndex(
                  (port) => port.name === edge.target_port,
                ) ?? 0,
              );
              const sourcePosition = positionById.get(source.id) ?? { x: 0, y: 0 };
              const targetPosition = positionById.get(target.id) ?? { x: 0, y: 0 };
              const x1 = sourcePosition.x + NODE_WIDTH;
              const y1 =
                sourcePosition.y + NODE_HEADER_HEIGHT + sourceIndex * PORT_ROW_HEIGHT + 14;
              const x2 = targetPosition.x;
              const y2 =
                targetPosition.y + NODE_HEADER_HEIGHT + targetIndex * PORT_ROW_HEIGHT + 14;
              const middle = Math.max(50, Math.abs(x2 - x1) / 2);
              return (
                <path
                  key={edgeKey(edge)}
                  d={`M ${x1} ${y1} C ${x1 + middle} ${y1}, ${x2 - middle} ${y2}, ${x2} ${y2}`}
                />
              );
            })}
          </svg>

          {workflow.nodes.map((node, nodeIndex) => {
            const definition = definitionByType.get(node.node_type);
            const position = positionById.get(node.id) ?? positionOf(node, nodeIndex);
            return (
              <article
                key={node.id}
                className={`workflow-node ${selectedNodeId === node.id ? "selected" : ""}`}
                style={{ left: position.x, top: position.y, width: NODE_WIDTH }}
                data-testid={`workflow-node-${node.id}`}
                aria-label={`${node.label || definition?.display_name || node.node_type} workflow node`}
              >
                <div
                  className="workflow-node-header"
                  onPointerDown={(event) => beginNodeDrag(event, node.id)}
                >
                  <button
                    type="button"
                    className="workflow-node-select"
                    onClick={() => setSelectedNodeId(node.id)}
                  >
                    <strong>{node.label || definition?.display_name || node.node_type}</strong>
                    <small>{node.id}</small>
                  </button>
                  <button
                    type="button"
                    className="danger-ghost"
                    aria-label={`Delete ${node.id}`}
                    onClick={() => removeNode(node.id)}
                  >
                    ×
                  </button>
                </div>
                <div className="workflow-node-ports">
                  <div>
                    {(definition?.inputs ?? []).map((port) => (
                      <button
                        key={port.name}
                        type="button"
                        className="workflow-port input-port"
                        title={`${port.name}: ${port.data_type}`}
                        disabled={
                          Boolean(pendingConnection) &&
                          pendingConnection?.dataType !== port.data_type
                        }
                        onClick={() => connectTo(node.id, port.name, port.data_type)}
                      >
                        <span aria-hidden="true" />
                        {port.name}
                      </button>
                    ))}
                  </div>
                  <div>
                    {(definition?.outputs ?? []).map((port) => (
                      <button
                        key={port.name}
                        type="button"
                        className={`workflow-port output-port ${pendingConnection?.nodeId === node.id && pendingConnection.port === port.name ? "active" : ""}`}
                        title={`${port.name}: ${port.data_type}`}
                        onClick={() =>
                          setPendingConnection({
                            nodeId: node.id,
                            port: port.name,
                            dataType: port.data_type,
                          })
                        }
                      >
                        {port.name}
                        <span aria-hidden="true" />
                      </button>
                    ))}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </div>

      <aside className="workflow-graph-inspector" aria-label="Workflow inspector">
        <h5>Node inspector</h5>
        {selectedNode ? (
          <>
            <label>
              Node ID
              <input value={selectedNode.id} readOnly />
            </label>
            <label>
              Label
              <input
                value={selectedNode.label ?? ""}
                onChange={(event) =>
                  updateNode(selectedNode.id, (node) => ({
                    ...node,
                    label: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Configuration JSON
              <textarea
                rows={16}
                value={configurationText}
                onChange={(event) => setConfigurationText(event.target.value)}
              />
            </label>
            <button type="button" onClick={saveConfiguration}>
              Apply configuration
            </button>
            {configurationError && (
              <p className="form-error">{configurationError}</p>
            )}
          </>
        ) : (
          <p>Select a node to edit its label, configuration, and position.</p>
        )}

        <hr />
        <h5>Accessible edge builder</h5>
        <label>
          Source node
          <select
            value={edgeSourceNode}
            onChange={(event) => {
              setEdgeSourceNode(event.target.value);
              setEdgeSourcePort("");
            }}
          >
            <option value="">Choose source</option>
            {workflow.nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source output
          <select
            value={edgeSourcePort}
            onChange={(event) => setEdgeSourcePort(event.target.value)}
          >
            <option value="">Choose output</option>
            {sourcePorts.map((port) => (
              <option key={port.name} value={port.name}>
                {port.name} · {port.data_type}
              </option>
            ))}
          </select>
        </label>
        <label>
          Target node
          <select
            value={edgeTargetNode}
            onChange={(event) => {
              setEdgeTargetNode(event.target.value);
              setEdgeTargetPort("");
            }}
          >
            <option value="">Choose target</option>
            {workflow.nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Target input
          <select
            value={edgeTargetPort}
            onChange={(event) => setEdgeTargetPort(event.target.value)}
          >
            <option value="">Choose input</option>
            {targetPorts.map((port) => (
              <option key={port.name} value={port.name}>
                {port.name} · {port.data_type}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!edgeSourcePort || !edgeTargetPort}
          onClick={addAccessibleEdge}
        >
          Add typed edge
        </button>

        <div className="workflow-edge-list">
          {workflow.edges.map((edge) => (
            <div key={edgeKey(edge)}>
              <small>
                {edge.source_node_id}.{edge.source_port} → {edge.target_node_id}.
                {edge.target_port}
              </small>
              <button
                type="button"
                className="danger-ghost"
                aria-label={`Remove edge ${edgeKey(edge)}`}
                onClick={() =>
                  onChange({
                    ...workflow,
                    edges: workflow.edges.filter(
                      (item) => edgeKey(item) !== edgeKey(edge),
                    ),
                  })
                }
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
