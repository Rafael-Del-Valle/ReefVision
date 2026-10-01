import {
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  fitTransform,
  screenToImage,
  zoomAtPoint,
} from "../annotation-editor/geometry";
import type {
  ImageSize,
  Point,
  ViewportTransform,
} from "../annotation-editor/types";
import {
  addPoseObservation,
  buildPoseSaveRequest,
  clonePose,
  movePoseObservation,
  placedCount,
  poseSkeletonSegments,
  removePoseObservation,
  schemaForPose,
  setPoseObservationStatus,
  validatePoseAgainstSchema,
} from "./poseEditorState";
import type {
  PoseInstance,
  PoseLandmarkSchema,
  PoseLandmarkStatus,
  PoseSaveRequest,
} from "./types";

type PoseEditorTool = "landmark" | "pan";
type PoseSaveState = "idle" | "dirty" | "saving" | "saved" | "error";

interface PoseAnnotationEditorProps {
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  schema: PoseLandmarkSchema;
  schemaRevisions?: PoseLandmarkSchema[];
  poses: PoseInstance[];
  initialPoseId?: string;
  viewportWidth?: number;
  viewportHeight?: number;
  onSave: (request: PoseSaveRequest) => Promise<PoseInstance>;
  onCreatePose?: (schema: PoseLandmarkSchema) => Promise<PoseInstance>;
}

interface PanInteraction {
  start: Point;
  initialView: ViewportTransform;
}

interface DragInteraction {
  poseId: string;
  observationId: string;
}

function indexPoses(poses: PoseInstance[]): Record<string, PoseInstance> {
  return Object.fromEntries(poses.map((pose) => [pose.id, clonePose(pose)]));
}

function makeObservationId(): string {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `pose-observation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function PoseAnnotationEditor({
  imageUrl,
  imageWidth,
  imageHeight,
  schema,
  schemaRevisions = [],
  poses,
  initialPoseId,
  viewportWidth = 900,
  viewportHeight = 600,
  onSave,
  onCreatePose,
}: PoseAnnotationEditorProps) {
  const imageSize: ImageSize = useMemo(
    () => ({ width: imageWidth, height: imageHeight }),
    [imageHeight, imageWidth],
  );
  const initialView = useMemo(
    () =>
      fitTransform(imageSize, {
        width: viewportWidth,
        height: viewportHeight,
      }),
    [imageSize, viewportHeight, viewportWidth],
  );

  const [persistedById, setPersistedById] = useState<
    Record<string, PoseInstance>
  >(() => indexPoses(poses));
  const [draftsById, setDraftsById] = useState<Record<string, PoseInstance>>(
    () => indexPoses(poses),
  );
  const firstPoseId = initialPoseId ?? poses[0]?.id ?? "";
  const [poseIds, setPoseIds] = useState(() => poses.map((pose) => pose.id));
  const [selectedPoseId, setSelectedPoseId] = useState(firstPoseId);
  const [selectedObservationId, setSelectedObservationId] = useState<
    string | null
  >(null);
  const [activeLabel, setActiveLabel] = useState(schema.groups[0]?.name ?? "");
  const [tool, setTool] = useState<PoseEditorTool>("landmark");
  const [view, setView] = useState<ViewportTransform>(initialView);
  const [panInteraction, setPanInteraction] = useState<PanInteraction | null>(
    null,
  );
  const [dragInteraction, setDragInteraction] =
    useState<DragInteraction | null>(null);
  const [saveStateById, setSaveStateById] = useState<
    Record<string, PoseSaveState>
  >({});
  const [saveMessageById, setSaveMessageById] = useState<
    Record<string, string | null>
  >({});
  const [creatingPose, setCreatingPose] = useState(false);
  const [creationMessage, setCreationMessage] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const selectedPose = draftsById[selectedPoseId] ?? null;
  const persistedPose = persistedById[selectedPoseId] ?? null;
  const selectedSchema = selectedPose
    ? schemaForPose(selectedPose, schema, schemaRevisions)
    : null;
  const saveState = saveStateById[selectedPoseId] ?? "idle";
  const saveMessage = saveMessageById[selectedPoseId] ?? null;
  const effectiveActiveLabel =
    selectedSchema?.groups.some((group) => group.name === activeLabel) === true
      ? activeLabel
      : (selectedSchema?.groups[0]?.name ?? "");
  const selectedObservation =
    selectedPose?.observations.find(
      (observation) => observation.id === selectedObservationId,
    ) ?? null;
  const skeletonSegments = useMemo(
    () =>
      selectedPose && selectedSchema
        ? poseSkeletonSegments(selectedPose, selectedSchema)
        : [],
    [selectedPose, selectedSchema],
  );

  const setPoseDraft = (
    poseId: string,
    updater: (pose: PoseInstance) => PoseInstance,
  ) => {
    setDraftsById((current) => {
      const pose = current[poseId];
      if (!pose) {
        return current;
      }
      const next = updater(pose);
      if (next === pose) {
        return current;
      }
      return { ...current, [poseId]: next };
    });
    setSaveStateById((current) => ({ ...current, [poseId]: "dirty" }));
    setSaveMessageById((current) => ({ ...current, [poseId]: null }));
  };

  const localScreenPoint = (clientX: number, clientY: number): Point => {
    const svg = svgRef.current;
    if (!svg) {
      return { x: clientX, y: clientY };
    }
    const rect = svg.getBoundingClientRect();
    const scaleX = rect.width > 0 ? viewportWidth / rect.width : 1;
    const scaleY = rect.height > 0 ? viewportHeight / rect.height : 1;
    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY,
    };
  };

  const clientPointToImage = (clientX: number, clientY: number): Point =>
    screenToImage(localScreenPoint(clientX, clientY), view);

  const handleStagePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!selectedPose || !selectedSchema) {
      return;
    }
    if (tool === "pan") {
      setPanInteraction({
        start: localScreenPoint(event.clientX, event.clientY),
        initialView: view,
      });
      return;
    }

    const activeGroup = selectedSchema.groups.find(
      (group) => group.name === effectiveActiveLabel,
    );
    if (
      !activeGroup ||
      placedCount(selectedPose.observations, effectiveActiveLabel) >=
        activeGroup.count
    ) {
      return;
    }

    const point = clientPointToImage(event.clientX, event.clientY);
    if (
      point.x < 0 ||
      point.y < 0 ||
      point.x > imageSize.width ||
      point.y > imageSize.height
    ) {
      return;
    }

    setPoseDraft(selectedPose.id, (pose) =>
      addPoseObservation(
        pose,
        selectedSchema,
        effectiveActiveLabel,
        point,
        imageSize,
        makeObservationId(),
      ),
    );
  };

  const handleStagePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (panInteraction) {
      const current = localScreenPoint(event.clientX, event.clientY);
      setView({
        ...panInteraction.initialView,
        offsetX:
          panInteraction.initialView.offsetX +
          (current.x - panInteraction.start.x),
        offsetY:
          panInteraction.initialView.offsetY +
          (current.y - panInteraction.start.y),
      });
      return;
    }

    if (dragInteraction) {
      const point = clientPointToImage(event.clientX, event.clientY);
      setPoseDraft(dragInteraction.poseId, (pose) =>
        movePoseObservation(
          pose,
          dragInteraction.observationId,
          point,
          imageSize,
        ),
      );
    }
  };

  const handleStagePointerUp = () => {
    setPanInteraction(null);
    setDragInteraction(null);
  };

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const focus = localScreenPoint(event.clientX, event.clientY);
    const zoomFactor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    setView((current) =>
      zoomAtPoint(current, focus, current.scale * zoomFactor),
    );
  };

  const handleObservationPointerDown = (
    event: ReactPointerEvent<SVGCircleElement>,
    observationId: string,
  ) => {
    event.stopPropagation();
    if (!selectedPose) {
      return;
    }
    setSelectedObservationId(observationId);
    setDragInteraction({
      poseId: selectedPose.id,
      observationId,
    });
  };

  const handleDeleteSelected = () => {
    if (!selectedPose || !selectedObservationId) {
      return;
    }
    setPoseDraft(selectedPose.id, (pose) =>
      removePoseObservation(pose, selectedObservationId),
    );
    setSelectedObservationId(null);
  };

  const handleRevert = () => {
    if (!persistedPose) {
      return;
    }
    setDraftsById((current) => ({
      ...current,
      [persistedPose.id]: clonePose(persistedPose),
    }));
    setSelectedObservationId(null);
    setSaveStateById((current) => ({
      ...current,
      [persistedPose.id]: "idle",
    }));
    setSaveMessageById((current) => ({
      ...current,
      [persistedPose.id]: null,
    }));
  };

  const handleSave = async () => {
    if (!selectedPose || !persistedPose || !selectedSchema) {
      return;
    }

    const validationErrors = validatePoseAgainstSchema(
      selectedPose,
      selectedSchema,
    );
    if (validationErrors.length > 0) {
      setSaveStateById((current) => ({
        ...current,
        [selectedPose.id]: "error",
      }));
      setSaveMessageById((current) => ({
        ...current,
        [selectedPose.id]: validationErrors.join("; "),
      }));
      return;
    }

    const request = buildPoseSaveRequest(
      persistedPose,
      selectedPose,
      selectedSchema,
    );
    setSaveStateById((current) => ({
      ...current,
      [selectedPose.id]: "saving",
    }));
    setSaveMessageById((current) => ({
      ...current,
      [selectedPose.id]: null,
    }));

    try {
      const savedPose = await onSave(request);
      if (savedPose.id !== selectedPose.id) {
        throw new Error("Saved pose id did not match the edited pose");
      }
      const savedClone = clonePose(savedPose);
      setPersistedById((current) => ({
        ...current,
        [savedPose.id]: savedClone,
      }));
      setDraftsById((current) => ({
        ...current,
        [savedPose.id]: clonePose(savedClone),
      }));
      setSaveStateById((current) => ({
        ...current,
        [savedPose.id]: "saved",
      }));
      setSaveMessageById((current) => ({
        ...current,
        [savedPose.id]: `Saved revision ${savedPose.revision}`,
      }));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown save failure";
      setSaveStateById((current) => ({
        ...current,
        [selectedPose.id]: "error",
      }));
      setSaveMessageById((current) => ({
        ...current,
        [selectedPose.id]: `Save failed: ${message}`,
      }));
    }
  };

  const handleCreatePose = async () => {
    if (!onCreatePose || creatingPose) {
      return;
    }
    setCreatingPose(true);
    setCreationMessage(null);
    try {
      const created = await onCreatePose(schema);
      if (
        created.schema_id !== schema.id ||
        created.schema_revision !== schema.revision
      ) {
        throw new Error("New pose was not created on the current schema revision");
      }
      setPersistedById((current) => ({
        ...current,
        [created.id]: clonePose(created),
      }));
      setDraftsById((current) => ({
        ...current,
        [created.id]: clonePose(created),
      }));
      setPoseIds((current) =>
        current.includes(created.id) ? current : [...current, created.id],
      );
      setSelectedPoseId(created.id);
      setSelectedObservationId(null);
      setSaveStateById((current) => ({
        ...current,
        [created.id]: "idle",
      }));
      setCreationMessage(
        `Created pose on schema revision ${schema.revision}`,
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown pose creation failure";
      setCreationMessage(`Pose creation failed: ${message}`);
    } finally {
      setCreatingPose(false);
    }
  };

  if (!selectedPose || !persistedPose) {
    return (
      <div>
        <p>No poses available for editing.</p>
        {onCreatePose && (
          <button
            type="button"
            disabled={creatingPose}
            onClick={() => void handleCreatePose()}
          >
            Create pose
          </button>
        )}
        {creationMessage && <span role="status">{creationMessage}</span>}
      </div>
    );
  }

  if (!selectedSchema) {
    return (
      <div role="alert">
        Pose {selectedPose.id} requires schema {selectedPose.schema_id} revision{" "}
        {selectedPose.schema_revision}, but that exact immutable revision is not
        available.
      </div>
    );
  }

  return (
    <section aria-label="Pose annotation editor">
      <header>
        <label>
          Pose
          <select
            aria-label="Pose"
            value={selectedPoseId}
            onChange={(event) => {
              setSelectedPoseId(event.target.value);
              setSelectedObservationId(null);
            }}
          >
            {poseIds.map((poseId) => (
              <option key={poseId} value={poseId}>
                {poseId}
              </option>
            ))}
          </select>
        </label>
        <span data-testid="pose-revision">
          Revision {persistedPose.revision}
        </span>
        <span data-testid="pose-schema-revision">
          Schema revision {selectedSchema.revision}
        </span>
        {onCreatePose && (
          <button
            type="button"
            disabled={creatingPose}
            onClick={() => void handleCreatePose()}
          >
            Create pose
          </button>
        )}
        {creationMessage && <span role="status">{creationMessage}</span>}
      </header>

      <div aria-label="Pose tools">
        <button
          type="button"
          aria-pressed={tool === "landmark"}
          onClick={() => setTool("landmark")}
        >
          Landmark tool
        </button>
        <button
          type="button"
          aria-pressed={tool === "pan"}
          onClick={() => setTool("pan")}
        >
          Pan tool
        </button>
        <button type="button" onClick={() => setView(initialView)}>
          Reset view
        </button>
        {selectedSchema.groups.map((group) => {
          const count = placedCount(selectedPose.observations, group.name);
          return (
            <button
              key={group.name}
              type="button"
              aria-label={`Place ${group.name}`}
              aria-pressed={effectiveActiveLabel === group.name}
              disabled={count >= group.count}
              onClick={() => {
                setActiveLabel(group.name);
                setTool("landmark");
              }}
            >
              {group.name} {count} / {group.count}
            </button>
          );
        })}
        <button
          type="button"
          disabled={!selectedObservationId}
          onClick={handleDeleteSelected}
        >
          Delete selected landmark
        </button>
        <label>
          Landmark status
          <select
            aria-label="Landmark status"
            disabled={!selectedObservation}
            value={selectedObservation?.status ?? "visible"}
            onChange={(event) => {
              if (!selectedPose || !selectedObservation) {
                return;
              }
              const status = event.target.value as PoseLandmarkStatus;
              setPoseDraft(selectedPose.id, (pose) =>
                setPoseObservationStatus(pose, selectedObservation.id, status),
              );
            }}
          >
            <option value="visible">visible</option>
            <option value="occluded">occluded</option>
            <option value="uncertain">uncertain</option>
            <option value="absent">absent</option>
          </select>
        </label>
      </div>

      <svg
        ref={svgRef}
        data-testid="pose-stage"
        width={viewportWidth}
        height={viewportHeight}
        viewBox={`0 0 ${viewportWidth} ${viewportHeight}`}
        onPointerDown={handleStagePointerDown}
        onPointerMove={handleStagePointerMove}
        onPointerUp={handleStagePointerUp}
        onPointerLeave={handleStagePointerUp}
        onWheel={handleWheel}
        role="img"
        aria-label="Pose annotation canvas"
      >
        <rect
          width={viewportWidth}
          height={viewportHeight}
          fill="transparent"
        />
        <g
          transform={`translate(${view.offsetX} ${view.offsetY}) scale(${view.scale})`}
        >
          <image
            href={imageUrl}
            x={0}
            y={0}
            width={imageWidth}
            height={imageHeight}
            preserveAspectRatio="none"
          />
          {skeletonSegments.map((segment) => (
            <line
              key={segment.key}
              data-testid={`pose-skeleton-${segment.key}`}
              x1={segment.from.x}
              y1={segment.from.y}
              x2={segment.to.x}
              y2={segment.to.y}
              stroke="currentColor"
              strokeWidth={2 / view.scale}
              opacity={0.55}
              pointerEvents="none"
            />
          ))}
          {selectedPose.observations.map((observation) => {
            const selected = observation.id === selectedObservationId;
            return (
              <g key={observation.id}>
                <circle
                  data-testid={`pose-landmark-${observation.id}`}
                  aria-label={`${observation.semantic_label} ${observation.occurrence_index + 1}`}
                  cx={observation.x}
                  cy={observation.y}
                  r={selected ? 8 / view.scale : 6 / view.scale}
                  strokeWidth={2 / view.scale}
                  onPointerDown={(event) =>
                    handleObservationPointerDown(event, observation.id)
                  }
                />
                <text
                  x={observation.x + 9 / view.scale}
                  y={observation.y - 9 / view.scale}
                  fontSize={12 / view.scale}
                  pointerEvents="none"
                >
                  {observation.semantic_label}
                  {selectedSchema.groups.find(
                    (group) =>
                      group.name === observation.semantic_label &&
                      group.count > 1,
                  )
                    ? ` ${observation.occurrence_index + 1}`
                    : ""}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      <footer>
        <button
          type="button"
          disabled={saveState === "saving"}
          onClick={() => void handleSave()}
        >
          Save pose
        </button>
        <button
          type="button"
          disabled={saveState === "saving"}
          onClick={handleRevert}
        >
          Revert pose
        </button>
        <span role="status">
          {saveMessage ??
            (saveState === "dirty"
              ? "Unsaved pose edits"
              : saveState === "saving"
                ? "Saving pose..."
                : saveState === "saved"
                  ? "Pose saved"
                  : saveState === "error"
                    ? "Pose save failed"
                    : "Pose ready")}
        </span>
      </footer>
    </section>
  );
}
