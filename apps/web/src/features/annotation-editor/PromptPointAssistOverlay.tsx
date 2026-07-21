import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  getAnnotationSession,
  getProjectModelCatalog,
  type ModelCatalogEntry,
  type Project,
} from "../../api/client";
import {
  acceptPromptAssistSession,
  applyPromptAssistPoints,
  createPromptAssistSession,
  deletePromptAssistSession,
  type PromptAssistSession,
} from "./promptPointAssistApi";
import {
  initialPromptPointHistoryState,
  promptPointHistoryReducer,
  type PromptPoint,
  type PromptPointKind,
} from "./promptPointHistory";

interface PromptPointAssistOverlayProps {
  project: Project;
  imageId: string;
  activeWorkspace?: "boxes" | "masks" | "raster";
  onAccepted?: (kind: PromptAssistOutputKind) => void;
  onClose: () => void;
}

type PromptAssistOutputKind = "raster_mask" | "polygon";

type ReadyPromptAssistModel = ModelCatalogEntry & { resolved_model_id: string };

const fallbackPanelStyle = {
  position: "fixed" as const,
  left: "1rem",
  bottom: "1rem",
  zIndex: 999999,
  width: "min(24rem, calc(100vw - 2rem))",
  maxHeight: "75vh",
  overflow: "auto" as const,
  padding: "1rem",
  border: "1px solid rgba(182, 238, 228, 0.3)",
  borderRadius: "0.9rem",
  background: "rgba(3, 25, 30, 0.98)",
  boxShadow: "0 0.75rem 2rem rgba(0, 0, 0, 0.45)",
};

function pointId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `prompt-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function pointLabel(kind: PromptPointKind): string {
  return kind === "positive" ? "Include" : "Exclude";
}

export function PromptPointAssistOverlay({
  project,
  imageId,
  activeWorkspace = "boxes",
  onAccepted = () => undefined,
  onClose,
}: PromptPointAssistOverlayProps) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<PromptPointKind>("positive");
  const [modelId, setModelId] = useState("");
  const [labelClassId, setLabelClassId] = useState("");
  const [outputKind, setOutputKind] = useState<PromptAssistOutputKind>(
    activeWorkspace === "masks" ? "polygon" : "raster_mask",
  );
  const outputKindExplicitRef = useRef(false);
  const [session, setSession] = useState<PromptAssistSession | null>(null);
  const [candidateStale, setCandidateStale] = useState(false);
  const [useContextBox, setUseContextBox] = useState(false);
  const [contextBox, setContextBox] = useState({
    x_min: 0,
    y_min: 0,
    x_max: 64,
    y_max: 64,
  });
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const [panelTarget, setPanelTarget] = useState<HTMLElement | null>(null);
  const [svgTarget, setSvgTarget] = useState<SVGSVGElement | null>(null);
  const [overlayTarget, setOverlayTarget] = useState<SVGGElement | null>(null);
  const [history, dispatchHistory] = useReducer(
    promptPointHistoryReducer,
    initialPromptPointHistoryState,
  );
  const historyRef = useRef(history);
  const sessionRef = useRef(session);
  const previewAbortRef = useRef<AbortController | null>(null);
  const requestEpochRef = useRef(0);

  useEffect(() => {
    historyRef.current = history;
  }, [history]);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const annotationSession = useQuery({
    queryKey: ["annotation-session", imageId],
    queryFn: ({ signal }) => getAnnotationSession(imageId, signal),
    refetchOnWindowFocus: false,
  });
  const modelCatalog = useQuery({
    queryKey: ["model_catalog", project.id, "point_prompt_assist"],
    queryFn: () =>
      getProjectModelCatalog(project.id, {
        workflow: "smart_mask",
      }),
  });

  useEffect(() => {
    if (outputKindExplicitRef.current) return;
    setOutputKind(activeWorkspace === "masks" ? "polygon" : "raster_mask");
  }, [activeWorkspace]);

  const readyModels = useMemo(() => {
    const models =
      modelCatalog.data?.models ?? modelCatalog.data?.entries ?? [];
    return models.filter(
      (model): model is ReadyPromptAssistModel =>
        (model.task === "assist_segmentation" ||
          model.prompt_assist_compatibility === true) &&
        model.selection_kind === "registered_model" &&
        typeof model.resolved_model_id === "string" &&
        model.resolved_model_id.length > 0 &&
        model.metadata_verified !== false &&
        model.provider_ready !== false &&
        (model.installation_state === "Ready" ||
          model.installation_state === "Available"),
    );
  }, [modelCatalog.data]);
  const selectedModel = useMemo(
    () =>
      readyModels.find((model) => model.resolved_model_id === modelId) ?? null,
    [modelId, readyModels],
  );
  const supportsPoint = selectedModel?.capabilities.point_prompt ?? true;
  const supportsNegative =
    selectedModel?.capabilities.negative_point_prompt ?? true;
  const supportsBox = selectedModel?.capabilities.box_prompt ?? false;
  const supportsMixed =
    selectedModel?.capabilities.mixed_point_box_prompt ?? false;
  const unavailableModels = useMemo(() => {
    const models =
      modelCatalog.data?.models ?? modelCatalog.data?.entries ?? [];
    return models.filter(
      (model) =>
        !readyModels.some(
          (candidate) => candidate.catalog_id === model.catalog_id,
        ),
    );
  }, [modelCatalog.data, readyModels]);

  useEffect(() => {
    const storageKey = `reefvision:point-assist-model:${project.id}`;
    const savedModelId = window.localStorage.getItem(storageKey);
    const nextModelId =
      readyModels.find((model) => model.resolved_model_id === savedModelId)
        ?.resolved_model_id ??
      readyModels[0]?.resolved_model_id ??
      "";
    setModelId((current) =>
      readyModels.some((model) => model.resolved_model_id === current)
        ? current
        : nextModelId,
    );
  }, [project.id, readyModels]);

  useEffect(() => {
    if (!modelId) return;
    window.localStorage.setItem(
      `reefvision:point-assist-model:${project.id}`,
      modelId,
    );
  }, [modelId, project.id]);

  useEffect(() => {
    const activeClasses =
      annotationSession.data?.label_classes.filter(
        (labelClass) => labelClass.is_active,
      ) ?? [];
    if (!activeClasses.some((labelClass) => labelClass.id === labelClassId)) {
      setLabelClassId(activeClasses[0]?.id ?? "");
    }
  }, [annotationSession.data?.label_classes, labelClassId]);

  useEffect(() => {
    const findTargets = () => {
      const svg = document.querySelector<SVGSVGElement>(
        activeWorkspace === "boxes"
          ? "svg.annotation-canvas"
          : activeWorkspace === "masks"
            ? '[data-testid="polygon-mask-layer"]'
            : '[data-testid="raster-brush-layer"]',
      );
      const group =
        activeWorkspace === "boxes"
          ? (svg?.querySelector<SVGGElement>(":scope > g") ?? null)
          : svg;
      const sidebar = document.querySelector<HTMLElement>(
        ".annotation-editor-sidebar",
      );
      setSvgTarget((current) => (current === svg ? current : svg));
      setOverlayTarget((current) => (current === group ? current : group));
      setPanelTarget((current) => (current === sidebar ? current : sidebar));
    };
    findTargets();
    const observer = new MutationObserver(findTargets);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [activeWorkspace]);

  const deleteRemoteSession = useCallback(async (sessionId: string) => {
    try {
      await deletePromptAssistSession(sessionId);
    } catch {
      // Session expiry and cleanup are best-effort.
    }
  }, []);

  useEffect(() => {
    return () => {
      previewAbortRef.current?.abort();
      const sessionId = sessionRef.current?.session_id;
      if (sessionId) void deleteRemoteSession(sessionId);
    };
  }, [deleteRemoteSession]);

  const points = history.present.points;
  const positivePoints = useMemo(
    () => points.filter((point) => point.kind === "positive"),
    [points],
  );
  const negativePoints = useMemo(
    () => points.filter((point) => point.kind === "negative"),
    [points],
  );

  useEffect(() => {
    if (!svgTarget || !overlayTarget || !annotationSession.data) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      if (!supportsPoint) return;
      const eventTarget = event.target instanceof Element ? event.target : null;
      if (
        eventTarget?.closest(
          "button, input, select, textarea, a, [role='button']",
        )
      ) {
        return;
      }
      const bounds = svgTarget.getBoundingClientRect();
      if (
        bounds.width <= 0 ||
        bounds.height <= 0 ||
        event.clientX < bounds.left ||
        event.clientX > bounds.right ||
        event.clientY < bounds.top ||
        event.clientY > bounds.bottom
      ) {
        return;
      }
      const effectiveMode: PromptPointKind = event.altKey ? "negative" : mode;
      if (effectiveMode === "negative" && !supportsNegative) {
        setInteractionError(
          "The selected provider does not support negative point prompts.",
        );
        return;
      }
      const currentPoints = historyRef.current.present.points;
      if (
        effectiveMode === "negative" &&
        !currentPoints.some((point) => point.kind === "positive")
      ) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        setInteractionError(
          "Place at least one Include point before Exclude points.",
        );
        return;
      }
      const matrix = overlayTarget.getScreenCTM();
      if (!matrix) return;
      const transformed = new DOMPoint(
        event.clientX,
        event.clientY,
      ).matrixTransform(matrix.inverse());
      const image = annotationSession.data.image;
      if (
        transformed.x < 0 ||
        transformed.y < 0 ||
        transformed.x > image.width_px ||
        transformed.y > image.height_px
      ) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      const point: PromptPoint = {
        id: pointId(),
        x: transformed.x,
        y: transformed.y,
        kind: effectiveMode,
        createdAt: new Date().toISOString(),
      };
      dispatchHistory({ type: "add", point });
      setCandidateStale(true);
      setInteractionError(null);
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () =>
      document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [
    annotationSession.data,
    mode,
    overlayTarget,
    supportsNegative,
    supportsPoint,
    svgTarget,
  ]);

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!modelId) throw new Error("Choose a ready point-assist model.");
      if (positivePoints.length === 0 && !useContextBox) {
        throw new Error("Place an Include point or enable a box prompt.");
      }
      if (useContextBox && !supportsBox) {
        throw new Error("The selected provider does not support box prompts.");
      }
      if (negativePoints.length > 0 && !supportsNegative) {
        throw new Error(
          "The selected provider does not support negative points.",
        );
      }
      if (useContextBox && points.length > 0 && !supportsMixed) {
        throw new Error(
          "The selected provider does not support mixed point/box prompts.",
        );
      }
      previewAbortRef.current?.abort();
      const controller = new AbortController();
      previewAbortRef.current = controller;
      const epoch = ++requestEpochRef.current;
      const requestedModelId = modelId;
      const previousSessionId = sessionRef.current?.session_id;
      if (previousSessionId) await deleteRemoteSession(previousSessionId);
      const created = await createPromptAssistSession(
        imageId,
        {
          model_id: modelId,
          device: "auto",
        },
        controller.signal,
      );
      try {
        const updatedSession = await applyPromptAssistPoints(
          created.session_id,
          {
            positive_points: positivePoints.map(({ x, y }) => ({ x, y })),
            negative_points: negativePoints.map(({ x, y }) => ({ x, y })),
            context_box: useContextBox ? contextBox : null,
          },
          controller.signal,
        );
        return { updatedSession, epoch, requestedModelId };
      } catch (error) {
        await deleteRemoteSession(created.session_id);
        throw error;
      }
    },
    onSuccess: ({ updatedSession, epoch, requestedModelId }) => {
      if (epoch !== requestEpochRef.current || requestedModelId !== modelId) {
        void deleteRemoteSession(updatedSession.session_id);
        return;
      }
      setSession(updatedSession);
      setCandidateStale(false);
      setInteractionError(null);
    },
  });

  const acceptMutation = useMutation({
    mutationFn: async ({
      outputKind: acceptedOutputKind,
      labelClassId: acceptedLabelClassId,
    }: {
      outputKind: PromptAssistOutputKind;
      labelClassId: string;
    }) => {
      const activeSession = sessionRef.current;
      if (!activeSession || !activeSession.candidate_box || candidateStale) {
        throw new Error("Update the mask preview before accepting it.");
      }
      if (!acceptedLabelClassId) {
        throw new Error("Choose an annotation class.");
      }
      const accepted = await acceptPromptAssistSession(
        activeSession.session_id,
        acceptedLabelClassId,
        acceptedOutputKind,
      );
      return { accepted, outputKind: acceptedOutputKind };
    },
    onSuccess: async ({ outputKind: acceptedOutputKind }) => {
      sessionRef.current = null;
      setSession(null);
      dispatchHistory({ type: "reset" });
      setCandidateStale(false);
      await Promise.all([
        queryClient.refetchQueries({
          queryKey: ["annotation-session", imageId],
          exact: true,
        }),
        queryClient.invalidateQueries({
          queryKey: ["project-images", project.id],
        }),
        queryClient.invalidateQueries({ queryKey: ["images", project.id] }),
      ]);
      onAccepted(acceptedOutputKind);
    },
  });

  const resetPrompts = useCallback(async () => {
    previewAbortRef.current?.abort();
    requestEpochRef.current += 1;
    const sessionId = sessionRef.current?.session_id;
    setSession(null);
    dispatchHistory({ type: "reset" });
    setUseContextBox(false);
    setCandidateStale(false);
    setInteractionError(null);
    if (sessionId) await deleteRemoteSession(sessionId);
  }, [deleteRemoteSession]);

  const markHistoryChanged = (action: "undo" | "redo") => {
    dispatchHistory({ type: action });
    setCandidateStale(true);
  };

  const candidateMaskHref = session?.candidate_mask_png_base64
    ? `data:image/png;base64,${session.candidate_mask_png_base64}`
    : null;
  const operationError =
    interactionError ??
    previewMutation.error?.message ??
    acceptMutation.error?.message;

  const panel = (
    <section
      className="annotation-sidebar-section"
      data-testid="point-assist-panel"
      style={panelTarget ? undefined : fallbackPanelStyle}
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Direct Prompt Assist</p>
          <h3>Positive and negative points</h3>
        </div>
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="annotation-helper">
        Click directly on the image to place the active point type. Alt-click
        always places an Exclude point. Update preview reruns the selected model
        from the full point history.
      </p>
      <label>
        Assist model
        <select
          value={modelId}
          disabled={readyModels.length === 0 || acceptMutation.isPending}
          onChange={(event) => {
            const nextModelId = event.target.value;
            const nextModel = readyModels.find(
              (model) => model.resolved_model_id === nextModelId,
            );
            const nextSupportsPoint =
              nextModel?.capabilities.point_prompt ?? true;
            const nextSupportsNegative =
              nextModel?.capabilities.negative_point_prompt ?? true;
            const nextSupportsBox = nextModel?.capabilities.box_prompt ?? false;
            previewAbortRef.current?.abort();
            requestEpochRef.current += 1;
            const priorSessionId = sessionRef.current?.session_id;
            if (priorSessionId) void deleteRemoteSession(priorSessionId);
            sessionRef.current = null;
            setSession(null);
            dispatchHistory({
              type: "replace",
              points: nextSupportsPoint
                ? historyRef.current.present.points.filter(
                    (point) =>
                      point.kind === "positive" || nextSupportsNegative,
                  )
                : [],
            });
            if (!nextSupportsBox) setUseContextBox(false);
            if (!nextSupportsNegative) setMode("positive");
            setModelId(nextModelId);
            setCandidateStale(true);
          }}
        >
          {readyModels.length === 0 ? (
            <option value="">No ready Smart Mask models</option>
          ) : (
            readyModels.map((model) => (
              <option
                key={model.catalog_id}
                value={model.resolved_model_id ?? ""}
              >
                {model.display_name}
              </option>
            ))
          )}
        </select>
      </label>
      {readyModels.length === 0 && modelCatalog.isSuccess && (
        <div className="form-warning" role="status">
          No compatible ready Prompt Assist model is installed. Open the Models
          tab, choose Assist / Smart Mask, select a ready provider, and import a
          real compatible checkpoint.
        </div>
      )}
      {selectedModel && (
        <div
          key={`${selectedModel.catalog_id}-capabilities`}
          className="version-preview-metrics"
        >
          {supportsPoint && <span>Point prompts</span>}
          {supportsNegative && <span>Negative points</span>}
          {supportsBox && <span>Box prompts</span>}
          {supportsMixed && <span>Mixed point/box</span>}
          <span>Raster output</span>
          <span>Polygon conversion</span>
          {selectedModel.supported_devices?.map((item) => (
            <span key={item}>{item.toUpperCase()}</span>
          ))}
        </div>
      )}
      {unavailableModels.length > 0 && (
        <details>
          <summary>
            Unavailable model diagnostics ({unavailableModels.length})
          </summary>
          <div className="annotation-selection-list">
            {unavailableModels.map((model) => (
              <div key={model.catalog_id} className="annotation-selection-row">
                <strong>{model.display_name}</strong>
                <span>
                  {model.installation_state}:{" "}
                  {model.installation_reason ?? "Not ready."}
                  {model.required_provider_pack || model.provider_pack_id
                    ? ` Provider: ${model.required_provider_pack ?? model.provider_pack_id}.`
                    : ""}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}{" "}
      <label>
        Accept mask as
        <select
          value={labelClassId}
          disabled={acceptMutation.isPending}
          onChange={(event) => setLabelClassId(event.target.value)}
        >
          {annotationSession.data?.label_classes
            .filter((labelClass) => labelClass.is_active)
            .map((labelClass) => (
              <option key={labelClass.id} value={labelClass.id}>
                {labelClass.name}
              </option>
            ))}
        </select>
      </label>
      <fieldset disabled={acceptMutation.isPending}>
        <legend>Acceptance output</legend>
        <label className="toggle-row">
          <input
            type="radio"
            name="prompt-assist-output"
            checked={outputKind === "raster_mask"}
            onChange={() => {
              outputKindExplicitRef.current = true;
              setOutputKind("raster_mask");
            }}
          />
          Accept as raster mask
        </label>
        <label className="toggle-row">
          <input
            type="radio"
            name="prompt-assist-output"
            checked={outputKind === "polygon"}
            onChange={() => {
              outputKindExplicitRef.current = true;
              setOutputKind("polygon");
            }}
          />
          Accept as polygon
        </label>
      </fieldset>
      <p className="annotation-helper">
        Prompt models produce a raster mask internally. Polygon output uses a
        deterministic one-source-pixel contour simplification and remains
        editable.
      </p>{" "}
      <div
        className="annotation-editor-inline-actions"
        role="group"
        aria-label="Point type"
      >
        <button
          type="button"
          className={mode === "positive" ? "active" : "secondary"}
          disabled={!supportsPoint}
          onClick={() => setMode("positive")}
        >
          Include point
        </button>
        <button
          type="button"
          className={mode === "negative" ? "active" : "secondary"}
          disabled={!supportsNegative || positivePoints.length === 0}
          onClick={() => setMode("negative")}
        >
          Exclude point
        </button>
      </div>
      <fieldset disabled={!supportsBox || previewMutation.isPending}>
        <legend>Box prompt</legend>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={useContextBox}
            onChange={(event) => {
              setUseContextBox(event.target.checked);
              setCandidateStale(true);
            }}
          />
          Use source-pixel context box
        </label>
        {useContextBox && (
          <div className="annotation-editor-inline-actions">
            {Object.entries(contextBox).map(([key, value]) => (
              <label key={key}>
                {key}
                <input
                  type="number"
                  min="0"
                  value={value}
                  onChange={(event) => {
                    setContextBox({
                      ...contextBox,
                      [key]: Number(event.target.value),
                    });
                    setCandidateStale(true);
                  }}
                />
              </label>
            ))}
          </div>
        )}
      </fieldset>
      {useContextBox && points.length > 0 && !supportsMixed && (
        <p className="form-warning">
          This provider cannot combine point and box prompts. Clear one prompt
          type before previewing.
        </p>
      )}
      <div className="version-preview-metrics">
        <span>{positivePoints.length} include</span>
        <span>{negativePoints.length} exclude</span>
        <span>{history.past.length} edits</span>
      </div>
      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          className="secondary"
          disabled={history.past.length === 0}
          onClick={() => markHistoryChanged("undo")}
        >
          Undo point
        </button>
        <button
          type="button"
          className="secondary"
          disabled={history.future.length === 0}
          onClick={() => markHistoryChanged("redo")}
        >
          Redo point
        </button>
        <button
          type="button"
          className="secondary"
          disabled={points.length === 0 && !session}
          onClick={() => void resetPrompts()}
        >
          Clear
        </button>
      </div>
      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          disabled={
            !modelId ||
            (positivePoints.length === 0 && !useContextBox) ||
            previewMutation.isPending ||
            (useContextBox && points.length > 0 && !supportsMixed)
          }
          onClick={() => previewMutation.mutate()}
        >
          {previewMutation.isPending
            ? "Updating preview..."
            : session
              ? "Update mask preview"
              : "Generate mask preview"}
        </button>
        <button
          type="button"
          disabled={
            !session?.candidate_box ||
            candidateStale ||
            !labelClassId ||
            acceptMutation.isPending
          }
          onClick={() =>
            acceptMutation.mutate({
              outputKind,
              labelClassId,
            })
          }
        >
          {acceptMutation.isPending
            ? "Accepting..."
            : outputKind === "polygon"
              ? "Accept polygon"
              : "Accept mask"}
        </button>
      </div>
      {candidateStale && session?.candidate_box && (
        <p className="form-warning">
          Point history changed. Update the preview before accepting this mask.
        </p>
      )}
      {session?.candidate_box && !candidateStale && (
        <p className="form-success">
          Candidate ready via {session.provider_name};{" "}
          {session.positive_point_count} positive and{" "}
          {session.negative_point_count} negative prompts were applied.
        </p>
      )}
      {operationError && <p className="form-error">{operationError}</p>}
      {modelCatalog.error && (
        <p className="form-error">{modelCatalog.error.message}</p>
      )}
      <div
        className="annotation-selection-list"
        aria-label="Point prompt history"
      >
        {[...points].reverse().map((point, index) => (
          <div key={point.id} className="annotation-selection-row">
            <div>
              <strong>
                {points.length - index}. {pointLabel(point.kind)}
              </strong>
              <span>
                ({point.x.toFixed(1)}, {point.y.toFixed(1)})
              </span>
            </div>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                dispatchHistory({ type: "remove", pointId: point.id });
                setCandidateStale(true);
              }}
            >
              Remove
            </button>
          </div>
        ))}
        {points.length === 0 && <p>No point prompts placed yet.</p>}
      </div>
    </section>
  );

  const overlay = overlayTarget
    ? createPortal(
        <g data-testid="point-assist-overlay" pointerEvents="none">
          {candidateMaskHref && (
            <image
              href={candidateMaskHref}
              x={0}
              y={0}
              width={annotationSession.data?.image.width_px ?? 0}
              height={annotationSession.data?.image.height_px ?? 0}
              opacity={candidateStale ? 0.14 : 0.32}
              preserveAspectRatio="none"
            />
          )}
          {points.map((point) => (
            <g key={point.id}>
              <circle
                cx={point.x}
                cy={point.y}
                r={8}
                fill={point.kind === "positive" ? "#57cc99" : "#ff6b6b"}
                stroke="#ffffff"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
              <text
                x={point.x}
                y={point.y + 4}
                textAnchor="middle"
                fill="#07191d"
                fontSize={12}
                fontWeight={700}
              >
                {point.kind === "positive" ? "+" : "−"}
              </text>
            </g>
          ))}
        </g>,
        overlayTarget,
      )
    : null;

  return (
    <>
      {createPortal(panel, panelTarget ?? document.body)}
      {overlay}
    </>
  );
}
