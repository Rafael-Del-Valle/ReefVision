import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  startTransition,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import {
  acceptAssistSession,
  acceptPrediction,
  cancelJob,
  boxAssistSession,
  bulkReviewPredictions,
  createAssistSession,
  createInferenceJob,
  deleteClassVisibilityPreference,
  deleteAssistSession,
  deleteProjectClassVisibilityDefault,
  getClassVisibilityBundle,
  getAnnotationSession,
  getJob,
  getModels,
  getPredictions,
  getProjectModelCatalog,
  imageDisplayUrl,
  imageThumbnailUrl,
  predictionMaskUrl,
  rejectPrediction,
  saveAnnotations,
  saveClassVisibilityPreference,
  saveProjectClassVisibilityDefault,
  type AnnotationSession,
  type AssistSession,
  type ClassVisibilityBundle,
  type ClassVisibilityLayerType,
  type ClassVisibilityScopeState,
  type JobRecord,
  type LabelClass,
  type ModelCatalogEntry,
  type PredictionProposal,
  type Project,
} from "../../api/client";
import { ErrorState, LoadingState } from "../../components/ui/AsyncState";
import { shouldIgnoreShortcutTarget } from "../../components/ui/keyboardShortcuts";
import {
  annotationEditorReducer,
  initialAnnotationEditorState,
  isDirty,
  toAnnotationSavePayload,
} from "./annotationEditorReducer";
import {
  copyAnnotations,
  pasteAnnotations,
  readInternalAnnotationClipboard,
  type AnnotationClipboard,
  writeInternalAnnotationClipboard,
} from "./annotationClipboard";
import { deleteMaskAnnotations } from "./maskDocumentOperations";
import { rasterMaskContentUrl } from "./rasterMaskApi";
import {
  actualSizeTransform,
  boxArea,
  clampScale,
  createBoxFromPoints,
  fitTransform,
  resizeAnnotation,
  screenToImage,
  translateAnnotations,
  zoomAtPoint,
} from "./geometry";
import type {
  AnnotationDocument,
  AnnotationEditorState,
  EditorAnnotation,
  Point,
  ResizeHandle,
  ViewportTransform,
} from "./types";
import {
  resolveClassVisibilityState,
  sanitizeHiddenClassIds,
  updateClassVisibilityBundleScope,
  visibilityLayerLabel,
  visibilityLayerOptions,
  visibilitySourceLabel,
  type VisibilityScopeKey,
} from "./classVisibility";
import {
  PredictionInspector,
  type ReviewedPredictionGeometry,
} from "./PredictionInspector";
import { QuickConfidenceReviewDialog } from "../review-queues/QuickConfidenceReviewDialog";
import {
  executeAdvancedProvider,
  getSam2Models,
  installSam2Model,
} from "../advanced-providers/advancedProvidersApi";

import {
  createSamImageProposals,
  intelligenceRequest,
} from "./annotationIntelligenceApi";
import { useMaskRefinement } from "./useMaskRefinement";
import { PendingMaskEditor } from "./PendingMaskEditor";
import { ImprovePredictionsPanel } from "./ImprovePredictionsPanel";

interface AnnotationEditorProps {
  project: Project;
  initialImageId: string;
  launchContext?: {
    returnLabel: string;
    contextTitle?: string;
    contextDescription?: string;
    highlightAnnotationIds?: string[];
    highlightPredictionIds?: string[];
  };
  onClose: () => void;
  onActiveImageChange?: (imageId: string) => void;
}

type EditorInteraction =
  | {
      type: "drawing";
      start: Point;
      current: Point;
    }
  | {
      type: "moving";
      origin: Point;
      selection: string[];
      snapshot: Record<string, EditorAnnotation>;
      current: Point;
    }
  | {
      type: "resizing";
      handle: ResizeHandle;
      annotationId: string;
      snapshot: EditorAnnotation;
      current: Point;
    }
  | {
      type: "panning";
      origin: Point;
      initialView: ViewportTransform;
    };

type VisibilityMutationAction = "save" | "reset";
type VisibilityMutationTarget = "my_preference" | "project_default";

interface VisibilityMutationInput {
  action: VisibilityMutationAction;
  layerType: ClassVisibilityLayerType;
  target: VisibilityMutationTarget;
  hiddenClassIds?: string[];
}

interface VisibilityMutationResult {
  layerType: ClassVisibilityLayerType;
  scopeKey: VisibilityScopeKey;
  state: ClassVisibilityScopeState;
  statusMessage: string;
}

function selectionToggled(selection: string[], id: string): string[] {
  return selection.includes(id)
    ? selection.filter((item) => item !== id)
    : [...selection, id];
}

function replaceAnnotations(
  document: AnnotationDocument,
  updated: EditorAnnotation[],
): AnnotationDocument {
  const updatedById = new Map(
    updated.map((annotation) => [annotation.id, annotation]),
  );
  return {
    ...document,
    annotations: document.annotations.map(
      (annotation) => updatedById.get(annotation.id) ?? annotation,
    ),
  };
}

function saveStateLabel(
  saveState: AnnotationEditorState["saveState"],
  message: string | null,
): string {
  if (message) {
    return message;
  }
  switch (saveState) {
    case "saving":
      return "Saving...";
    case "dirty":
      return "Unsaved changes";
    case "saved":
      return "Saved";
    case "conflict":
      return "Revision conflict";
    case "error":
      return "Save failed";
    default:
      return "Ready";
  }
}

function isEditableTarget(target: EventTarget | null): boolean {
  return shouldIgnoreShortcutTarget(target);
}

function clientPointInSvg(
  svg: SVGSVGElement,
  clientX: number,
  clientY: number,
  view: ViewportTransform,
): Point {
  const rect = svg.getBoundingClientRect();
  return screenToImage(
    {
      x: clientX - rect.left,
      y: clientY - rect.top,
    },
    view,
  );
}

function countByClass(
  annotations: EditorAnnotation[],
  labelClasses: LabelClass[],
): Map<string, number> {
  const counts = new Map<string, number>();
  annotations.forEach((annotation) => {
    counts.set(
      annotation.label_class_id,
      (counts.get(annotation.label_class_id) ?? 0) + 1,
    );
  });
  labelClasses.forEach((labelClass) => {
    if (!counts.has(labelClass.id)) {
      counts.set(labelClass.id, 0);
    }
  });
  return counts;
}

function makeAnnotationId(): string {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `annotation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function confirmDiscardUnsavedEdits(actionLabel: string): boolean {
  return window.confirm(
    `Saving failed. Discard unsaved local annotation edits and ${actionLabel}?`,
  );
}

/**
 * Preserve a thumbnail preview when a source-resolution preload fails.
 * The preview is not a substitute for source imagery during scientific review.
 */
export function annotationImageSource(
  imageId: string,
  thumbnailPath: string | null,
  fullImageLoaded: boolean,
  retry = 0,
): string {
  return thumbnailPath && !fullImageLoaded
    ? imageThumbnailUrl(imageId)
    : `${imageDisplayUrl(imageId)}?retry=${retry}`;
}

export function AnnotationEditor({
  project,
  initialImageId,
  launchContext,
  onClose,
  onActiveImageChange,
}: AnnotationEditorProps) {
  const queryClient = useQueryClient();
  const [currentImageId, setCurrentImageId] = useState(initialImageId);
  const [state, dispatch] = useReducer(
    annotationEditorReducer,
    initialAnnotationEditorState,
  );
  const [interaction, setInteraction] = useState<EditorInteraction | null>(
    null,
  );
  const [view, setView] = useState<ViewportTransform | null>(null);
  const [hideAnnotations, setHideAnnotations] = useState(false);
  const [showPredictions, setShowPredictions] = useState(true);
  const [selectedVisibilityLayer, setSelectedVisibilityLayer] =
    useState<ClassVisibilityLayerType>("annotations");
  const [sessionVisibilityOverrides, setSessionVisibilityOverrides] = useState<
    Partial<Record<ClassVisibilityLayerType, string[]>>
  >({});
  const [visibilityStatusMessage, setVisibilityStatusMessage] = useState<
    string | null
  >(null);
  const [predictionModelFilter, setPredictionModelFilter] = useState("");
  const [predictionClassFilter, setPredictionClassFilter] = useState("");
  const [predictionConfidenceFilter, setPredictionConfidenceFilter] =
    useState("0");
  const [predictionStatusFilter, setPredictionStatusFilter] =
    useState("pending");
  const [predictionSort, setPredictionSort] = useState("confidence-asc");
  const [selectedPredictionIds, setSelectedPredictionIds] = useState<string[]>(
    [],
  );
  const [assistModelId, setAssistModelId] = useState("");
  const [assistSession, setAssistSession] = useState<AssistSession | null>(
    null,
  );
  const [deployModelId, setDeployModelId] = useState("");
  const [deployConfidence, setDeployConfidence] = useState("0.25");
  const [quickReviewConfidence, setQuickReviewConfidence] = useState("50");
  const [quickReviewOpen, setQuickReviewOpen] = useState(false);
  const [editProposalId, setEditProposalId] = useState<string | null>(null);
  const [learningOpen, setLearningOpen] = useState(false);
  const [samPromptArmed, setSamPromptArmed] = useState(false);
  const [samModelVariant, setSamModelVariant] = useState("small");
  const [samPendingBox, setSamPendingBox] = useState<{
    imageId: string;
    variant: string;
    box: [number, number, number, number];
  } | null>(null);
  const [samInstallJobId, setSamInstallJobId] = useState<string | null>(null);
  const [samReviewProposalId, setSamReviewProposalId] = useState<string | null>(
    null,
  );
  const [isolateSamReview, setIsolateSamReview] = useState(true);
  const [shortcutMessage, setShortcutMessage] = useState<string | null>(null);
  const [deployDevice, setDeployDevice] = useState("auto");
  const [deployJobId, setDeployJobId] = useState<string | null>(null);
  const completedDeployJobRef = useRef<string | null>(null);
  const [predictionClassOverrides, setPredictionClassOverrides] = useState<
    Record<string, string>
  >({});
  const [predictionGeometryOverrides, setPredictionGeometryOverrides] =
    useState<Record<string, ReviewedPredictionGeometry>>({});
  const [objectFilter, setObjectFilter] = useState("");
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const [fullImageRetry, setFullImageRetry] = useState(0);
  const [imagePreload, setImagePreload] = useState<{
    imageId: string;
    retry: number;
    phase: "loading" | "loaded" | "failed";
  } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef(state);
  const interactionRef = useRef<EditorInteraction | null>(interaction);
  const viewRef = useRef<ViewportTransform | null>(view);
  const currentImageIdRef = useRef(currentImageId);
  const loadedImageIdRef = useRef<string | null>(null);
  const savePromiseRef = useRef<Promise<boolean> | null>(null);
  const assistSessionRef = useRef<AssistSession | null>(assistSession);
  const annotationClipboardRef = useRef<AnnotationClipboard | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    interactionRef.current = interaction;
  }, [interaction]);

  useEffect(() => {
    currentImageIdRef.current = currentImageId;
  }, [currentImageId]);

  useEffect(() => {
    onActiveImageChange?.(currentImageId);
  }, [currentImageId, onActiveImageChange]);

  useEffect(() => {
    assistSessionRef.current = assistSession;
  }, [assistSession]);

  useEffect(() => {
    setSelectedVisibilityLayer("annotations");
    setSessionVisibilityOverrides({});
    setVisibilityStatusMessage(null);
  }, [project.id]);

  const sessionQuery = useQuery({
    queryKey: ["annotation-session", currentImageId],
    queryFn: ({ signal }) => getAnnotationSession(currentImageId, signal),
    refetchOnWindowFocus: false,
  });
  const visibilityQuery = useQuery({
    queryKey: ["class-visibility", project.id],
    queryFn: ({ signal }) => getClassVisibilityBundle(project.id, signal),
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
  const detectorModels = useQuery({
    queryKey: ["models", project.id, "detector"],
    queryFn: () => getModels(project.id, "detector"),
  });
  const activeDetectorModelId =
    detectorModels.data?.find(
      (model) => model.metadata_json.active_for_predictions === true,
    )?.id ?? "";
  const samInstallJobQuery = useQuery({
    queryKey: ["job", samInstallJobId],
    queryFn: ({ signal }) => getJob(samInstallJobId as string, signal),
    enabled: samInstallJobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed", "cancelled"].includes(status)
        ? false
        : 1000;
    },
  });
  const deployJobQuery = useQuery({
    queryKey: ["job", deployJobId],
    queryFn: ({ signal }) => getJob(deployJobId as string, signal),
    enabled: deployJobId !== null,
    refetchInterval: (query) => {
      const job = query.state.data as JobRecord | undefined;
      return job && ["succeeded", "failed", "cancelled"].includes(job.status)
        ? false
        : 1000;
    },
  });
  const assistModels = useQuery({
    queryKey: ["model_catalog", project.id, "smart_mask"],
    queryFn: () =>
      getProjectModelCatalog(project.id, {
        workflow: "smart_mask",
      }),
  });
  const predictionQuery = useQuery({
    queryKey: [
      "predictions",
      currentImageId,
      predictionModelFilter,
      predictionClassFilter,
      predictionConfidenceFilter,
      predictionStatusFilter,
    ],
    queryFn: ({ signal }) =>
      getPredictions(
        currentImageId,
        {
          modelId: predictionModelFilter || undefined,
          labelClassId: predictionClassFilter || undefined,
          minConfidence: Number(predictionConfidenceFilter),
          reviewStatus: predictionStatusFilter || undefined,
        },
        signal,
      ),
    enabled: Boolean(sessionQuery.data) && showPredictions,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (!deployModelId && detectorModels.data?.[0]) {
      const active = detectorModels.data.find(
        (model) => model.metadata_json.active_for_predictions === true,
      );
      setDeployModelId((active ?? detectorModels.data[0]).id);
    }
  }, [deployModelId, detectorModels.data]);

  useEffect(() => {
    const session = sessionQuery.data;
    if (!session || session.image.id !== currentImageId) {
      return;
    }
    const snapshot = stateRef.current;
    const imageChanged = loadedImageIdRef.current !== session.image.id;
    const newerSameImage =
      !imageChanged &&
      session.image.annotation_revision > snapshot.baseRevision;
    if (!imageChanged && !newerSameImage) {
      return;
    }
    if (
      !imageChanged &&
      (isDirty(snapshot) || snapshot.saveState === "saving")
    ) {
      return;
    }
    dispatch({ type: "loadSession", session });
    loadedImageIdRef.current = session.image.id;
    setSamReviewProposalId(null);
    setHideAnnotations(false);
    setSelectedPredictionIds([]);
    setPredictionGeometryOverrides({});
    setInteraction(null);
    setView(null);
  }, [currentImageId, sessionQuery.data]);

  const readyAssistModels = useMemo(
    () =>
      (assistModels.data?.models ?? []).filter(
        (model): model is ModelCatalogEntry & { resolved_model_id: string } =>
          model.selection_kind === "registered_model" &&
          typeof model.resolved_model_id === "string" &&
          model.resolved_model_id.length > 0 &&
          (model.installation_state === "Ready" ||
            model.installation_state === "Available"),
      ),
    [assistModels.data?.models],
  );
  const selectedAssistCatalogEntry =
    readyAssistModels.find(
      (model) => model.resolved_model_id === assistModelId,
    ) ?? null;

  useEffect(() => {
    const storageKey = `reefvision:smart-mask-model:${project.id}`;
    const saved = window.localStorage.getItem(storageKey);
    if (saved) {
      setAssistModelId(saved);
    }
  }, [project.id]);

  useEffect(() => {
    const storageKey = `reefvision:smart-mask-model:${project.id}`;
    if (
      assistModelId &&
      readyAssistModels.some(
        (model) => model.resolved_model_id === assistModelId,
      )
    ) {
      window.localStorage.setItem(storageKey, assistModelId);
      return;
    }
    const nextModelId = readyAssistModels[0]?.resolved_model_id ?? "";
    setAssistModelId(nextModelId);
    if (nextModelId) {
      window.localStorage.setItem(storageKey, nextModelId);
    } else {
      window.localStorage.removeItem(storageKey);
    }
  }, [assistModelId, project.id, readyAssistModels]);

  useEffect(() => {
    const neighborIds = [
      sessionQuery.data?.previous_image_id,
      sessionQuery.data?.next_image_id,
    ].filter((imageId): imageId is string => Boolean(imageId));
    neighborIds.forEach((imageId) => {
      void queryClient.prefetchQuery({
        queryKey: ["annotation-session", imageId],
        queryFn: ({ signal }) => getAnnotationSession(imageId, signal),
      });
    });
  }, [
    queryClient,
    sessionQuery.data?.next_image_id,
    sessionQuery.data?.previous_image_id,
  ]);

  useEffect(() => {
    const imageId = sessionQuery.data?.image.id;
    if (!imageId) {
      return;
    }
    const preloader = new window.Image();
    let cancelled = false;
    let decodeFallback: number | null = null;
    let fallbackActivated = false;
    const retry = fullImageRetry;
    setImagePreload({ imageId, retry, phase: "loading" });
    preloader.decoding = "async";
    preloader.onload = () => {
      if (cancelled) return;
      if (typeof preloader.decode !== "function") {
        setImagePreload({ imageId, retry, phase: "loaded" });
        return;
      }
      // WebView2 can fire load but leave decode() pending indefinitely.
      // Reveal a successfully loaded image after a bounded grace period.
      decodeFallback = window.setTimeout(() => {
        decodeFallback = null;
        fallbackActivated = true;
        if (!cancelled) {
          setImagePreload({ imageId, retry, phase: "loaded" });
        }
      }, 3_000);
      void preloader.decode().then(
        () => {
          if (decodeFallback !== null) window.clearTimeout(decodeFallback);
          decodeFallback = null;
          if (!cancelled) {
            setImagePreload({ imageId, retry, phase: "loaded" });
          }
        },
        () => {
          if (decodeFallback !== null) window.clearTimeout(decodeFallback);
          decodeFallback = null;
          // A late rejection must not hide an image already revealed after
          // its successful load event.
          if (!cancelled && !fallbackActivated) {
            setImagePreload({ imageId, retry, phase: "failed" });
          }
        },
      );
    };
    preloader.onerror = () => {
      if (!cancelled) {
        if (decodeFallback !== null) window.clearTimeout(decodeFallback);
        decodeFallback = null;
        setImagePreload({ imageId, retry, phase: "failed" });
      }
    };
    preloader.src = annotationImageSource(imageId, null, true, retry);
    return () => {
      cancelled = true;
      if (decodeFallback !== null) window.clearTimeout(decodeFallback);
      preloader.onload = null;
      preloader.onerror = null;
    };
  }, [fullImageRetry, sessionQuery.data?.image.id]);

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) {
      return;
    }
    const updateSize = () => {
      setContainerSize({
        width: element.clientWidth || 1200,
        height: element.clientHeight || 780,
      });
    };
    updateSize();
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(updateSize);
      observer.observe(element);
      return () => observer.disconnect();
    }
    globalThis.addEventListener("resize", updateSize);
    return () => globalThis.removeEventListener("resize", updateSize);
  }, [sessionQuery.data?.image.id]);

  const imageSize = useMemo(() => {
    if (!sessionQuery.data) {
      return null;
    }
    return {
      width: sessionQuery.data.image.width_px,
      height: sessionQuery.data.image.height_px,
    };
  }, [sessionQuery.data]);

  const fallbackView = useMemo(() => {
    if (!imageSize) {
      return null;
    }
    return fitTransform(imageSize, {
      width: containerSize.width || 1200,
      height: containerSize.height || 780,
    });
  }, [containerSize.height, containerSize.width, imageSize]);

  const currentView = view ?? fallbackView;

  useEffect(() => {
    viewRef.current = currentView;
  }, [currentView]);

  const fitToScreen = useCallback(() => {
    if (!imageSize) {
      return;
    }
    setInteraction(null);
    setView(
      fitTransform(imageSize, {
        width: containerSize.width || 1200,
        height: containerSize.height || 780,
      }),
    );
  }, [containerSize, imageSize]);

  const showActualSize = useCallback(() => {
    if (!imageSize) return;
    setInteraction(null);
    setView(
      actualSizeTransform(imageSize, {
        width: containerSize.width || 1200,
        height: containerSize.height || 780,
      }),
    );
  }, [containerSize.height, containerSize.width, imageSize]);

  useEffect(() => {
    if (
      !view &&
      imageSize &&
      containerSize.width > 0 &&
      containerSize.height > 0
    ) {
      setView(fitTransform(imageSize, containerSize));
    }
  }, [containerSize, imageSize, view]);

  const labelClasses = useMemo(() => {
    const source = sessionQuery.data?.label_classes ?? project.label_classes;
    return [...source].sort(
      (left, right) =>
        left.display_order - right.display_order ||
        left.class_index - right.class_index,
    );
  }, [project.label_classes, sessionQuery.data?.label_classes]);
  const labelClassesById = useMemo(
    () =>
      new Map(labelClasses.map((labelClass) => [labelClass.id, labelClass])),
    [labelClasses],
  );
  const allClassIds = useMemo(
    () => labelClasses.map((labelClass) => labelClass.id),
    [labelClasses],
  );
  const annotationVisibility = useMemo(
    () =>
      resolveClassVisibilityState(
        "annotations",
        visibilityQuery.data,
        sessionVisibilityOverrides,
        allClassIds,
      ),
    [allClassIds, sessionVisibilityOverrides, visibilityQuery.data],
  );
  const predictionVisibility = useMemo(
    () =>
      resolveClassVisibilityState(
        "predictions",
        visibilityQuery.data,
        sessionVisibilityOverrides,
        allClassIds,
      ),
    [allClassIds, sessionVisibilityOverrides, visibilityQuery.data],
  );
  const currentLayerVisibility = useMemo(
    () =>
      resolveClassVisibilityState(
        selectedVisibilityLayer,
        visibilityQuery.data,
        sessionVisibilityOverrides,
        allClassIds,
      ),
    [
      allClassIds,
      selectedVisibilityLayer,
      sessionVisibilityOverrides,
      visibilityQuery.data,
    ],
  );
  const currentVisibilityLayerOption =
    visibilityLayerOptions.find(
      (option) => option.id === selectedVisibilityLayer,
    ) ?? visibilityLayerOptions[0];

  const counts = useMemo(
    () => countByClass(state.document.annotations, labelClasses),
    [labelClasses, state.document.annotations],
  );
  const highlightedAnnotationIds = useMemo(
    () => new Set(launchContext?.highlightAnnotationIds ?? []),
    [launchContext?.highlightAnnotationIds],
  );
  const highlightedPredictionIds = useMemo(
    () => new Set(launchContext?.highlightPredictionIds ?? []),
    [launchContext?.highlightPredictionIds],
  );

  const renderedAnnotations = useMemo(() => {
    if (!imageSize) {
      return state.document.annotations;
    }
    if (!interaction) {
      return state.document.annotations;
    }
    if (interaction.type === "moving") {
      const preview = translateAnnotations(
        Object.values(interaction.snapshot),
        {
          x: interaction.current.x - interaction.origin.x,
          y: interaction.current.y - interaction.origin.y,
        },
        imageSize,
      );
      return replaceAnnotations(state.document, preview).annotations;
    }
    if (interaction.type === "resizing") {
      const preview = resizeAnnotation(
        interaction.snapshot,
        interaction.handle,
        interaction.current,
        imageSize,
      );
      return replaceAnnotations(state.document, [preview]).annotations;
    }
    return state.document.annotations;
  }, [imageSize, interaction, state.document]);

  const draftBox = useMemo(() => {
    if (!imageSize || !interaction || interaction.type !== "drawing") {
      return null;
    }
    return createBoxFromPoints(
      interaction.start,
      interaction.current,
      imageSize,
    );
  }, [imageSize, interaction]);

  const annotationHiddenClassSet = useMemo(
    () => new Set(annotationVisibility.hiddenClassIds),
    [annotationVisibility.hiddenClassIds],
  );
  const predictionHiddenClassSet = useMemo(
    () => new Set(predictionVisibility.hiddenClassIds),
    [predictionVisibility.hiddenClassIds],
  );
  const currentLayerHiddenClassSet = useMemo(
    () => new Set(currentLayerVisibility.hiddenClassIds),
    [currentLayerVisibility.hiddenClassIds],
  );
  const dirty = isDirty(state);
  const canUndo = state.history.length > 0;
  const canRedo = state.future.length > 0;
  const selectableLabelClasses = useMemo(
    () => labelClasses.filter((labelClass) => labelClass.is_active !== false),
    [labelClasses],
  );
  const activeClassId =
    state.activeClassId &&
    selectableLabelClasses.some(
      (labelClass) => labelClass.id === state.activeClassId,
    )
      ? state.activeClassId
      : (selectableLabelClasses[0]?.id ?? null);
  const activeClass =
    (activeClassId ? labelClassesById.get(activeClassId) : null) ?? null;
  const saveStatusText = saveStateLabel(state.saveState, state.saveMessage);
  const selectedObjectCount =
    state.selectedIds.length + state.selectedMaskIds.length;
  const canReassignSelection =
    state.tool === "select" && state.selectedIds.length > 0;
  const visiblePredictions = useMemo(() => {
    if (!showPredictions) {
      return [];
    }
    const filtered = (predictionQuery.data?.items ?? []).filter(
      (proposal) =>
        !proposal.label_class_id ||
        !predictionHiddenClassSet.has(proposal.label_class_id),
    );
    return [...filtered].sort((left, right) => {
      if (predictionSort === "confidence-desc")
        return right.confidence - left.confidence;
      if (predictionSort === "class")
        return left.predicted_label.localeCompare(right.predicted_label);
      return left.confidence - right.confidence;
    });
  }, [
    predictionHiddenClassSet,
    predictionQuery.data?.items,
    predictionSort,
    showPredictions,
  ]);
  const predictionCounts = showPredictions
    ? (predictionQuery.data?.counts ?? {})
    : {};
  const allPredictions = predictionQuery.data?.items ?? [];
  const selectedPrediction =
    selectedPredictionIds.length === 1
      ? (allPredictions.find(
          (proposal) => proposal.id === selectedPredictionIds[0],
        ) ?? null)
      : null;
  const samReviewProposal = samReviewProposalId
    ? (allPredictions.find((proposal) => proposal.id === samReviewProposalId) ??
      null)
    : null;
  useEffect(() => {
    if (
      selectedPrediction?.geometry_kind === "raster_mask" &&
      selectedPrediction.review_status === "pending"
    ) {
      setSamReviewProposalId(selectedPrediction.id);
    } else if (selectedPrediction) setSamReviewProposalId(null);
  }, [selectedPrediction?.id, selectedPrediction?.review_status]);
  const selectedPredictionPosition = selectedPrediction
    ? visiblePredictions.findIndex(
        (proposal) => proposal.id === selectedPrediction.id,
      )
    : -1;
  const selectPredictionAt = useCallback(
    (index: number) => {
      const proposal = visiblePredictions[index];
      if (proposal) setSelectedPredictionIds([proposal.id]);
    },
    [visiblePredictions],
  );
  const assistSourcePrediction =
    (assistSession?.source_prediction_id
      ? (allPredictions.find(
          (proposal) => proposal.id === assistSession.source_prediction_id,
        ) ?? null)
      : null) ?? selectedPrediction;
  const visibleAnnotations = useMemo(
    () =>
      hideAnnotations
        ? []
        : renderedAnnotations.filter(
            (annotation) =>
              !annotationHiddenClassSet.has(annotation.label_class_id),
          ),
    [annotationHiddenClassSet, hideAnnotations, renderedAnnotations],
  );

  const setSessionVisibilityOverride = useCallback(
    (layerType: ClassVisibilityLayerType, hiddenClassIds: string[]) => {
      setSessionVisibilityOverrides((current) => ({
        ...current,
        [layerType]: sanitizeHiddenClassIds(hiddenClassIds, allClassIds),
      }));
    },
    [allClassIds],
  );

  const clearSessionVisibilityOverride = useCallback(
    (layerType: ClassVisibilityLayerType) => {
      setSessionVisibilityOverrides((current) => {
        if (!(layerType in current)) {
          return current;
        }
        const next = { ...current };
        delete next[layerType];
        return next;
      });
    },
    [],
  );

  const updateSelectedLayerVisibility = useCallback(
    (updater: (currentHiddenClassIds: string[]) => string[]) => {
      setSessionVisibilityOverrides((current) => {
        const baseHiddenClassIds =
          current[selectedVisibilityLayer] ??
          currentLayerVisibility.hiddenClassIds;
        return {
          ...current,
          [selectedVisibilityLayer]: sanitizeHiddenClassIds(
            updater(baseHiddenClassIds),
            allClassIds,
          ),
        };
      });
    },
    [
      allClassIds,
      currentLayerVisibility.hiddenClassIds,
      selectedVisibilityLayer,
    ],
  );

  const visibilityMutation = useMutation({
    mutationFn: async (
      input: VisibilityMutationInput,
    ): Promise<VisibilityMutationResult> => {
      const scopeKey: VisibilityScopeKey =
        input.target === "my_preference"
          ? "user_preferences"
          : "project_defaults";
      const layerLabel = visibilityLayerLabel(input.layerType);
      if (input.action === "save") {
        const payload = {
          hidden_class_ids: input.hiddenClassIds ?? [],
        };
        const state =
          input.target === "my_preference"
            ? await saveClassVisibilityPreference(
                project.id,
                input.layerType,
                payload,
              )
            : await saveProjectClassVisibilityDefault(
                project.id,
                input.layerType,
                payload,
              );
        return {
          layerType: input.layerType,
          scopeKey,
          state,
          statusMessage:
            input.target === "my_preference"
              ? `Saved my preference for ${layerLabel}.`
              : `Saved project default for ${layerLabel}.`,
        };
      }

      if (input.target === "my_preference") {
        await deleteClassVisibilityPreference(project.id, input.layerType);
      } else {
        await deleteProjectClassVisibilityDefault(project.id, input.layerType);
      }
      return {
        layerType: input.layerType,
        scopeKey,
        state: {
          saved: false,
          hidden_class_ids: [],
          updated_at: null,
          updated_by_identity: null,
        },
        statusMessage:
          input.target === "my_preference"
            ? `Reset my saved preference for ${layerLabel}.`
            : `Reset the project default for ${layerLabel}.`,
      };
    },
    onMutate: (input) => {
      const layerLabel = visibilityLayerLabel(input.layerType);
      setVisibilityStatusMessage(
        input.action === "save"
          ? `Saving ${layerLabel} visibility...`
          : `Resetting ${layerLabel} visibility...`,
      );
    },
    onSuccess: (result) => {
      queryClient.setQueryData<ClassVisibilityBundle>(
        ["class-visibility", project.id],
        (current) => {
          if (!current) {
            return current;
          }
          return updateClassVisibilityBundleScope(
            current,
            result.scopeKey,
            result.layerType,
            result.state,
          );
        },
      );
      setVisibilityStatusMessage(result.statusMessage);
    },
    onError: (error: Error) => {
      setVisibilityStatusMessage(error.message);
    },
  });

  useEffect(() => {
    const job = deployJobQuery.data;
    if (
      !job ||
      job.status !== "succeeded" ||
      completedDeployJobRef.current === job.id
    ) {
      return;
    }
    completedDeployJobRef.current = job.id;
    setShowPredictions(true);
    void queryClient.invalidateQueries({
      queryKey: ["predictions", currentImageId],
    });
  }, [currentImageId, deployJobQuery.data, queryClient]);

  const fullImageMutation = useMutation({
    mutationFn: () =>
      createSamImageProposals(
        project.id,
        currentImageId,
        samModelVariant,
        deployDevice,
      ),
    onSuccess: (job) => {
      completedDeployJobRef.current = null;
      setDeployJobId(job.id);
      localStorage.setItem(
        `reefvision-image-predictions:${currentImageId}`,
        job.id,
      );
      setShowPredictions(true);
      setPredictionModelFilter("");
      setPredictionClassFilter("");
      setPredictionConfidenceFilter("0");
      setPredictionStatusFilter("pending");
      setShortcutMessage(
        "Generating class-agnostic SAM proposals across the image. Proposals remain unverified until accepted.",
      );
    },
    onError: (error: Error) => setShortcutMessage(error.message),
  });
  const cancelImageMutation = useMutation({
    mutationFn: () => cancelJob(deployJobId!),
    onSuccess: () => {
      void deployJobQuery.refetch();
    },
  });
  useEffect(() => {
    setDeployJobId(
      localStorage.getItem(`reefvision-image-predictions:${currentImageId}`),
    );
    setSamReviewProposalId(null);
    setEditProposalId(null);
  }, [currentImageId]);

  const samInstallMutation = useMutation({
    mutationFn: (variant: string) => installSam2Model(project.id, variant),
    onSuccess: (job) => {
      setSamInstallJobId(job.id);
      setShortcutMessage(
        "SAM 2.1 is downloading. Your segmentation prompt is queued.",
      );
    },
    onError: (error: Error) => setShortcutMessage(error.message),
  });
  const samAssistMutation = useMutation({
    mutationFn: async (input: {
      imageId: string;
      variant: string;
      box: [number, number, number, number];
    }) => {
      const installed = (await getSam2Models(project.id)).find(
        (item) => item.variant === input.variant,
      );
      if (!installed?.ready) {
        if (installed?.installed) {
          throw new Error(installed.reason ?? "SAM runtime is not ready.");
        }
        setSamPendingBox(input);
        if (!samInstallJobId && !samInstallMutation.isPending) {
          samInstallMutation.mutate(input.variant);
        }
        return null;
      }
      return executeAdvancedProvider(project.id, "sam2", {
        task: "assist_segmentation",
        device: "auto",
        allow_model_download: false,
        prompt_fields: {
          image_id: input.imageId,
          sam2_variant: input.variant,
          box: input.box,
        },
      });
    },
    onSuccess: async (result, input) => {
      if (!result) return;
      if (currentImageIdRef.current !== input.imageId) return;
      setSamPendingBox(null);
      setSamInstallJobId(null);
      setSamPromptArmed(false);
      setShortcutMessage(
        "SAM mask created as a pending proposal. Review and accept it.",
      );
      setShowPredictions(true);
      setPredictionModelFilter("");
      setPredictionClassFilter("");
      setPredictionConfidenceFilter("0");
      setPredictionStatusFilter("pending");
      const proposalId = result.result.proposal_id;
      if (typeof proposalId === "string") {
        setSamReviewProposalId(proposalId);
        setIsolateSamReview(true);
        setSelectedPredictionIds([proposalId]);
      }
      await queryClient.invalidateQueries({
        queryKey: ["predictions", input.imageId],
      });
    },
    onError: (error: Error) => {
      setShortcutMessage(error.message);
      setSamPendingBox(null);
    },
  });

  useEffect(() => {
    if (!samPendingBox || samInstallJobQuery.data?.status !== "succeeded")
      return;
    if (
      samPendingBox.imageId !== currentImageId ||
      samPendingBox.variant !== samModelVariant
    ) {
      setSamPendingBox(null);
      setSamInstallJobId(null);
      return;
    }
    samAssistMutation.mutate(samPendingBox);
    // Job state changes only after the single background install completes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [samInstallJobQuery.data?.status]);

  useEffect(() => {
    if (
      samInstallJobQuery.data?.status === "failed" ||
      samInstallJobQuery.data?.status === "cancelled"
    ) {
      setShortcutMessage(
        samInstallJobQuery.data.error_message ??
          "SAM model download did not finish.",
      );
      setSamPendingBox(null);
      setSamInstallJobId(null);
    }
  }, [samInstallJobQuery.data]);

  const deployModelMutation = useMutation({
    mutationFn: (modelId: string) => {
      if (!modelId) {
        throw new Error("Choose a trained or imported project model first");
      }
      return createInferenceJob(project.id, {
        model_id: modelId,
        image_ids: [currentImageId],
        confidence_threshold: Number(deployConfidence),
        device: deployDevice,
      });
    },
    onSuccess: (job) => {
      completedDeployJobRef.current = null;
      setDeployJobId(job.id);
      localStorage.setItem(
        `reefvision-image-predictions:${currentImageId}`,
        job.id,
      );
    },
  });

  const deleteAssistSessionQuietly = useCallback(async (sessionId: string) => {
    try {
      await deleteAssistSession(sessionId);
    } catch {
      // Best-effort cleanup only.
    }
  }, []);

  const clearAssistSession = useCallback(
    async (deleteRemote: boolean) => {
      const currentSession = assistSessionRef.current;
      setAssistSession(null);
      if (deleteRemote && currentSession) {
        await deleteAssistSessionQuietly(currentSession.session_id);
      }
    },
    [deleteAssistSessionQuietly],
  );

  const acceptPredictionMutation = useMutation({
    mutationFn: (proposal: PredictionProposal) => {
      if (isDirty(stateRef.current))
        throw new Error(
          "Save your annotation edits before accepting predictions.",
        );
      return acceptPrediction(proposal.id, {
        label_class_id:
          predictionClassOverrides[proposal.id] ||
          proposal.label_class_id ||
          activeClassId,
        ...(predictionGeometryOverrides[proposal.id] ?? {
          x_min: proposal.x_min,
          y_min: proposal.y_min,
          x_max: proposal.x_max,
          y_max: proposal.y_max,
        }),
      });
    },
    onSuccess: async (_, proposal) => {
      if (samReviewProposalId === proposal.id) setSamReviewProposalId(null);
      const oldIndex = visiblePredictions.findIndex(
        (item) => item.id === proposal.id,
      );
      await Promise.all([
        predictionQuery.refetch(),
        sessionQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: ["images", project.id] }),
      ]);
      setSelectedPredictionIds(
        visiblePredictions.filter((item) => item.id !== proposal.id)[oldIndex]
          ?.id
          ? [
              visiblePredictions.filter((item) => item.id !== proposal.id)[
                oldIndex
              ].id,
            ]
          : [],
      );
    },
  });
  const promptAssistMutation = useMutation({
    mutationFn: async (proposal: PredictionProposal) => {
      if (!assistModelId) {
        throw new Error(
          "Select a ready Smart Mask model from the Model Catalog before running Prompt Assist",
        );
      }
      await clearAssistSession(true);
      const session = await createAssistSession(currentImageId, {
        model_id: assistModelId,
        device: "auto",
        source_prediction_id: proposal.id,
      });
      try {
        return await boxAssistSession(session.session_id, {
          x_min: proposal.x_min,
          y_min: proposal.y_min,
          x_max: proposal.x_max,
          y_max: proposal.y_max,
        });
      } catch (error) {
        await deleteAssistSessionQuietly(session.session_id);
        throw error;
      }
    },
    onSuccess: (session) => {
      setAssistSession(session);
    },
  });
  const acceptAssistMutation = useMutation({
    mutationFn: async () => {
      const session = assistSessionRef.current;
      if (!session || !session.candidate_box) {
        throw new Error(
          "Run Prompt Assist on a proposal before accepting a mask",
        );
      }
      const labelClassId =
        (assistSourcePrediction
          ? (predictionClassOverrides[assistSourcePrediction.id] ??
            assistSourcePrediction.label_class_id)
          : null) ?? activeClassId;
      if (!labelClassId) {
        throw new Error("Choose an annotation class before accepting the mask");
      }
      return acceptAssistSession(session.session_id, {
        label_class_id: labelClassId,
      });
    },
    onSuccess: async () => {
      setAssistSession(null);
      await Promise.all([
        predictionQuery.refetch(),
        sessionQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: ["images", project.id] }),
      ]);
      setSelectedPredictionIds([]);
    },
  });
  const discardAssistMutation = useMutation({
    mutationFn: async () => {
      await clearAssistSession(true);
    },
  });
  const rejectPredictionMutation = useMutation({
    mutationFn: (proposalId: string) => rejectPrediction(proposalId),
    onSuccess: async (_, proposalId) => {
      if (samReviewProposalId === proposalId) setSamReviewProposalId(null);
      const oldIndex = visiblePredictions.findIndex(
        (item) => item.id === proposalId,
      );
      await predictionQuery.refetch();
      const remaining = visiblePredictions.filter(
        (item) => item.id !== proposalId,
      );
      setSelectedPredictionIds(
        remaining[oldIndex]?.id ? [remaining[oldIndex].id] : [],
      );
    },
  });
  const bulkReviewMutation = useMutation({
    mutationFn: ({
      action,
      selected,
    }: {
      action: "accept" | "reject";
      selected: boolean;
    }) => {
      if (action === "accept" && isDirty(stateRef.current))
        throw new Error(
          "Save your annotation edits before accepting predictions.",
        );
      const proposals = visiblePredictions.filter(
        (proposal) => !selected || selectedPredictionIds.includes(proposal.id),
      );
      const unlabeled = proposals.some((proposal) => !proposal.label_class_id);
      if (action === "accept" && unlabeled && !activeClassId)
        throw new Error(
          "Choose a class before accepting class-agnostic proposals.",
        );
      if (
        action === "accept" &&
        unlabeled &&
        proposals.some((proposal) => proposal.label_class_id)
      )
        throw new Error(
          "Review class-agnostic and class-aware proposals separately to preserve their classes.",
        );
      return bulkReviewPredictions({
        action,
        proposal_ids: proposals.map((proposal) => proposal.id),
        ...(action === "accept" && unlabeled
          ? { label_class_id: activeClassId! }
          : {}),
      });
    },
    onSuccess: async (_, { action }) => {
      await Promise.all([
        predictionQuery.refetch(),
        action === "accept" ? sessionQuery.refetch() : Promise.resolve(),
        queryClient.invalidateQueries({ queryKey: ["images", project.id] }),
      ]);
      setSelectedPredictionIds([]);
      setSamReviewProposalId(null);
    },
  });

  const setSelection = useCallback((selection: string[]) => {
    dispatch({ type: "setSelection", selection });
  }, []);

  const setMaskSelection = useCallback((selection: string[]) => {
    dispatch({ type: "setMaskSelection", selection });
  }, []);

  const commitDocument = useCallback(
    (
      document: AnnotationDocument,
      selection?: string[],
      maskSelection?: string[],
    ) => {
      dispatch({
        type: "commitDocument",
        document,
        selection,
        maskSelection,
      });
    },
    [],
  );

  const applyClassToSelection = useCallback(
    (classId: string) => {
      dispatch({ type: "setActiveClassId", classId });
      if (state.tool !== "select" || state.selectedIds.length === 0) {
        return;
      }
      const nextDocument = {
        ...state.document,
        annotations: state.document.annotations.map((annotation) =>
          state.selectedIds.includes(annotation.id)
            ? { ...annotation, label_class_id: classId }
            : annotation,
        ),
      };
      commitDocument(nextDocument, state.selectedIds);
    },
    [commitDocument, state.document, state.selectedIds, state.tool],
  );

  const saveCurrentVisibilityAsMyPreference = useCallback(() => {
    visibilityMutation.mutate({
      action: "save",
      layerType: selectedVisibilityLayer,
      target: "my_preference",
      hiddenClassIds: currentLayerVisibility.hiddenClassIds,
    });
  }, [
    currentLayerVisibility.hiddenClassIds,
    selectedVisibilityLayer,
    visibilityMutation,
  ]);

  const saveCurrentVisibilityAsProjectDefault = useCallback(() => {
    visibilityMutation.mutate({
      action: "save",
      layerType: selectedVisibilityLayer,
      target: "project_default",
      hiddenClassIds: currentLayerVisibility.hiddenClassIds,
    });
  }, [
    currentLayerVisibility.hiddenClassIds,
    selectedVisibilityLayer,
    visibilityMutation,
  ]);

  const resetMyVisibilityPreferences = useCallback(() => {
    visibilityMutation.mutate({
      action: "reset",
      layerType: selectedVisibilityLayer,
      target: "my_preference",
    });
  }, [selectedVisibilityLayer, visibilityMutation]);

  const copyCurrentVisibilityToProjectDefaults = useCallback(() => {
    visibilityMutation.mutate({
      action: "save",
      layerType: selectedVisibilityLayer,
      target: "project_default",
      hiddenClassIds: currentLayerVisibility.hiddenClassIds,
    });
  }, [
    currentLayerVisibility.hiddenClassIds,
    selectedVisibilityLayer,
    visibilityMutation,
  ]);

  const applyProjectDefaultsToMyPreferences = useCallback(() => {
    if (!currentLayerVisibility.projectDefault.saved) {
      visibilityMutation.mutate({
        action: "reset",
        layerType: selectedVisibilityLayer,
        target: "my_preference",
      });
      return;
    }
    visibilityMutation.mutate({
      action: "save",
      layerType: selectedVisibilityLayer,
      target: "my_preference",
      hiddenClassIds: currentLayerVisibility.projectDefault.hidden_class_ids,
    });
  }, [
    currentLayerVisibility.projectDefault.hidden_class_ids,
    currentLayerVisibility.projectDefault.saved,
    selectedVisibilityLayer,
    visibilityMutation,
  ]);

  const resetSessionVisibility = useCallback(() => {
    clearSessionVisibilityOverride(selectedVisibilityLayer);
    setVisibilityStatusMessage(
      `Reset the session override for ${visibilityLayerLabel(selectedVisibilityLayer)}.`,
    );
  }, [clearSessionVisibilityOverride, selectedVisibilityLayer]);

  const resetToProjectDefaults = useCallback(() => {
    const nextHiddenClassIds = currentLayerVisibility.projectDefault.saved
      ? currentLayerVisibility.projectDefault.hidden_class_ids
      : [];
    setSessionVisibilityOverride(selectedVisibilityLayer, nextHiddenClassIds);
    setVisibilityStatusMessage(
      currentLayerVisibility.projectDefault.saved
        ? `Applied the project default to this session for ${visibilityLayerLabel(selectedVisibilityLayer)}.`
        : `No project default is saved for ${visibilityLayerLabel(selectedVisibilityLayer)}. This session now uses visible-by-default.`,
    );
  }, [
    currentLayerVisibility.projectDefault.hidden_class_ids,
    currentLayerVisibility.projectDefault.saved,
    selectedVisibilityLayer,
    setSessionVisibilityOverride,
  ]);

  const toggleCurrentLayerClassVisibility = useCallback(
    (classId: string) => {
      updateSelectedLayerVisibility((currentHiddenClassIds) =>
        currentHiddenClassIds.includes(classId)
          ? currentHiddenClassIds.filter((item) => item !== classId)
          : [...currentHiddenClassIds, classId],
      );
    },
    [updateSelectedLayerVisibility],
  );

  const deleteSelection = useCallback(() => {
    if (state.selectedIds.length === 0 && state.selectedMaskIds.length === 0) {
      return;
    }
    const withoutBoxes = {
      ...state.document,
      annotations: state.document.annotations.filter(
        (annotation) => !state.selectedIds.includes(annotation.id),
      ),
    };
    const nextDocument = deleteMaskAnnotations(
      withoutBoxes,
      state.selectedMaskIds,
    );
    commitDocument(nextDocument, [], []);
  }, [
    commitDocument,
    state.document,
    state.selectedIds,
    state.selectedMaskIds,
  ]);

  const copySelection = useCallback((): AnnotationClipboard | null => {
    const snapshot = stateRef.current;
    const image = sessionQuery.data?.image;
    if (
      !image ||
      (snapshot.selectedIds.length === 0 &&
        snapshot.selectedMaskIds.length === 0)
    ) {
      setShortcutMessage("Select an annotation before copying.");
      return null;
    }
    const clipboard = copyAnnotations(
      snapshot.document,
      snapshot.selectedIds,
      snapshot.selectedMaskIds,
      {
        id: image.id,
        projectId: project.id,
        width: image.width_px,
        height: image.height_px,
      },
    );
    annotationClipboardRef.current = clipboard;
    writeInternalAnnotationClipboard(clipboard);
    const count = clipboard.items.length;
    setShortcutMessage(
      clipboard.skippedRasterCount > 0
        ? `Copied ${count} editable annotation${count === 1 ? "" : "s"}. ${clipboard.skippedRasterCount} raster mask${clipboard.skippedRasterCount === 1 ? " was" : "s were"} skipped; raster pixels require the brush workspace.`
        : `Copied ${count} annotation${count === 1 ? "" : "s"} to ReefVision's internal clipboard.`,
    );
    return clipboard;
  }, [project.id, sessionQuery.data?.image]);

  const pasteClipboard = useCallback(
    (
      clipboard = annotationClipboardRef.current ??
        readInternalAnnotationClipboard(),
    ) => {
      const image = sessionQuery.data?.image;
      if (!image || !clipboard) {
        setShortcutMessage("Copy an annotation before pasting.");
        return;
      }
      const result = pasteAnnotations(
        clipboard,
        {
          id: image.id,
          projectId: project.id,
          width: image.width_px,
          height: image.height_px,
        },
        makeAnnotationId,
      );
      if (!result.ok) {
        setShortcutMessage(result.reason);
        return;
      }
      const snapshot = stateRef.current;
      const annotationIds = result.annotations.map((item) => item.id);
      const maskIds = result.maskAnnotations.map((item) => item.id);
      commitDocument(
        {
          ...snapshot.document,
          // New copies must be reviewed before this image is eligible for verified learning.
          annotation_status:
            snapshot.document.annotation_status === "reviewed"
              ? "in_progress"
              : snapshot.document.annotation_status,
          annotations: [
            ...snapshot.document.annotations,
            ...result.annotations,
          ],
          maskAnnotations: [
            ...snapshot.document.maskAnnotations,
            ...result.maskAnnotations,
          ],
        },
        annotationIds,
        maskIds,
      );
      annotationClipboardRef.current = result.nextClipboard;
      writeInternalAnnotationClipboard(result.nextClipboard);
      const count = annotationIds.length + maskIds.length;
      setShortcutMessage(
        `Pasted ${count} annotation${count === 1 ? "" : "s"} in source-image coordinates. New polygon copies require review.`,
      );
    },
    [commitDocument, project.id, sessionQuery.data?.image],
  );

  const duplicateSelection = useCallback(() => {
    const clipboard = copySelection();
    if (clipboard?.items.length) {
      pasteClipboard(clipboard);
    }
  }, [copySelection, pasteClipboard]);

  const saveNow = useCallback((): Promise<boolean> => {
    if (savePromiseRef.current) {
      return savePromiseRef.current;
    }
    const snapshot = stateRef.current;
    if (!isDirty(snapshot)) {
      return Promise.resolve(true);
    }
    const sentVersion = snapshot.documentVersion;
    dispatch({ type: "saveStarted", sentVersion });
    const promise = saveAnnotations(
      currentImageIdRef.current,
      toAnnotationSavePayload(snapshot),
    )
      .then(async (response) => {
        queryClient.setQueryData<AnnotationSession>(
          ["annotation-session", currentImageIdRef.current],
          (current) =>
            current
              ? {
                  ...current,
                  image: response.image,
                  annotations: response.annotations,
                  counts_by_class: response.counts_by_class,
                }
              : current,
        );
        dispatch({ type: "saveSucceeded", sentVersion, response });
        await queryClient.invalidateQueries({
          queryKey: ["images", project.id],
        });
        return true;
      })
      .catch((error: unknown) => {
        const message =
          error instanceof Error ? error.message : "Saving annotations failed";
        dispatch({
          type: "saveFailed",
          message,
          conflict: message.toLowerCase().includes("conflict"),
        });
        return false;
      })
      .finally(() => {
        savePromiseRef.current = null;
      });
    savePromiseRef.current = promise;
    return promise;
  }, [project.id, queryClient]);

  const flushPendingSave = useCallback(async (): Promise<boolean> => {
    if (savePromiseRef.current) {
      await savePromiseRef.current;
    }
    if (isDirty(stateRef.current)) {
      return saveNow();
    }
    return true;
  }, [saveNow]);

  useEffect(() => {
    if (!sessionQuery.data || interaction) {
      return;
    }
    if (!dirty || state.saveState === "saving") {
      return;
    }
    const timeoutId = window.setTimeout(() => {
      void saveNow();
    }, 700);
    return () => window.clearTimeout(timeoutId);
  }, [dirty, interaction, saveNow, sessionQuery.data, state.saveState]);

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!isDirty(stateRef.current)) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);

  const runSamOnBox = useCallback(
    (box: { x_min: number; y_min: number; x_max: number; y_max: number }) => {
      if (samAssistMutation.isPending) {
        setShortcutMessage("A SAM segmentation is already running.");
        return;
      }
      const prompt: [number, number, number, number] = [
        box.x_min,
        box.y_min,
        box.x_max,
        box.y_max,
      ];
      if (prompt[2] <= prompt[0] || prompt[3] <= prompt[1]) {
        setShortcutMessage("Draw a non-empty box for SAM segmentation.");
        return;
      }
      setSamPromptArmed(false);
      setShortcutMessage("Running SAM 2.1 segmentation...");
      samAssistMutation.mutate({
        imageId: currentImageId,
        variant: samModelVariant,
        box: prompt,
      });
    },
    [currentImageId, samModelVariant, samAssistMutation],
  );

  const refinement = useMaskRefinement({
    imageId: currentImageId,
    variant: samModelVariant,
    device: deployDevice,
    selectedMasks: state.document.maskAnnotations.filter((mask) =>
      state.selectedMaskIds.includes(mask.id),
    ),
    boxSelectionCount: state.selectedIds.length,
    dirty,
    imageWidth: sessionQuery.data?.image.width_px ?? 1,
    imageHeight: sessionQuery.data?.image.height_px ?? 1,
    message: setShortcutMessage,
    refresh: async () => {
      await sessionQuery.refetch();
      await queryClient.invalidateQueries({ queryKey: ["images", project.id] });
    },
  });
  const imagePredictionBusy =
    fullImageMutation.isPending ||
    deployModelMutation.isPending ||
    ["queued", "running", "cancel_requested"].includes(
      deployJobQuery.data?.status ?? "",
    );
  const predictImage = () => {
    if (imagePredictionBusy) {
      setShortcutMessage("Image predictions are already running.");
      return;
    }
    if (dirty) {
      setShortcutMessage(
        "Save your annotation edits before generating predictions.",
      );
      return;
    }
    setShowPredictions(true);
    if (activeDetectorModelId)
      deployModelMutation.mutate(activeDetectorModelId);
    else fullImageMutation.mutate();
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) {
        return;
      }

      if (event.key === "Escape") {
        if (interactionRef.current || samPromptArmed || editProposalId) {
          event.preventDefault();
          setInteraction(null);
          setSamPromptArmed(false);
          setEditProposalId(null);
        }
        return;
      }

      // Shift+Digit1/2 are editor actions, while plain 1–9 still choose classes.
      if (
        event.shiftKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        event.code === "Digit1"
      ) {
        event.preventDefault();
        predictImage();
        return;
      }
      if (
        event.shiftKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        event.code === "Digit2"
      ) {
        event.preventDefault();
        refinement.start();
        return;
      }

      const numberIndex =
        event.key.length === 1 ? Number.parseInt(event.key, 10) : Number.NaN;
      if (
        Number.isInteger(numberIndex) &&
        numberIndex >= 1 &&
        numberIndex <= 9
      ) {
        const labelClass = labelClasses[numberIndex - 1];
        if (labelClass) {
          event.preventDefault();
          applyClassToSelection(labelClass.id);
        }
        return;
      }

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        dispatch({ type: event.shiftKey ? "redo" : "undo" });
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        dispatch({ type: "redo" });
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copySelection();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
        event.preventDefault();
        pasteClipboard();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
        event.preventDefault();
        duplicateSelection();
        return;
      }

      switch (event.key.toLowerCase()) {
        case "j":
          if (selectedPredictionPosition >= 0) {
            event.preventDefault();
            selectPredictionAt(selectedPredictionPosition + 1);
          }
          break;
        case "k":
          if (selectedPredictionPosition >= 0) {
            event.preventDefault();
            selectPredictionAt(selectedPredictionPosition - 1);
          }
          break;
        case "b":
          event.preventDefault();
          dispatch({ type: "setTool", tool: "box" });
          break;
        case "v":
          event.preventDefault();
          dispatch({ type: "setTool", tool: "select" });
          break;
        case "p":
          event.preventDefault();
          dispatch({ type: "setTool", tool: "pan" });
          break;
        case "f":
          event.preventDefault();
          fitToScreen();
          break;
        case "h":
          event.preventDefault();
          setHideAnnotations((current) => !current);
          break;
        case "a":
          if (sessionQuery.data?.previous_image_id) {
            event.preventDefault();
            void (async () => {
              if (await flushPendingSave()) {
                setCurrentImageId(
                  sessionQuery.data.previous_image_id as string,
                );
              }
            })();
          }
          break;
        case "d":
          if (sessionQuery.data?.next_image_id) {
            event.preventDefault();
            void (async () => {
              if (await flushPendingSave()) {
                setCurrentImageId(sessionQuery.data.next_image_id as string);
              }
            })();
          }
          break;
        case "delete":
        case "backspace":
          event.preventDefault();
          deleteSelection();
          break;
        default:
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    applyClassToSelection,
    currentImageId,
    activeDetectorModelId,
    deployModelMutation,
    predictImage,
    refinement,
    deployJobQuery.data?.status,
    samAssistMutation,
    samInstallMutation.isPending,
    samPendingBox,
    samModelVariant,
    state.document.annotations,
    state.selectedIds,
    editProposalId,
    deleteSelection,
    copySelection,
    pasteClipboard,
    duplicateSelection,
    fitToScreen,
    flushPendingSave,
    labelClasses,
    selectPredictionAt,
    selectedPredictionPosition,
    sessionQuery.data?.next_image_id,
    sessionQuery.data?.previous_image_id,
  ]);

  useEffect(() => {
    if (!interaction) {
      return;
    }

    const handlePointerMove = (event: PointerEvent) => {
      const currentInteraction = interactionRef.current;
      const activeView = viewRef.current;
      const svg = svgRef.current;
      if (!currentInteraction) {
        return;
      }
      if (currentInteraction.type === "panning") {
        setView({
          ...currentInteraction.initialView,
          offsetX:
            currentInteraction.initialView.offsetX +
            (event.clientX - currentInteraction.origin.x),
          offsetY:
            currentInteraction.initialView.offsetY +
            (event.clientY - currentInteraction.origin.y),
        });
        return;
      }
      if (!activeView || !svg) {
        return;
      }
      const point = clientPointInSvg(
        svg,
        event.clientX,
        event.clientY,
        activeView,
      );
      setInteraction((active) =>
        active && active.type !== "panning"
          ? { ...active, current: point }
          : active,
      );
    };

    const handlePointerUp = () => {
      const currentInteraction = interactionRef.current;
      const currentState = stateRef.current;
      if (!currentInteraction || !imageSize) {
        setInteraction(null);
        return;
      }
      if (currentInteraction.type === "drawing") {
        const box = createBoxFromPoints(
          currentInteraction.start,
          currentInteraction.current,
          imageSize,
        );
        if (samPromptArmed) {
          runSamOnBox(box);
        } else if (activeClassId) {
          const annotation: EditorAnnotation = {
            id: makeAnnotationId(),
            label_class_id: activeClassId,
            ...box,
          };
          if (boxArea(annotation) >= 1) {
            commitDocument(
              {
                ...currentState.document,
                annotation_status:
                  currentState.document.annotation_status === "unannotated"
                    ? "in_progress"
                    : currentState.document.annotation_status,
                annotations: [...currentState.document.annotations, annotation],
              },
              [annotation.id],
            );
          }
        }
      }

      if (currentInteraction.type === "moving") {
        const moved = translateAnnotations(
          Object.values(currentInteraction.snapshot),
          {
            x: currentInteraction.current.x - currentInteraction.origin.x,
            y: currentInteraction.current.y - currentInteraction.origin.y,
          },
          imageSize,
        );
        commitDocument(
          replaceAnnotations(currentState.document, moved),
          currentInteraction.selection,
        );
      }

      if (currentInteraction.type === "resizing") {
        const resized = resizeAnnotation(
          currentInteraction.snapshot,
          currentInteraction.handle,
          currentInteraction.current,
          imageSize,
        );
        commitDocument(replaceAnnotations(currentState.document, [resized]), [
          currentInteraction.annotationId,
        ]);
      }

      setInteraction(null);
    };

    const handlePointerCancel = () => {
      interactionRef.current = null;
      setInteraction(null);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerCancel);
    window.addEventListener("blur", handlePointerCancel);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerCancel);
      window.removeEventListener("blur", handlePointerCancel);
    };
  }, [
    activeClassId,
    commitDocument,
    imageSize,
    interaction,
    samPromptArmed,
    runSamOnBox,
  ]);

  const navigateToImage = useCallback(
    async (imageId: string | null) => {
      if (!imageId) {
        return;
      }
      if (!(await flushPendingSave())) {
        if (!isDirty(stateRef.current)) {
          return;
        }
        if (!confirmDiscardUnsavedEdits("open another image")) {
          return;
        }
      }
      await clearAssistSession(true);
      setInteraction(null);
      startTransition(() => {
        setCurrentImageId(imageId);
      });
    },
    [clearAssistSession, flushPendingSave],
  );

  const handleClose = useCallback(async () => {
    if (!(await flushPendingSave())) {
      if (!isDirty(stateRef.current)) {
        return;
      }
      if (!confirmDiscardUnsavedEdits("return to the gallery")) {
        return;
      }
    }
    await clearAssistSession(true);
    setInteraction(null);
    onClose();
  }, [clearAssistSession, flushPendingSave, onClose]);

  useEffect(() => {
    return () => {
      const sessionId = assistSessionRef.current?.session_id;
      if (sessionId) {
        void deleteAssistSessionQuietly(sessionId);
      }
    };
  }, [deleteAssistSessionQuietly]);

  const handleCanvasPointerDown = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      if (!currentView || !imageSize) return;
      if (
        event.button === 1 ||
        event.button === 2 ||
        (event.button === 0 && event.altKey) ||
        (state.tool === "pan" && !samPromptArmed)
      ) {
        event.preventDefault();
        setInteraction({
          type: "panning",
          origin: { x: event.clientX, y: event.clientY },
          initialView: currentView,
        });
        return;
      }
      const svg = svgRef.current;
      if (!svg) {
        return;
      }
      const point = clientPointInSvg(
        svg,
        event.clientX,
        event.clientY,
        currentView,
      );

      if (samPromptArmed || (state.tool === "box" && activeClassId)) {
        setSelection([]);
        setMaskSelection([]);
        setInteraction({
          type: "drawing",
          start: point,
          current: point,
        });
        return;
      }

      setSelection([]);
      setMaskSelection([]);
    },
    [
      activeClassId,
      currentView,
      imageSize,
      samPromptArmed,
      setMaskSelection,
      setSelection,
      state.tool,
    ],
  );

  const handleCanvasWheel = useCallback(
    (event: ReactWheelEvent<SVGSVGElement>) => {
      if (!currentView) {
        return;
      }
      event.preventDefault();
      const rect = event.currentTarget.getBoundingClientRect();
      const screenPoint = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      const direction = event.deltaY > 0 ? 1 / 1.08 : 1.08;
      setView(
        zoomAtPoint(
          currentView,
          screenPoint,
          clampScale(currentView.scale * direction),
        ),
      );
    },
    [currentView],
  );

  const handleAnnotationPointerDown = useCallback(
    (event: ReactPointerEvent<SVGRectElement>, annotationId: string) => {
      event.stopPropagation();
      if (!currentView || !imageSize) {
        return;
      }
      if (
        event.button === 1 ||
        event.button === 2 ||
        (event.button === 0 && event.altKey)
      ) {
        event.preventDefault();
        setInteraction({
          type: "panning",
          origin: { x: event.clientX, y: event.clientY },
          initialView: currentView,
        });
        return;
      }
      if (state.tool === "pan") {
        event.preventDefault();
        setInteraction({
          type: "panning",
          origin: { x: event.clientX, y: event.clientY },
          initialView: currentView,
        });
        return;
      }
      if (state.tool !== "select") {
        setSelection([annotationId]);
        return;
      }
      const svg = svgRef.current;
      if (!svg) {
        return;
      }
      const point = clientPointInSvg(
        svg,
        event.clientX,
        event.clientY,
        currentView,
      );
      const additive = event.metaKey || event.ctrlKey || event.shiftKey;
      const selection = additive
        ? selectionToggled(state.selectedIds, annotationId)
        : state.selectedIds.includes(annotationId)
          ? state.selectedIds
          : [annotationId];
      if (!additive) {
        setMaskSelection([]);
      }
      setSelection(selection);
      const snapshot = Object.fromEntries(
        state.document.annotations
          .filter((annotation) => selection.includes(annotation.id))
          .map((annotation) => [annotation.id, annotation]),
      );
      setInteraction({
        type: "moving",
        origin: point,
        selection,
        snapshot,
        current: point,
      });
    },
    [
      currentView,
      imageSize,
      setMaskSelection,
      setSelection,
      state.document.annotations,
      state.selectedIds,
      state.tool,
    ],
  );

  const handleResizePointerDown = useCallback(
    (
      event: ReactPointerEvent<SVGCircleElement>,
      annotation: EditorAnnotation,
      handle: ResizeHandle,
    ) => {
      event.stopPropagation();
      if (!currentView) {
        return;
      }
      if (
        event.button === 1 ||
        event.button === 2 ||
        (event.button === 0 && event.altKey)
      ) {
        event.preventDefault();
        setInteraction({
          type: "panning",
          origin: { x: event.clientX, y: event.clientY },
          initialView: currentView,
        });
        return;
      }
      const svg = svgRef.current;
      if (!svg) {
        return;
      }
      const point = clientPointInSvg(
        svg,
        event.clientX,
        event.clientY,
        currentView,
      );
      setSelection([annotation.id]);
      setInteraction({
        type: "resizing",
        handle,
        annotationId: annotation.id,
        snapshot: annotation,
        current: point,
      });
    },
    [currentView, setSelection],
  );

  const handleMaskPointerDown = useCallback(
    (event: ReactPointerEvent<SVGElement>, maskId: string) => {
      event.stopPropagation();
      if (
        currentView &&
        (event.button === 1 ||
          event.button === 2 ||
          (event.button === 0 && event.altKey) ||
          state.tool === "pan")
      ) {
        event.preventDefault();
        setInteraction({
          type: "panning",
          origin: { x: event.clientX, y: event.clientY },
          initialView: currentView,
        });
        return;
      }
      if (state.tool !== "select") {
        return;
      }
      const additive = event.metaKey || event.ctrlKey || event.shiftKey;
      if (!additive) {
        setSelection([]);
        setMaskSelection([maskId]);
        return;
      }
      setMaskSelection(selectionToggled(state.selectedMaskIds, maskId));
    },
    [
      currentView,
      setMaskSelection,
      setSelection,
      state.selectedMaskIds,
      state.tool,
    ],
  );

  function togglePredictionSelection(proposalId: string) {
    setSelectedPredictionIds([proposalId]);
  }

  if (sessionQuery.isPending || !sessionQuery.data || !imageSize) {
    return (
      <div className="annotation-editor-shell">
        <div className="annotation-editor-splash">
          {sessionQuery.error ? (
            <ErrorState
              title="The annotation editor could not be loaded"
              message="ReefVision could not load this image and its annotations."
              error={sessionQuery.error}
              onRetry={() => void sessionQuery.refetch()}
              onBack={() => void handleClose()}
            />
          ) : (
            <LoadingState
              title="Loading annotation editor"
              description="Preparing the image, classes, and saved annotations."
            />
          )}
        </div>
      </div>
    );
  }

  const resolvedView =
    currentView ??
    fitTransform(imageSize, {
      width: containerSize.width || 1200,
      height: containerSize.height || 780,
    });
  const image = sessionQuery.data.image;
  const preloadIsCurrent =
    imagePreload?.imageId === image.id &&
    imagePreload?.retry === fullImageRetry;
  const fullImageLoaded = preloadIsCurrent && imagePreload?.phase === "loaded";
  const fullImageFailed = preloadIsCurrent && imagePreload?.phase === "failed";
  const fullImageLoading =
    !preloadIsCurrent || imagePreload?.phase === "loading";
  const currentLabelClasses = labelClasses;
  const strokeScale = 1 / resolvedView.scale;
  const handleRadius = Math.max(4 * strokeScale, 2);
  const imageHref = annotationImageSource(
    image.id,
    image.thumbnail_path,
    fullImageLoaded,
    fullImageRetry,
  );
  const imageRenderKey = `${image.id}:${fullImageRetry}:${fullImageLoaded}`;
  const assistAcceptLabelClassId =
    (assistSourcePrediction
      ? (predictionClassOverrides[assistSourcePrediction.id] ??
        assistSourcePrediction.label_class_id)
      : null) ?? activeClassId;
  const assistAcceptLabelClass =
    (assistAcceptLabelClassId
      ? labelClassesById.get(assistAcceptLabelClassId)
      : null) ?? null;
  const assistMaskHref = assistSession?.candidate_mask_png_base64
    ? `data:image/png;base64,${assistSession.candidate_mask_png_base64}`
    : null;

  return (
    <div className="annotation-editor-shell" data-testid="annotation-editor">
      <header className="annotation-editor-topbar">
        <div>
          <p className="eyebrow">Manual annotation editor</p>
          <h2>{image.original_filename}</h2>
          <p className="annotation-editor-subtitle">
            {project.name} | {image.width_px} x {image.height_px} px
          </p>
          {launchContext?.contextTitle && (
            <div className="annotation-editor-context">
              <strong>{launchContext.contextTitle}</strong>
              {launchContext.contextDescription && (
                <p>{launchContext.contextDescription}</p>
              )}
            </div>
          )}
        </div>
        <div className="annotation-editor-actions">
          <button
            type="button"
            className="secondary"
            title="Fit image to view (F)"
            aria-keyshortcuts="F"
            onClick={fitToScreen}
          >
            Fit (F)
          </button>
          <button type="button" className="secondary" onClick={showActualSize}>
            Actual Size (100%)
          </button>
          <button type="button" className="secondary" onClick={fitToScreen}>
            Reset View
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => setHideAnnotations((current) => !current)}
          >
            {hideAnnotations ? "Show boxes (H)" : "Hide boxes (H)"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => setShowPredictions((current) => !current)}
          >
            {showPredictions ? "Hide predictions" : "Show predictions"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => setQuickReviewOpen(true)}
            title="Open a floating low-confidence prediction reviewer"
          >
            Quick review (≤{quickReviewConfidence}%)
          </button>
          <button
            type="button"
            className="secondary"
            disabled={
              samAssistMutation.isPending || samInstallMutation.isPending
            }
            title="Segment one selected box, or draw a SAM prompt box"
            onClick={() => {
              const box = state.document.annotations.find((annotation) =>
                state.selectedIds.includes(annotation.id),
              );
              if (box) runSamOnBox(box);
              else {
                setSamPromptArmed(true);
                setShortcutMessage(
                  "SAM prompt mode: draw a box around an object.",
                );
              }
            }}
          >
            SAM box prompt
          </button>
          <button
            type="button"
            className="secondary"
            disabled={imagePredictionBusy}
            title="Generate full-image proposals (Shift+1)"
            aria-keyshortcuts="Shift+1"
            onClick={predictImage}
          >
            Predict objects in image (Shift+1)
          </button>
          <button
            type="button"
            className="secondary"
            disabled={refinement.busy || Boolean(refinement.reason)}
            aria-keyshortcuts="Shift+2"
            title={
              refinement.reason ??
              "Compare a proposed boundary before replacing this mask"
            }
            onClick={refinement.start}
          >
            Refine selected mask (Shift+2)
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => setLearningOpen((value) => !value)}
          >
            Improve Predictions
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void saveNow()}
          >
            Save now
          </button>
          <button type="button" onClick={() => void handleClose()}>
            {launchContext?.returnLabel ?? "Back to gallery"}
          </button>
        </div>
      </header>

      <div className="annotation-editor-body">
        <aside className="annotation-tool-rail" aria-label="Annotation tools">
          <button
            type="button"
            aria-label="Select tool"
            title="Select and edit objects (V)"
            aria-keyshortcuts="V"
            aria-pressed={state.tool === "select"}
            className={state.tool === "select" ? "active" : "secondary"}
            onClick={() => dispatch({ type: "setTool", tool: "select" })}
          >
            <span aria-hidden="true">↖</span>
            <small>Select</small>
          </button>
          <button
            type="button"
            aria-label="Pan tool"
            title="Pan the image (P)"
            aria-keyshortcuts="P"
            aria-pressed={state.tool === "pan"}
            className={state.tool === "pan" ? "active" : "secondary"}
            onClick={() => dispatch({ type: "setTool", tool: "pan" })}
          >
            <span aria-hidden="true">✥</span>
            <small>Pan</small>
          </button>
          <button
            type="button"
            aria-label="Box tool"
            title="Draw bounding boxes (B)"
            aria-keyshortcuts="B"
            aria-pressed={state.tool === "box"}
            className={state.tool === "box" ? "active" : "secondary"}
            disabled={!activeClassId}
            onClick={() => dispatch({ type: "setTool", tool: "box" })}
          >
            <span aria-hidden="true">□</span>
            <small>Box</small>
          </button>
        </aside>
        <aside className="annotation-editor-sidebar">
          <div className="annotation-inspector-heading">
            <p className="eyebrow">Inspector</p>
            <h3>Image annotations</h3>
          </div>
          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Workflow</p>
                <h3>Image state</h3>
              </div>
              <span
                className={`save-chip save-${state.saveState}`}
                data-testid="annotation-save-state"
              >
                {saveStatusText}
              </span>
            </div>
            <label>
              Annotation status
              <select
                value={state.document.annotation_status}
                onChange={(event) =>
                  commitDocument({
                    ...state.document,
                    annotation_status: event.target
                      .value as AnnotationDocument["annotation_status"],
                  })
                }
              >
                <option value="unannotated">Unannotated</option>
                <option value="in_progress">In progress</option>
                <option value="annotated">Annotated</option>
                <option value="reviewed">Reviewed</option>
                <option value="excluded">Excluded</option>
              </select>
            </label>
            {(state.saveState === "error" ||
              state.saveState === "conflict") && (
              <div className="editor-message error">
                <p>{state.saveMessage}</p>
                <div className="annotation-editor-inline-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => void saveNow()}
                  >
                    Retry save
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={async () => {
                      const shouldReload = window.confirm(
                        "Discard unsaved local edits and reload the latest saved revision?",
                      );
                      if (!shouldReload) {
                        return;
                      }
                      await sessionQuery.refetch();
                    }}
                  >
                    Reload latest
                  </button>
                </div>
              </div>
            )}
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Project model</p>
                <h3>Deploy trained model</h3>
              </div>
              <span>{detectorModels.data?.length ?? 0} available</span>
            </div>
            <label>
              Trained or imported model
              <select
                value={deployModelId}
                onChange={(event) => setDeployModelId(event.target.value)}
                disabled={!detectorModels.data?.length}
              >
                {detectorModels.data?.length ? (
                  detectorModels.data.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.display_name}
                    </option>
                  ))
                ) : (
                  <option value="">No project models registered</option>
                )}
              </select>
            </label>
            <label>
              Deployment confidence
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={deployConfidence}
                onChange={(event) => setDeployConfidence(event.target.value)}
              />
            </label>
            <label>
              Deployment device
              <select
                value={deployDevice}
                onChange={(event) => setDeployDevice(event.target.value)}
              >
                <option value="auto">Auto</option>
                <option value="cuda">CUDA</option>
                <option value="cpu">CPU</option>
              </select>
            </label>
            <p className="annotation-helper">
              Run a registered trained or imported project model such as best.pt
              on this image. Grounding DINO and other prompted, open-vocabulary
              tools remain separate assist workflows.
            </p>
            {!detectorModels.isPending && detectorModels.data?.length === 0 && (
              <p className="annotation-helper" role="status">
                No trained detector is registered for this project. Register a
                local detector in Model Hub to run image-wide class-aware
                inference. Use Predict objects in image for class-agnostic SAM
                proposals. SAM masks do not train a detector from your edits
                automatically.
              </p>
            )}
            {detectorModels.isError && (
              <p className="form-error" role="alert">
                Could not load registered detectors:{" "}
                {detectorModels.error.message}
              </p>
            )}
            <button
              type="button"
              disabled={
                !deployModelId ||
                deployModelMutation.isPending ||
                deployJobQuery.data?.status === "queued" ||
                deployJobQuery.data?.status === "running"
              }
              onClick={() => deployModelMutation.mutate(deployModelId)}
            >
              {deployModelMutation.isPending
                ? "Queueing model..."
                : "Run model on this image"}
            </button>
            {deployModelMutation.error && (
              <p className="form-error">{deployModelMutation.error.message}</p>
            )}
            {deployJobQuery.data && (
              <p className="annotation-helper">
                Model job {deployJobQuery.data.status}:{" "}
                {deployJobQuery.data.progress_current}/
                {deployJobQuery.data.progress_total} image
              </p>
            )}
            {deployJobQuery.data?.error_message && (
              <p className="form-error">{deployJobQuery.data.error_message}</p>
            )}
            <label>
              Review predictions at or below confidence (%)
              <input
                type="number"
                min="0"
                max="100"
                step="1"
                value={quickReviewConfidence}
                onChange={(event) =>
                  setQuickReviewConfidence(event.target.value)
                }
              />
            </label>
            <button
              type="button"
              className="secondary"
              disabled={
                quickReviewConfidence.trim() === "" ||
                !Number.isFinite(Number(quickReviewConfidence)) ||
                Number(quickReviewConfidence) < 0 ||
                Number(quickReviewConfidence) > 100
              }
              onClick={() => setQuickReviewOpen(true)}
            >
              Quick-review predictions in popout
            </button>
            <p className="annotation-helper">
              Only review model predictions at or below this percentage.
              Higher-confidence predictions are skipped, not automatically
              human-verified. Set deployment confidence low enough to retain
              detections that you want reviewed (for example 0.05).
            </p>
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Detector review</p>
                <h3>Prediction proposals</h3>
              </div>
              <span>{predictionCounts.pending ?? 0} pending</span>
            </div>
            <label>
              Model filter
              <select
                value={predictionModelFilter}
                onChange={(event) =>
                  setPredictionModelFilter(event.target.value)
                }
              >
                <option value="">All detector models</option>
                {detectorModels.data?.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Class filter
              <select
                value={predictionClassFilter}
                onChange={(event) =>
                  setPredictionClassFilter(event.target.value)
                }
              >
                <option value="">All mapped classes</option>
                {labelClasses.map((labelClass) => (
                  <option key={labelClass.id} value={labelClass.id}>
                    {labelClass.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Confidence threshold
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={predictionConfidenceFilter}
                onChange={(event) =>
                  setPredictionConfidenceFilter(event.target.value)
                }
              />
            </label>
            <label>
              Review status
              <select
                value={predictionStatusFilter}
                onChange={(event) =>
                  setPredictionStatusFilter(event.target.value)
                }
              >
                <option value="pending">Pending review</option>
                <option value="accepted">Accepted</option>
                <option value="edited_and_accepted">Edited and accepted</option>
                <option value="rejected">Rejected</option>
                <option value="">All states</option>
              </select>
            </label>
            <label>
              Sort predictions
              <select
                value={predictionSort}
                onChange={(event) => setPredictionSort(event.target.value)}
              >
                <option value="confidence-asc">Lowest confidence first</option>
                <option value="confidence-desc">
                  Highest confidence first
                </option>
                <option value="class">Class</option>
              </select>
            </label>
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className="secondary"
                disabled={
                  visiblePredictions.length === 0 ||
                  predictionStatusFilter !== "pending" ||
                  bulkReviewMutation.isPending
                }
                onClick={() => {
                  const count = visiblePredictions.length;
                  if (
                    window.confirm(
                      `Accept ${count} visible pending predictions? Class-agnostic masks use the currently selected class. Original model provenance will be preserved.`,
                    )
                  ) {
                    bulkReviewMutation.mutate({
                      action: "accept",
                      selected: false,
                    });
                  }
                }}
              >
                Accept visible
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  !selectedPredictionIds.length ||
                  predictionStatusFilter !== "pending" ||
                  bulkReviewMutation.isPending
                }
                onClick={() => {
                  if (
                    window.confirm(
                      `Accept ${selectedPredictionIds.length} selected pending predictions? Class-agnostic masks use the currently selected class.`,
                    )
                  )
                    bulkReviewMutation.mutate({
                      action: "accept",
                      selected: true,
                    });
                }}
              >
                Accept selected
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  visiblePredictions.length === 0 ||
                  predictionStatusFilter !== "pending" ||
                  bulkReviewMutation.isPending
                }
                onClick={() => {
                  const count = visiblePredictions.length;
                  if (
                    window.confirm(
                      `Reject ${count} pending predictions? The prediction records will be preserved.`,
                    )
                  ) {
                    bulkReviewMutation.mutate({
                      action: "reject",
                      selected: false,
                    });
                  }
                }}
              >
                Reject visible
              </button>
            </div>
            {acceptPredictionMutation.error && (
              <p className="form-error">
                {acceptPredictionMutation.error.message}
              </p>
            )}
            {rejectPredictionMutation.error && (
              <p className="form-error">
                {rejectPredictionMutation.error.message}
              </p>
            )}
            {bulkReviewMutation.error && (
              <p className="form-error">{bulkReviewMutation.error.message}</p>
            )}
            <div className="annotation-selection-list">
              {predictionQuery.isPending && <p>Loading predictions...</p>}
              {!predictionQuery.isPending &&
                visiblePredictions.length === 0 && (
                  <p>No pending proposals for the current filters.</p>
                )}
              {visiblePredictions.map((proposal) => {
                const labelClass =
                  (proposal.label_class_id
                    ? labelClassesById.get(proposal.label_class_id)
                    : null) ?? null;
                const selected = selectedPredictionIds.includes(proposal.id);
                return (
                  <div
                    key={proposal.id}
                    className="annotation-selection-row"
                    data-testid={`prediction-row-${proposal.id}`}
                    onClick={() => togglePredictionSelection(proposal.id)}
                  >
                    <strong>
                      {labelClass?.name ?? proposal.predicted_label} @{" "}
                      {proposal.confidence.toFixed(2)}
                    </strong>
                    <span>{proposal.model_display_name}</span>
                    <span>{proposal.review_status.replaceAll("_", " ")}</span>
                    {selected && <small>Selected for inspection</small>}
                  </div>
                );
              })}
            </div>
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Prompt Assist</p>
                <h3>Detect then segment</h3>
              </div>
              <span>{readyAssistModels.length} ready models</span>
            </div>
            <label>
              Assist model
              <select
                value={assistModelId}
                onChange={(event) => setAssistModelId(event.target.value)}
                disabled={readyAssistModels.length === 0}
              >
                {readyAssistModels.length ? (
                  readyAssistModels.map((model) => (
                    <option
                      key={model.catalog_id}
                      value={model.resolved_model_id}
                    >
                      {model.display_name}
                    </option>
                  ))
                ) : (
                  <option value="">No ready Smart Mask models</option>
                )}
              </select>
            </label>
            <p className="annotation-helper">
              Select one pending proposal, send its box to the selected Smart
              Mask model, review the candidate mask overlay, then accept it as a
              traced annotation. Imported custom assist checkpoints still come
              from the advanced Model Hub workflow.
            </p>
            {selectedAssistCatalogEntry && (
              <p className="annotation-helper">
                {selectedAssistCatalogEntry.installation_state} |{" "}
                {selectedAssistCatalogEntry.provider} |{" "}
                {selectedAssistCatalogEntry.model_weight_license}
              </p>
            )}
            {assistSourcePrediction ? (
              <div className="annotation-selection-list">
                <div className="annotation-selection-row">
                  <strong>Source proposal</strong>
                  <span>
                    {assistSourcePrediction.predicted_label} @{" "}
                    {assistSourcePrediction.confidence.toFixed(2)}
                  </span>
                </div>
                <div className="annotation-selection-row">
                  <strong>Accept as</strong>
                  <span>
                    {assistAcceptLabelClass?.name ?? "Choose a class"}
                  </span>
                </div>
              </div>
            ) : (
              <p>Select exactly one pending proposal to run Prompt Assist.</p>
            )}
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className="secondary"
                disabled={
                  !selectedPrediction ||
                  !assistModelId ||
                  promptAssistMutation.isPending
                }
                onClick={() => {
                  if (selectedPrediction) {
                    promptAssistMutation.mutate(selectedPrediction);
                  }
                }}
              >
                {promptAssistMutation.isPending
                  ? "Segmenting..."
                  : "Segment selected proposal"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={
                  !assistSession?.candidate_box ||
                  acceptAssistMutation.isPending
                }
                onClick={() => acceptAssistMutation.mutate()}
              >
                {acceptAssistMutation.isPending
                  ? "Accepting..."
                  : "Accept mask"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!assistSession || discardAssistMutation.isPending}
                onClick={() => discardAssistMutation.mutate()}
              >
                Discard mask
              </button>
            </div>
            {assistSession?.candidate_box && (
              <p className="annotation-helper">
                Candidate mask ready via {assistSession.provider_name} (
                {assistSession.prompt_type ?? "assist"}).
              </p>
            )}
            {assistModels.error && (
              <p className="form-error">{assistModels.error.message}</p>
            )}
            {promptAssistMutation.error && (
              <p className="form-error">{promptAssistMutation.error.message}</p>
            )}
            {acceptAssistMutation.error && (
              <p className="form-error">{acceptAssistMutation.error.message}</p>
            )}
            {discardAssistMutation.error && (
              <p className="form-error">
                {discardAssistMutation.error.message}
              </p>
            )}
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Classes</p>
                <h3>Annotation classes</h3>
              </div>
            </div>
            <label className="annotation-active-class-control">
              <span>Active annotation class</span>
              <select
                data-testid="active-annotation-class"
                value={activeClassId ?? ""}
                disabled={selectableLabelClasses.length === 0}
                onChange={(event) => applyClassToSelection(event.target.value)}
              >
                {selectableLabelClasses.length === 0 ? (
                  <option value="">No active classes available</option>
                ) : (
                  selectableLabelClasses.map((labelClass) => (
                    <option key={labelClass.id} value={labelClass.id}>
                      {labelClass.name}
                    </option>
                  ))
                )}
              </select>
            </label>
            {selectableLabelClasses.length === 0 && (
              <div className="editor-message error" role="alert">
                <p>
                  This project has no active annotation classes. Open Data &
                  annotation → Classes and create or reactivate a class before
                  drawing annotations.
                </p>
              </div>
            )}
            <div className="annotation-visibility-toolbar">
              <label>
                <span>Visibility scope layer</span>
                <select
                  data-testid="class-visibility-layer"
                  value={selectedVisibilityLayer}
                  onChange={(event) =>
                    setSelectedVisibilityLayer(
                      event.target.value as ClassVisibilityLayerType,
                    )
                  }
                >
                  {visibilityLayerOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <p className="annotation-helper">
                {currentVisibilityLayerOption.description}
              </p>
              <p
                className="annotation-helper annotation-visibility-status"
                data-testid="class-visibility-status"
              >
                {visibilityStatusMessage ??
                  `${visibilityLayerLabel(selectedVisibilityLayer)} currently uses ${visibilitySourceLabel(currentLayerVisibility.source)}.`}
              </p>
              {visibilityQuery.error && (
                <p className="form-error">
                  Saved visibility preferences could not be loaded. ReefVision
                  is using session-visible defaults until the request succeeds.
                </p>
              )}
              <p className="annotation-helper">
                My Preference:{" "}
                {currentLayerVisibility.userPreference.saved
                  ? "saved"
                  : "not saved"}
                . Project Default:{" "}
                {currentLayerVisibility.projectDefault.saved
                  ? "saved"
                  : "not saved"}
                .
              </p>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => updateSelectedLayerVisibility(() => [])}
                >
                  Show all
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    updateSelectedLayerVisibility(() => allClassIds)
                  }
                >
                  Hide all
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    updateSelectedLayerVisibility((currentHiddenClassIds) => {
                      const hidden = new Set(currentHiddenClassIds);
                      return allClassIds.filter(
                        (classId) => !hidden.has(classId),
                      );
                    })
                  }
                >
                  Invert
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={resetSessionVisibility}
                >
                  Reset Session
                </button>
              </div>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={visibilityMutation.isPending}
                  onClick={saveCurrentVisibilityAsMyPreference}
                >
                  Save as My Preference
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={visibilityMutation.isPending}
                  onClick={saveCurrentVisibilityAsProjectDefault}
                >
                  Save as Project Default
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={visibilityMutation.isPending}
                  onClick={resetMyVisibilityPreferences}
                >
                  Reset My Preferences
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={resetToProjectDefaults}
                >
                  Reset to Project Defaults
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={visibilityMutation.isPending}
                  onClick={copyCurrentVisibilityToProjectDefaults}
                >
                  Copy Current Visibility to Project Defaults
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={visibilityMutation.isPending}
                  onClick={applyProjectDefaultsToMyPreferences}
                >
                  Apply Project Defaults to My Preferences
                </button>
              </div>
            </div>
            <ul className="annotation-class-list">
              {currentLabelClasses.map((labelClass, index) => {
                const active = labelClass.id === activeClassId;
                const hidden = currentLayerHiddenClassSet.has(labelClass.id);
                return (
                  <li
                    key={labelClass.id}
                    className={`annotation-class-row ${active ? "selected" : ""} ${hidden ? "hidden" : ""}`}
                  >
                    <button
                      type="button"
                      className="annotation-class-button"
                      data-testid={`class-tool-${index + 1}`}
                      aria-pressed={active}
                      disabled={labelClass.is_active === false}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        applyClassToSelection(labelClass.id);
                      }}
                    >
                      <span
                        className="annotation-class-swatch"
                        style={{ backgroundColor: labelClass.display_color }}
                      />
                      <span className="annotation-class-text">
                        {index + 1}. {labelClass.name}
                      </span>
                      <span className="annotation-class-count">
                        {counts.get(labelClass.id) ?? 0}
                      </span>
                    </button>
                    <label className="annotation-class-visibility">
                      <input
                        type="checkbox"
                        checked={!hidden}
                        onChange={() =>
                          toggleCurrentLayerClassVisibility(labelClass.id)
                        }
                      />
                      Visible
                    </label>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        updateSelectedLayerVisibility(() =>
                          allClassIds.filter(
                            (classId) => classId !== labelClass.id,
                          ),
                        )
                      }
                    >
                      Solo
                    </button>
                  </li>
                );
              })}
            </ul>
            <p className="annotation-helper">
              Active class: {activeClass?.name ?? "None"}.
              {!activeClass
                ? " Drawing tools are disabled until an active class is available."
                : ""}
              {canReassignSelection
                ? " Selecting another class reassigns the current selection."
                : state.tool === "box"
                  ? " Draw new boxes with the active class without changing the current selection."
                  : " Select boxes to reassign them to another class."}
            </p>
            <p className="annotation-helper">
              Class visibility updates apply immediately, do not refetch
              annotations, and never rewrite annotation records, datasets,
              exports, or model class maps.
            </p>
            {selectedVisibilityLayer === "annotations" && hideAnnotations && (
              <p className="annotation-helper">
                Boxes are currently hidden globally. Saved class visibility has
                not changed.
              </p>
            )}
            {selectedVisibilityLayer === "predictions" && !showPredictions && (
              <p className="annotation-helper">
                Predictions are currently hidden globally. Saved class
                visibility has not changed.
              </p>
            )}
            {!currentVisibilityLayerOption.liveInEditor && (
              <p className="annotation-helper">
                This layer is stored now and will be applied when ReefVision
                opens the matching overlay or workspace.
              </p>
            )}
          </section>

          <section className="annotation-sidebar-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Selection</p>
                <h3>{selectedObjectCount} selected</h3>
              </div>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className="secondary"
                  title="Undo (Ctrl/Cmd+Z)"
                  aria-keyshortcuts="Control+Z Meta+Z"
                  disabled={!canUndo}
                  onClick={() => dispatch({ type: "undo" })}
                >
                  Undo
                </button>
                <button
                  type="button"
                  className="secondary"
                  title="Redo (Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y)"
                  aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z Control+Y Meta+Y"
                  disabled={!canRedo}
                  onClick={() => dispatch({ type: "redo" })}
                >
                  Redo
                </button>
                <button
                  type="button"
                  className="secondary"
                  title="Copy to ReefVision's internal clipboard (Ctrl/Cmd+C)"
                  aria-keyshortcuts="Control+C Meta+C"
                  disabled={selectedObjectCount === 0}
                  onClick={copySelection}
                >
                  Copy
                </button>
                <button
                  type="button"
                  className="secondary"
                  title="Duplicate selection (Ctrl/Cmd+D)"
                  aria-keyshortcuts="Control+D Meta+D"
                  disabled={selectedObjectCount === 0}
                  onClick={duplicateSelection}
                >
                  Duplicate
                </button>
                <button
                  type="button"
                  className="secondary"
                  title="Paste from ReefVision's internal clipboard (Ctrl/Cmd+V)"
                  aria-keyshortcuts="Control+V Meta+V"
                  disabled={!annotationClipboardRef.current?.items.length}
                  onClick={() => pasteClipboard()}
                >
                  Paste
                </button>
              </div>
            </div>
            <p className="annotation-helper">
              Wheel to zoom. Alt+left-drag, middle-drag, or the Pan tool moves
              the view. Ctrl/Cmd-click builds a mixed selection of boxes and
              masks. Polygon, Fill, Smart Close, and Brush masks remain visible
              in Select mode.
            </p>
            <button
              type="button"
              className="danger-ghost"
              title="Delete selection (Delete or Backspace)"
              aria-keyshortcuts="Delete Backspace"
              disabled={selectedObjectCount === 0}
              onClick={deleteSelection}
            >
              Delete selection
            </button>
            <label>
              Find objects
              <input
                value={objectFilter}
                placeholder="Filter by class"
                onChange={(event) => setObjectFilter(event.target.value)}
              />
            </label>
            <div
              className="annotation-selection-list object-list"
              role="listbox"
              aria-label="Objects"
            >
              {state.document.annotations.length === 0 &&
                state.document.maskAnnotations.length === 0 && (
                  <p>No annotations yet.</p>
                )}
              {state.document.annotations
                .filter((annotation) =>
                  (labelClassesById.get(annotation.label_class_id)?.name ?? "")
                    .toLowerCase()
                    .includes(objectFilter.toLowerCase()),
                )
                .map((annotation, index) => {
                  const labelClass = labelClassesById.get(
                    annotation.label_class_id,
                  );
                  const selected = state.selectedIds.includes(annotation.id);
                  return (
                    <button
                      key={annotation.id}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      className={`annotation-selection-row object-row ${selected ? "selected" : ""}`}
                      onClick={() => {
                        setMaskSelection([]);
                        setSelection([annotation.id]);
                      }}
                    >
                      <span className="object-index">{index + 1}</span>
                      <span
                        className="annotation-class-swatch"
                        style={{
                          backgroundColor:
                            labelClass?.display_color ?? "#72dbc9",
                        }}
                      />
                      <span>
                        <strong>{labelClass?.name ?? "Unknown class"}</strong>
                        <small>
                          Bounding box ·{" "}
                          {Math.round(annotation.x_max - annotation.x_min)} ×{" "}
                          {Math.round(annotation.y_max - annotation.y_min)} px
                        </small>
                      </span>
                    </button>
                  );
                })}
              {state.document.maskAnnotations
                .filter((mask) =>
                  (labelClassesById.get(mask.label_class_id ?? "")?.name ?? "")
                    .toLowerCase()
                    .includes(objectFilter.toLowerCase()),
                )
                .map((mask, index) => {
                  const labelClass = mask.label_class_id
                    ? labelClassesById.get(mask.label_class_id)
                    : null;
                  const selected = state.selectedMaskIds.includes(mask.id);
                  const kindLabel =
                    mask.geometry_kind === "raster_mask"
                      ? "Brush mask"
                      : "Polygon / Fill";
                  return (
                    <button
                      key={mask.id}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      className={`annotation-selection-row object-row ${selected ? "selected" : ""}`}
                      onClick={() => {
                        setSelection([]);
                        setMaskSelection([mask.id]);
                      }}
                    >
                      <span className="object-index">
                        {state.document.annotations.length + index + 1}
                      </span>
                      <span
                        className="annotation-class-swatch"
                        style={{
                          backgroundColor:
                            labelClass?.display_color ?? "#72dbc9",
                        }}
                      />
                      <span>
                        <strong>{labelClass?.name ?? "Unassigned"}</strong>
                        <small>
                          {kindLabel}
                          {mask.area_pixels !== null
                            ? ` · ${mask.area_pixels} px²`
                            : ""}
                        </small>
                      </span>
                    </button>
                  );
                })}
            </div>
            <div
              className="prediction-inspector-slot"
              data-testid="prediction-inspector-slot"
            >
              {selectedPrediction ? (
                <PredictionInspector
                  proposal={selectedPrediction}
                  imageWidth={imageSize.width}
                  imageHeight={imageSize.height}
                  classes={labelClasses}
                  reviewedClassId={
                    predictionClassOverrides[selectedPrediction.id] ??
                    selectedPrediction.label_class_id ??
                    activeClassId ??
                    ""
                  }
                  reviewedGeometry={
                    predictionGeometryOverrides[selectedPrediction.id] ?? {
                      x_min: selectedPrediction.x_min,
                      y_min: selectedPrediction.y_min,
                      x_max: selectedPrediction.x_max,
                      y_max: selectedPrediction.y_max,
                    }
                  }
                  position={selectedPredictionPosition + 1}
                  total={visiblePredictions.length}
                  busy={
                    acceptPredictionMutation.isPending ||
                    rejectPredictionMutation.isPending ||
                    promptAssistMutation.isPending
                  }
                  error={
                    (acceptPredictionMutation.error ??
                      rejectPredictionMutation.error ??
                      promptAssistMutation.error) as Error | null
                  }
                  onClassChange={(classId) =>
                    setPredictionClassOverrides((current) => ({
                      ...current,
                      [selectedPrediction.id]: classId,
                    }))
                  }
                  onGeometryChange={(geometry) =>
                    setPredictionGeometryOverrides((current) => ({
                      ...current,
                      [selectedPrediction.id]: geometry,
                    }))
                  }
                  onAccept={() =>
                    acceptPredictionMutation.mutate(selectedPrediction)
                  }
                  onReject={() =>
                    rejectPredictionMutation.mutate(selectedPrediction.id)
                  }
                  onPromptAssist={() =>
                    promptAssistMutation.mutate(selectedPrediction)
                  }
                  onPrevious={() =>
                    selectPredictionAt(selectedPredictionPosition - 1)
                  }
                  onNext={() =>
                    selectPredictionAt(selectedPredictionPosition + 1)
                  }
                  onLocate={() => {
                    const scale = resolvedView.scale;
                    const centerX =
                      (selectedPrediction.x_min + selectedPrediction.x_max) / 2;
                    const centerY =
                      (selectedPrediction.y_min + selectedPrediction.y_max) / 2;
                    setView({
                      scale,
                      offsetX: containerSize.width / 2 - centerX * scale,
                      offsetY: containerSize.height / 2 - centerY * scale,
                    });
                  }}
                />
              ) : (
                <>
                  <strong>Prediction Inspector</strong>
                  <span>
                    Select a model proposal to inspect its crop, confidence,
                    geometry, and provenance.
                  </span>
                </>
              )}
            </div>
          </section>
        </aside>

        <section className="annotation-canvas-panel">
          <div className="annotation-nav">
            <button
              type="button"
              className="secondary"
              disabled={!sessionQuery.data.previous_image_id}
              onClick={() =>
                void navigateToImage(sessionQuery.data.previous_image_id)
              }
            >
              Previous image (A)
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!sessionQuery.data.next_image_id}
              onClick={() =>
                void navigateToImage(sessionQuery.data.next_image_id)
              }
            >
              Next image (D)
            </button>
            <span>{dirty ? "Autosave pending" : "All changes synced"}</span>
            {shortcutMessage && <span role="status">{shortcutMessage}</span>}
            {samAssistMutation.error && (
              <span role="alert">{samAssistMutation.error.message}</span>
            )}
            {samInstallMutation.error && (
              <span role="alert">{samInstallMutation.error.message}</span>
            )}
            <label>
              SAM 2.1 model
              <select
                aria-label="SAM 2.1 model for editor shortcuts"
                value={samModelVariant}
                onChange={(event) => {
                  setSamModelVariant(event.target.value);
                  setSamPendingBox(null);
                  setSamInstallJobId(null);
                }}
              >
                <option value="tiny">Tiny</option>
                <option value="small">Small</option>
                <option value="base-plus">Base+</option>
                <option value="large">Large</option>
              </select>
            </label>
          </div>

          {deployJobQuery.data && (
            <section aria-label="Image prediction progress" role="status">
              <span>
                Image predictions: {deployJobQuery.data.status} ·{" "}
                {deployJobQuery.data.progress_current}/
                {deployJobQuery.data.progress_total}
              </span>
              {imagePredictionBusy && (
                <button
                  type="button"
                  disabled={cancelImageMutation.isPending}
                  onClick={() => cancelImageMutation.mutate()}
                >
                  Cancel image predictions
                </button>
              )}
              {deployJobQuery.data.error_message && (
                <p role="alert">{deployJobQuery.data.error_message}</p>
              )}
              {cancelImageMutation.error && (
                <p role="alert">{cancelImageMutation.error.message}</p>
              )}
            </section>
          )}
          {fullImageMutation.error && (
            <p role="alert">
              {fullImageMutation.error.message} Choose or download a SAM 2.1
              variant in Model Hub, then retry.
            </p>
          )}
          {refinement.busy && (
            <p role="status">
              Processing mask refinement… The original is unchanged until
              acceptance.
            </p>
          )}
          {fullImageLoading && (
            <p role="status" className="rv-media-load-status">
              Loading full-resolution image...
            </p>
          )}
          {fullImageFailed && (
            <div className="rv-media-load-error" role="alert">
              <strong>Full-resolution image could not load</strong>
              <p>
                {image.thumbnail_path
                  ? "A thumbnail preview is shown. Do not verify new annotations against this preview."
                  : "No thumbnail is available. The image cannot be reliably reviewed until the full-resolution file loads."}
              </p>
              <button
                type="button"
                className="secondary"
                onClick={() => setFullImageRetry((value) => value + 1)}
              >
                Retry full-resolution image
              </button>
            </div>
          )}
          <div className="annotation-canvas-frame" ref={viewportRef}>
            {learningOpen && (
              <ImprovePredictionsPanel
                projectId={project.id}
                onClose={() => setLearningOpen(false)}
              />
            )}
            {refinement.panel}
            {samReviewProposalId && (
              <section
                className="sam-review-banner"
                role="region"
                aria-label="SAM mask proposal review"
                data-testid="sam-proposal-review"
              >
                <strong>SAM mask is a proposal — not saved yet</strong>
                <p>
                  Review this outline before adding it to your annotations.
                  Existing masks are unchanged until you accept.
                </p>
                {samReviewProposal ? (
                  <>
                    <label>
                      Accept as class
                      <select
                        aria-label="Class for SAM mask"
                        value={
                          predictionClassOverrides[samReviewProposal.id] ??
                          samReviewProposal.label_class_id ??
                          activeClassId ??
                          ""
                        }
                        onChange={(event) =>
                          setPredictionClassOverrides((current) => ({
                            ...current,
                            [samReviewProposal.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">Choose a class</option>
                        {labelClasses
                          .filter(
                            (labelClass) => labelClass.is_active !== false,
                          )
                          .map((labelClass) => (
                            <option key={labelClass.id} value={labelClass.id}>
                              {labelClass.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="sam-review-toggle">
                      <input
                        type="checkbox"
                        checked={isolateSamReview}
                        onChange={(event) =>
                          setIsolateSamReview(event.target.checked)
                        }
                      />
                      Hide existing masks while reviewing
                    </label>
                    <div className="annotation-editor-inline-actions">
                      <button
                        type="button"
                        disabled={
                          acceptPredictionMutation.isPending ||
                          rejectPredictionMutation.isPending ||
                          !(
                            predictionClassOverrides[samReviewProposal.id] ||
                            samReviewProposal.label_class_id ||
                            activeClassId
                          )
                        }
                        onClick={() =>
                          acceptPredictionMutation.mutate(samReviewProposal)
                        }
                      >
                        Accept SAM mask
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        disabled={
                          acceptPredictionMutation.isPending ||
                          rejectPredictionMutation.isPending
                        }
                        onClick={() =>
                          rejectPredictionMutation.mutate(samReviewProposal.id)
                        }
                      >
                        Reject SAM mask
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setEditProposalId(samReviewProposal.id)}
                      >
                        Edit mask
                      </button>
                    </div>
                    {editProposalId === samReviewProposal.id && (
                      <PendingMaskEditor
                        imageId={currentImageId}
                        maskUrl={predictionMaskUrl(samReviewProposal.id)}
                        width={image.width_px}
                        height={image.height_px}
                        onCancel={() => setEditProposalId(null)}
                        onSave={async (png) => {
                          await intelligenceRequest(
                            `/prediction-proposals/${encodeURIComponent(samReviewProposal.id)}/mask`,
                            { mask_png_base64: png },
                            "PUT",
                          );
                          setEditProposalId(null);
                          await predictionQuery.refetch();
                        }}
                      />
                    )}
                    {acceptPredictionMutation.error && (
                      <p className="form-error" role="alert">
                        {acceptPredictionMutation.error.message}
                      </p>
                    )}
                    {rejectPredictionMutation.error && (
                      <p className="form-error" role="alert">
                        {rejectPredictionMutation.error.message}
                      </p>
                    )}
                  </>
                ) : (
                  <p role="status">Loading SAM mask proposal for review...</p>
                )}
              </section>
            )}
            {samPromptArmed && (
              <p className="annotation-helper" role="status">
                SAM prompt ready: drag a bounding box around the object. Use SAM
                box prompt to segment an existing selected box.
              </p>
            )}
            <svg
              ref={svgRef}
              className={`annotation-canvas tool-${state.tool}`}
              data-testid="annotation-canvas"
              onContextMenu={(event) => event.preventDefault()}
              onPointerDown={handleCanvasPointerDown}
              onWheel={handleCanvasWheel}
              viewBox={`0 0 ${containerSize.width || 1} ${containerSize.height || 1}`}
            >
              <g
                data-testid="viewport-transform"
                transform={`translate(${resolvedView.offsetX} ${resolvedView.offsetY}) scale(${resolvedView.scale})`}
              >
                <image
                  key={imageRenderKey}
                  href={imageHref}
                  x={0}
                  y={0}
                  width={image.width_px}
                  height={image.height_px}
                  preserveAspectRatio="none"
                />
                <rect
                  x={0}
                  y={0}
                  width={image.width_px}
                  height={image.height_px}
                  fill="transparent"
                />
                {state.tool === "select" &&
                  !(
                    samReviewProposal &&
                    isolateSamReview &&
                    !refinement.pending
                  ) &&
                  state.document.maskAnnotations.map((mask) => {
                    const labelClass = mask.label_class_id
                      ? labelClassesById.get(mask.label_class_id)
                      : null;
                    const color = labelClass?.display_color ?? "#72dbc9";
                    const selected = state.selectedMaskIds.includes(mask.id);

                    if (
                      mask.geometry_kind === "raster_mask" &&
                      mask.mask_path !== null
                    ) {
                      return (
                        <image
                          key={mask.id}
                          data-testid={`mask-annotation-${mask.id}`}
                          href={rasterMaskContentUrl(mask)}
                          x={0}
                          y={0}
                          width={image.width_px}
                          height={image.height_px}
                          opacity={selected ? 0.52 : 0.3}
                          preserveAspectRatio="none"
                          style={{ cursor: "pointer", mixBlendMode: "screen" }}
                          onPointerDown={(event) =>
                            handleMaskPointerDown(event, mask.id)
                          }
                        />
                      );
                    }

                    if (!mask.points || mask.points.length < 3) {
                      return null;
                    }
                    return (
                      <polygon
                        key={mask.id}
                        data-testid={`mask-annotation-${mask.id}`}
                        points={mask.points
                          .map((point) => `${point.x},${point.y}`)
                          .join(" ")}
                        fill={color}
                        fillOpacity={selected ? 0.28 : 0.14}
                        stroke={color}
                        strokeWidth={selected ? 2.5 : 1.5}
                        vectorEffect="non-scaling-stroke"
                        style={{ cursor: "pointer" }}
                        onPointerDown={(event) =>
                          handleMaskPointerDown(event, mask.id)
                        }
                      />
                    );
                  })}
                {refinement.overlay}
                {assistMaskHref && (
                  <image
                    href={assistMaskHref}
                    x={0}
                    y={0}
                    width={image.width_px}
                    height={image.height_px}
                    opacity={0.3}
                    preserveAspectRatio="none"
                  />
                )}
                {assistSession?.candidate_box && (
                  <rect
                    x={assistSession.candidate_box.x_min}
                    y={assistSession.candidate_box.y_min}
                    width={
                      assistSession.candidate_box.x_max -
                      assistSession.candidate_box.x_min
                    }
                    height={
                      assistSession.candidate_box.y_max -
                      assistSession.candidate_box.y_min
                    }
                    fill="rgba(87, 204, 153, 0.10)"
                    stroke="#57cc99"
                    strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                <defs>
                  <filter id="prediction-cyan">
                    <feColorMatrix
                      type="matrix"
                      values="0 0 0 0 0.2  0 0 0 0 0.9  0 0 0 0 1  1 0 0 0 0"
                    />
                  </filter>
                </defs>
                {showPredictions &&
                  visiblePredictions.map((proposal) => {
                    const labelClass =
                      (proposal.label_class_id
                        ? labelClassesById.get(proposal.label_class_id)
                        : null) ?? null;
                    const selected = selectedPredictionIds.includes(
                      proposal.id,
                    );
                    const highlighted = highlightedPredictionIds.has(
                      proposal.id,
                    );
                    return (
                      <g key={`prediction-${proposal.id}`}>
                        {proposal.geometry_kind === "raster_mask" && (
                          <image
                            href={`${predictionMaskUrl(proposal.id)}?sha=${proposal.mask_content_sha256 ?? ""}`}
                            filter="url(#prediction-cyan)"
                            x={0}
                            y={0}
                            width={image.width_px}
                            height={image.height_px}
                            opacity={selected ? 0.48 : 0.25}
                            preserveAspectRatio="none"
                            pointerEvents="none"
                            data-testid={`proposal-mask-${proposal.id}`}
                          />
                        )}
                        <rect
                          x={proposal.x_min}
                          y={proposal.y_min}
                          width={proposal.x_max - proposal.x_min}
                          height={proposal.y_max - proposal.y_min}
                          fill={
                            selected
                              ? "rgba(255, 196, 0, 0.14)"
                              : highlighted
                                ? "rgba(255, 196, 0, 0.16)"
                                : "rgba(255, 196, 0, 0.06)"
                          }
                          stroke={labelClass?.display_color ?? "#f5c542"}
                          strokeWidth={highlighted ? 2.5 : 1.5}
                          strokeDasharray={`${6 * strokeScale} ${4 * strokeScale}`}
                          vectorEffect="non-scaling-stroke"
                          onPointerDown={(event) => {
                            event.stopPropagation();
                            togglePredictionSelection(proposal.id);
                          }}
                        />
                        <text
                          x={proposal.x_min + 4 * strokeScale}
                          y={proposal.y_min + 14 * strokeScale}
                          fill={labelClass?.display_color ?? "#f5c542"}
                          fontSize={12 * strokeScale}
                        >
                          {`${labelClass?.name ?? proposal.predicted_label} ${proposal.confidence.toFixed(2)}`}
                        </text>
                      </g>
                    );
                  })}
                {!hideAnnotations &&
                  visibleAnnotations.map((annotation) => {
                    const labelClass = labelClassesById.get(
                      annotation.label_class_id,
                    );
                    const selected = state.selectedIds.includes(annotation.id);
                    const highlighted = highlightedAnnotationIds.has(
                      annotation.id,
                    );
                    return (
                      <g key={annotation.id}>
                        <rect
                          data-testid={`annotation-${annotation.id}`}
                          x={annotation.x_min}
                          y={annotation.y_min}
                          width={annotation.x_max - annotation.x_min}
                          height={annotation.y_max - annotation.y_min}
                          fill={
                            selected
                              ? "rgba(255,255,255,0.10)"
                              : highlighted
                                ? "rgba(114, 219, 201, 0.15)"
                                : "rgba(255,255,255,0.03)"
                          }
                          stroke={labelClass?.display_color ?? "#72dbc9"}
                          strokeWidth={highlighted ? 2.5 : 1.5}
                          vectorEffect="non-scaling-stroke"
                          onPointerDown={(event) =>
                            handleAnnotationPointerDown(event, annotation.id)
                          }
                        />
                        <text
                          x={annotation.x_min + 4 * strokeScale}
                          y={annotation.y_min + 14 * strokeScale}
                          fill={labelClass?.display_color ?? "#72dbc9"}
                          fontSize={12 * strokeScale}
                        >
                          {labelClass?.name ?? annotation.label_class_id}
                        </text>
                        {selected &&
                          (
                            [
                              {
                                handle: "nw",
                                x: annotation.x_min,
                                y: annotation.y_min,
                              },
                              {
                                handle: "ne",
                                x: annotation.x_max,
                                y: annotation.y_min,
                              },
                              {
                                handle: "sw",
                                x: annotation.x_min,
                                y: annotation.y_max,
                              },
                              {
                                handle: "se",
                                x: annotation.x_max,
                                y: annotation.y_max,
                              },
                            ] as const
                          ).map((corner) => (
                            <circle
                              key={`${annotation.id}-${corner.handle}`}
                              cx={corner.x}
                              cy={corner.y}
                              r={handleRadius}
                              fill="#ffffff"
                              stroke={labelClass?.display_color ?? "#72dbc9"}
                              strokeWidth={1.5}
                              vectorEffect="non-scaling-stroke"
                              onPointerDown={(event) =>
                                handleResizePointerDown(
                                  event,
                                  annotation,
                                  corner.handle,
                                )
                              }
                            />
                          ))}
                      </g>
                    );
                  })}
                {!hideAnnotations &&
                  draftBox &&
                  boxArea({
                    id: "draft",
                    label_class_id: "draft",
                    ...draftBox,
                  }) >= 1 && (
                    <rect
                      x={draftBox.x_min}
                      y={draftBox.y_min}
                      width={draftBox.x_max - draftBox.x_min}
                      height={draftBox.y_max - draftBox.y_min}
                      fill="rgba(114,219,201,0.12)"
                      stroke={activeClass?.display_color ?? "#72dbc9"}
                      strokeDasharray={`${6 * strokeScale} ${4 * strokeScale}`}
                      strokeWidth={1.5}
                      vectorEffect="non-scaling-stroke"
                    />
                  )}
              </g>
            </svg>
          </div>
        </section>
      </div>
      {quickReviewOpen && (
        <QuickConfidenceReviewDialog
          item={{
            image_id: currentImageId,
            project_id: project.id,
            review_queue_id: "",
            review_state: "pending",
          }}
          reviewBelowConfidence={Number(quickReviewConfidence) / 100}
          position={1}
          total={1}
          showRankedPosition={false}
          hasPreviousImage={Boolean(sessionQuery.data.previous_image_id)}
          hasNextImage={Boolean(sessionQuery.data.next_image_id)}
          onClose={() => setQuickReviewOpen(false)}
          onPreviousImage={() => {
            void navigateToImage(sessionQuery.data.previous_image_id);
          }}
          onNextImage={() => {
            void navigateToImage(sessionQuery.data.next_image_id);
          }}
          onReviewSaved={() => {
            void Promise.all([
              sessionQuery.refetch(),
              predictionQuery.refetch(),
            ]);
          }}
        />
      )}
    </div>
  );
}
