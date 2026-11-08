import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  createAnatomyRevision,
  createAnatomySchema,
  getAnatomySchema,
  listAnatomySchemas,
  type AnatomyLandmarkDefinition,
  type AnatomySchemaRevision,
  type AnatomySkeletonEdge,
} from "./anatomyApi";

interface AnatomySkeletonDesignerProps {
  projectId: string;
  onSchemaSelected?: (schema: AnatomySchemaRevision) => void;
}

function emptyLandmark(index: number): AnatomyLandmarkDefinition {
  return {
    id: `landmark_${index + 1}`,
    name: `Landmark ${index + 1}`,
    description: null,
    group: null,
    repeat_group: null,
    repeat_index: null,
    symmetric_with: null,
    required: true,
  };
}

function cleanedLandmark(
  landmark: AnatomyLandmarkDefinition,
): AnatomyLandmarkDefinition {
  return {
    id: landmark.id.trim(),
    name: landmark.name.trim(),
    required: landmark.required,
    ...(landmark.description?.trim()
      ? { description: landmark.description.trim() }
      : {}),
    ...(landmark.group?.trim() ? { group: landmark.group.trim() } : {}),
    ...(landmark.repeat_group?.trim()
      ? {
          repeat_group: landmark.repeat_group.trim(),
          repeat_index: landmark.repeat_index ?? 0,
        }
      : {}),
    ...(landmark.symmetric_with
      ? { symmetric_with: landmark.symmetric_with }
      : {}),
  };
}

export function AnatomySkeletonDesigner({
  projectId,
  onSchemaSelected,
}: AnatomySkeletonDesignerProps) {
  const queryClient = useQueryClient();
  const schemasQuery = useQuery({
    queryKey: ["pose_anatomy_schemas", projectId],
    queryFn: ({ signal }) => listAnatomySchemas(projectId, signal),
  });
  const [selectedId, setSelectedId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [landmarks, setLandmarks] = useState<AnatomyLandmarkDefinition[]>([]);
  const [edges, setEdges] = useState<AnatomySkeletonEdge[]>([]);
  const [edgeFrom, setEdgeFrom] = useState("");
  const [edgeTo, setEdgeTo] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const historyQuery = useQuery({
    queryKey: ["pose_anatomy_schema", selectedId],
    queryFn: ({ signal }) => getAnatomySchema(selectedId, signal),
    enabled: Boolean(selectedId),
  });

  const selectedSchema = (schemasQuery.data ?? []).find(
    (item) => item.id === selectedId,
  );

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        landmarks: landmarks.map(cleanedLandmark),
        edges,
      };
      return selectedId
        ? createAnatomyRevision(selectedId, payload)
        : createAnatomySchema(projectId, {
            name: templateName.trim(),
            ...payload,
          });
    },
    onSuccess: async (schema) => {
      setSelectedId(schema.id);
      setTemplateName(schema.name);
      setLandmarks(schema.landmarks);
      setEdges(schema.edges);
      setMessage(`Saved revision ${schema.revision}`);
      await queryClient.invalidateQueries({
        queryKey: ["pose_anatomy_schemas", projectId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["pose_anatomy_schema", schema.id],
      });
      onSchemaSelected?.(schema);
    },
    onError: (error) => {
      setMessage(
        `Could not save anatomy: ${error instanceof Error ? error.message : String(error)}`,
      );
    },
  });

  const preview = useMemo(
    () =>
      landmarks.map((landmark, index) => {
        const angle = (index / Math.max(landmarks.length, 1)) * Math.PI * 2;
        return {
          landmark,
          x: 160 + Math.cos(angle - Math.PI / 2) * 110,
          y: 140 + Math.sin(angle - Math.PI / 2) * 100,
        };
      }),
    [landmarks],
  );
  const pointById = new Map(preview.map((item) => [item.landmark.id, item]));

  function selectSchema(id: string) {
    setSelectedId(id);
    setMessage(null);
    if (!id) {
      setTemplateName("");
      setLandmarks([]);
      setEdges([]);
      return;
    }
    const schema = (schemasQuery.data ?? []).find((item) => item.id === id);
    if (schema) {
      setTemplateName(schema.name);
      setLandmarks(schema.landmarks.map((item) => ({ ...item })));
      setEdges(schema.edges.map((item) => ({ ...item })));
      onSchemaSelected?.(schema);
    }
  }

  function updateLandmark(
    index: number,
    patch: Partial<AnatomyLandmarkDefinition>,
  ) {
    setLandmarks((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    );
    setMessage(null);
  }

  function moveLandmark(index: number, offset: number) {
    setLandmarks((current) => {
      const target = index + offset;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setMessage(null);
  }

  function removeLandmark(index: number) {
    const removedId = landmarks[index]?.id;
    setLandmarks((current) =>
      current.filter((_, itemIndex) => itemIndex !== index),
    );
    setEdges((current) =>
      current.filter(
        (edge) => edge.from_id !== removedId && edge.to_id !== removedId,
      ),
    );
    setLandmarks((current) =>
      current.map((item) =>
        item.symmetric_with === removedId
          ? { ...item, symmetric_with: null }
          : item,
      ),
    );
  }

  function addEdge() {
    if (!edgeFrom || !edgeTo || edgeFrom === edgeTo) return;
    const duplicate = edges.some(
      (edge) =>
        (edge.from_id === edgeFrom && edge.to_id === edgeTo) ||
        (edge.from_id === edgeTo && edge.to_id === edgeFrom),
    );
    if (!duplicate)
      setEdges((current) => [...current, { from_id: edgeFrom, to_id: edgeTo }]);
  }

  const saveDisabled =
    saveMutation.isPending ||
    landmarks.length === 0 ||
    landmarks.some((item) => !item.id.trim() || !item.name.trim()) ||
    (!selectedId && !templateName.trim());

  return (
    <section
      className="management-card"
      data-testid="anatomy-skeleton-designer"
    >
      <div className="workspace-section-heading">
        <div>
          <p className="eyebrow">Pose anatomy</p>
          <h3>Anatomical skeleton designer</h3>
          <p className="muted-copy">
            Stable IDs protect annotation and checkpoint meaning; names and
            graph structure change only through explicit revisions.
          </p>
        </div>
      </div>

      <label>
        Saved template
        <select
          aria-label="Saved template"
          value={selectedId}
          onChange={(event) => selectSchema(event.target.value)}
        >
          <option value="">Create a new template</option>
          {(schemasQuery.data ?? []).map((schema) => (
            <option key={schema.id} value={schema.id}>
              {schema.name} · revision {schema.revision}
            </option>
          ))}
        </select>
      </label>
      {schemasQuery.isLoading && <p>Loading anatomy templates…</p>}
      {schemasQuery.isError && (
        <p role="alert">Could not load anatomy templates.</p>
      )}
      {!schemasQuery.isLoading && (schemasQuery.data ?? []).length === 0 && (
        <p>No saved anatomy templates yet.</p>
      )}
      <label>
        Template name
        <input
          aria-label="Template name"
          value={templateName}
          disabled={Boolean(selectedId)}
          onChange={(event) => setTemplateName(event.target.value)}
        />
      </label>
      {selectedSchema && (
        <>
          <p className="annotation-helper">
            Editing revision {selectedSchema.revision} · integrity{" "}
            {selectedSchema.content_hash.slice(0, 12)}…
          </p>
          <details>
            <summary>Revision history</summary>
            {historyQuery.isLoading && <p>Loading revision history…</p>}
            {historyQuery.isError && (
              <p role="alert">Could not load revision history.</p>
            )}
            <ol aria-label="Anatomy revision history">
              {(historyQuery.data?.revisions ?? []).map((revision) => (
                <li key={revision.revision}>
                  Revision {revision.revision} · {revision.keypoint_count}{" "}
                  landmarks · {revision.content_hash.slice(0, 12)}… ·{" "}
                  {new Date(revision.created_at).toLocaleString()}
                </li>
              ))}
            </ol>
          </details>
        </>
      )}

      <div className="annotation-selection-list">
        {landmarks.map((landmark, index) => (
          <fieldset key={`${landmark.id}-${index}`}>
            <legend>Landmark {index + 1}</legend>
            <label>
              Stable landmark ID
              <input
                aria-label="Stable landmark ID"
                value={landmark.id}
                onChange={(event) =>
                  updateLandmark(index, { id: event.target.value })
                }
              />
            </label>
            <label>
              Anatomical name
              <input
                aria-label="Anatomical name"
                value={landmark.name}
                onChange={(event) =>
                  updateLandmark(index, { name: event.target.value })
                }
              />
            </label>
            <label>
              Description
              <input
                aria-label="Description"
                value={landmark.description ?? ""}
                onChange={(event) =>
                  updateLandmark(index, { description: event.target.value })
                }
              />
            </label>
            <label>
              Anatomical group
              <input
                aria-label="Anatomical group"
                value={landmark.group ?? ""}
                onChange={(event) =>
                  updateLandmark(index, { group: event.target.value })
                }
              />
            </label>
            <label>
              Repeated structure
              <input
                aria-label="Repeated structure"
                value={landmark.repeat_group ?? ""}
                onChange={(event) =>
                  updateLandmark(index, { repeat_group: event.target.value })
                }
              />
            </label>
            <label>
              Repeat index
              <input
                aria-label="Repeat index"
                type="number"
                min={0}
                value={landmark.repeat_index ?? ""}
                onChange={(event) =>
                  updateLandmark(index, {
                    repeat_index:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  })
                }
              />
            </label>
            <label>
              Symmetric partner
              <select
                aria-label="Symmetric partner"
                value={landmark.symmetric_with ?? ""}
                onChange={(event) =>
                  updateLandmark(index, {
                    symmetric_with: event.target.value || null,
                  })
                }
              >
                <option value="">None</option>
                {landmarks
                  .filter((candidate) => candidate.id !== landmark.id)
                  .map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.name} ({candidate.id})
                    </option>
                  ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={landmark.required}
                onChange={(event) =>
                  updateLandmark(index, { required: event.target.checked })
                }
              />
              Required landmark
            </label>
            <button
              type="button"
              aria-label="Move landmark up"
              onClick={() => moveLandmark(index, -1)}
              disabled={index === 0}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label="Move landmark down"
              onClick={() => moveLandmark(index, 1)}
              disabled={index === landmarks.length - 1}
            >
              ↓
            </button>
            <button
              type="button"
              aria-label="Remove landmark"
              onClick={() => removeLandmark(index)}
            >
              Remove
            </button>
          </fieldset>
        ))}
      </div>
      <button
        type="button"
        onClick={() =>
          setLandmarks((current) => [...current, emptyLandmark(current.length)])
        }
      >
        Add landmark
      </button>

      <div className="annotation-control-grid">
        <label>
          Connection start
          <select
            aria-label="Connection start"
            value={edgeFrom}
            onChange={(event) => setEdgeFrom(event.target.value)}
          >
            <option value="">Choose landmark</option>
            {landmarks.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Connection end
          <select
            aria-label="Connection end"
            value={edgeTo}
            onChange={(event) => setEdgeTo(event.target.value)}
          >
            <option value="">Choose landmark</option>
            {landmarks.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={addEdge}>
          Add connection
        </button>
      </div>
      <ul>
        {edges.map((edge) => (
          <li key={`${edge.from_id}-${edge.to_id}`}>
            {edge.from_id} ↔ {edge.to_id}{" "}
            <button
              type="button"
              aria-label={`Remove connection ${edge.from_id} ${edge.to_id}`}
              onClick={() =>
                setEdges((current) => current.filter((item) => item !== edge))
              }
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <svg
        viewBox="0 0 320 280"
        role="img"
        aria-label="Skeleton graph preview"
        style={{ maxWidth: 520 }}
      >
        {edges.map((edge) => {
          const from = pointById.get(edge.from_id);
          const to = pointById.get(edge.to_id);
          return from && to ? (
            <line
              key={`${edge.from_id}-${edge.to_id}`}
              data-testid={`anatomy-edge-${edge.from_id}-${edge.to_id}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke="currentColor"
            />
          ) : null;
        })}
        {preview.map(({ landmark, x, y }) => (
          <g
            key={landmark.id}
            data-testid={`anatomy-preview-landmark-${landmark.id}`}
          >
            <circle cx={x} cy={y} r="8" fill="currentColor" />
            <text x={x + 11} y={y + 4}>
              {landmark.name}
            </text>
          </g>
        ))}
      </svg>

      <button
        type="button"
        disabled={saveDisabled}
        onClick={() => {
          setMessage(null);
          saveMutation.mutate();
        }}
      >
        {selectedId ? "Save new revision" : "Save template"}
      </button>
      {message && (
        <p role={saveMutation.isError ? "alert" : "status"}>{message}</p>
      )}
    </section>
  );
}
