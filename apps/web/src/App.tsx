import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { version as applicationVersion } from "../package.json";

import {
  archiveProject,
  createProject,
  getHealth,
  getProject,
  getProjectSummaries,
  type Project,
  type ProjectSummary,
  type QualityControlIssue,
  type ReviewQueueItem,
} from "./api/client";
import { ActiveLearningWorkspace } from "./features/active-learning/ActiveLearningWorkspace";
import { AdvancedProviderWorkspace } from "./features/advanced-providers/AdvancedProviderWorkspace";
import { ReefVisionAssistant } from "./features/assistant/ReefVisionAssistant";
import { EnhancedAnnotationEditor } from "./features/annotation-editor/EnhancedAnnotationEditor";
import { ClassManagerPanel } from "./features/classes/ClassManagerPanel";
import { ClassificationWorkspace } from "./features/classification/ClassificationWorkspace";
import { ComputedMetricsPanel } from "./features/computed-metrics/ComputedMetricsPanel";
import { DatasetVersionsPanel } from "./features/dataset-versions/DatasetVersionsPanel";
import { EnvironmentalContextPanel } from "./features/environmental-context/EnvironmentalContextPanel";
import { Gallery } from "./features/gallery/Gallery";
import { ScientificHeatmapsPanel } from "./features/scientific-heatmaps/ScientificHeatmapsPanel";
import { InteroperabilityWorkspace } from "./features/interoperability/InteroperabilityWorkspace";
import { ModelManager } from "./features/models/ModelManager";
import { OnboardingModal } from "./features/onboarding/OnboardingModal";
import { QualityControlDashboard } from "./features/quality-control/QualityControlDashboard";
import { ReviewQueueDashboard } from "./features/review-queues/ReviewQueueDashboard";
import { SystemPanel } from "./features/system/SystemPanel";
import { TrainingWorkspace } from "./features/training/TrainingWorkspace";
import { VideoTrackExchangePanel } from "./features/video/VideoTrackExchangePanel";
import { VideoTrackingWorkspace } from "./features/video/VideoTrackingWorkspace";
import type {
  VideoWorkspaceCommand,
  VideoWorkspaceContext,
} from "./features/video/videoWorkspaceBridge";
import { WorkflowGraphWorkspace } from "./features/workflow-graphs/WorkflowGraphWorkspace";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "./components/ui/AsyncState";
import { StatusBadge } from "./components/ui/StatusBadge";
import { KeyboardShortcutsDialog } from "./components/ui/KeyboardShortcutsDialog";
import { ProjectLauncher } from "./components/layout/ProjectLauncher";
import { ProjectImportDialog } from "./components/layout/ProjectImportDialog";
import { ScientistWorkspaceInspector } from "./components/layout/ScientistWorkspaceInspector";
import { ProjectWorkbenchShell } from "./components/layout/ProjectWorkbenchShell";
import { DetachedInspectorWindow } from "./components/layout/DetachedInspectorWindow";
import {
  detachedPanelChannelName,
  isDetachedInspectorMessage,
  parseDetachedPanelRequest,
  type DetachedInspectorMessage,
  type DetachedInspectorSnapshot,
} from "./components/layout/detachedPanelBridge";
import {
  workspacePreset,
  type WorkspacePresetId,
} from "./components/layout/workspacePresets";
import "./styles/design-system.css";
import "./styles/app.css";
import "./styles/phase12-workspace.css";

interface AnnotationLaunchState {
  imageId: string;
  returnLabel: string;
  contextTitle?: string;
  contextDescription?: string;
  highlightAnnotationIds?: string[];
  highlightPredictionIds?: string[];
  initialWorkspace?: "boxes" | "masks" | "raster";
}

type ProjectView =
  | "gallery"
  | "versions"
  | "interoperability"
  | "environmental_context"
  | "computed_metrics"
  | "scientific_heatmaps"
  | "models"
  | "training"
  | "classification"
  | "video"
  | "active_learning"
  | "classes"
  | "quality_control"
  | "review_queue"
  | "advanced_providers"
  | "workflows"
  | "system";

const ONBOARDING_DISMISS_KEY = "reefvision.onboarding.dismissed.1.0.3";

type ProjectTab = Exclude<ProjectView, "system">;

const PROJECT_NAV_GROUPS: Array<{
  id: string;
  label: string;
  description: string;
  items: Array<{ id: ProjectTab; label: string; description: string }>;
}> = [
  {
    id: "data",
    label: "Data & annotation",
    description:
      "Import, annotate, organize classes, and freeze reproducible datasets.",
    items: [
      {
        id: "gallery",
        label: "Images & annotation",
        description:
          "Browse imagery, run inference, and open the annotation editor.",
      },
      {
        id: "versions",
        label: "Dataset versions",
        description:
          "Create immutable snapshots, splits, comparisons, and exports.",
      },
      {
        id: "interoperability",
        label: "Interoperability",
        description:
          "Export, inspect, and import versioned ReefVision project packages.",
      },
      {
        id: "classes",
        label: "Classes",
        description:
          "Manage project labels, display colors, order, and activity.",
      },
      {
        id: "environmental_context",
        label: "Environmental Context",
        description:
          "Import sensor and NOAA observations with units, quality flags, and provenance.",
      },
      {
        id: "computed_metrics",
        label: "Computed Metrics",
        description:
          "Define unit-aware formulas and calculate immutable results from scientific records.",
      },
      {
        id: "scientific_heatmaps",
        label: "Scientific Heatmaps",
        description:
          "Explore reviewed objects, verified masks, and predictions in independent spatial layers.",
      },
    ],
  },
  {
    id: "models",
    label: "Models & AI",
    description: "Train, run, register, and inspect computer-vision providers.",
    items: [
      {
        id: "models",
        label: "Model Hub",
        description:
          "Train from architectures and register local trained models.",
      },
      {
        id: "training",
        label: "Training",
        description: "Launch and inspect reproducible model-training runs.",
      },
      {
        id: "classification",
        label: "Classification",
        description: "Train and run image-level classification workflows.",
      },
      {
        id: "active_learning",
        label: "Active learning",
        description: "Prioritize informative samples for human annotation.",
      },
      {
        id: "advanced_providers",
        label: "Advanced providers",
        description:
          "Use prompt, segmentation, depth, OCR, and VLM provider tools.",
      },
    ],
  },
  {
    id: "review",
    label: "Review",
    description:
      "Find annotation issues and direct review time where it matters.",
    items: [
      {
        id: "quality_control",
        label: "Quality control",
        description: "Run explainable project or dataset-version QC checks.",
      },
      {
        id: "review_queue",
        label: "Review queue",
        description:
          "Work through ranked human-review items and model proposals.",
      },
    ],
  },
  {
    id: "automation",
    label: "Video & automation",
    description:
      "Analyze temporal data and compose reusable scientific workflows.",
    items: [
      {
        id: "video",
        label: "Video & tracking",
        description:
          "Track organisms, inspect activity and occupancy, and exchange tracks.",
      },
      {
        id: "workflows",
        label: "Workflow builder",
        description:
          "Visually connect typed analysis nodes, validate, save, and run.",
      },
    ],
  },
];

function ReefVisionMainApp() {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  );
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [editorLaunch, setEditorLaunch] =
    useState<AnnotationLaunchState | null>(null);
  const [trainingCatalogModelId, setTrainingCatalogModelId] = useState<
    string | null
  >(null);
  const [poseArchitecture, setPoseArchitecture] = useState<string | null>(null);
  const [classificationArchitecture, setClassificationArchitecture] = useState<
    string | null
  >(null);
  const [activeView, setActiveView] = useState<ProjectView>("gallery");
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showKeyboardShortcuts, setShowKeyboardShortcuts] = useState(false);
  const keyboardShortcutsButtonRef = useRef<HTMLButtonElement | null>(null);
  const [workspacePresetId, setWorkspacePresetId] =
    useState<WorkspacePresetId>("annotation");
  const [inferenceSelectedImageIds, setInferenceSelectedImageIds] = useState<
    string[]
  >([]);
  const [focusedGalleryImageId, setFocusedGalleryImageId] = useState<
    string | null
  >(null);
  const [selectedReviewQueueId, setSelectedReviewQueueId] = useState<
    string | null
  >(null);
  const [videoWorkspaceContext, setVideoWorkspaceContext] =
    useState<VideoWorkspaceContext | null>(null);
  const [videoWorkspaceCommand, setVideoWorkspaceCommand] =
    useState<VideoWorkspaceCommand | null>(null);
  const videoWorkspaceCommandSequenceRef = useRef(0);
  const detachedInspectorSnapshotRef = useRef<DetachedInspectorSnapshot | null>(
    null,
  );

  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
  });
  const projectSummaries = useQuery({
    queryKey: ["project_summaries"],
    queryFn: ({ signal }) => getProjectSummaries(signal),
  });
  const selectedProjectQuery = useQuery({
    queryKey: ["project", selectedProjectId],
    queryFn: ({ signal }) => getProject(selectedProjectId as string, signal),
    enabled: selectedProjectId !== null,
  });
  const createMutation = useMutation({
    mutationFn: () =>
      createProject({ name: projectName, description, template: "blank" }),
    onSuccess: async (created) => {
      setShowCreate(false);
      setProjectName("");
      setDescription("");
      setSelectedProjectId(created.id);
      setEditorLaunch(null);
      setActiveView("gallery");
      queryClient.setQueryData(["project", created.id], created);
      await queryClient.invalidateQueries({ queryKey: ["project_summaries"] });
    },
  });
  const archiveMutation = useMutation({
    mutationFn: (projectId: string) => archiveProject(projectId),
    onSuccess: async () => {
      setSelectedProjectId(null);
      setEditorLaunch(null);
      await queryClient.invalidateQueries({ queryKey: ["project_summaries"] });
    },
  });

  const selectedProjectSummary = useMemo(
    () =>
      projectSummaries.data?.find(
        (project) => project.id === selectedProjectId,
      ) ?? null,
    [projectSummaries.data, selectedProjectId],
  );
  const selectedProject = selectedProjectQuery.data ?? null;

  useEffect(() => {
    if (window.localStorage.getItem(ONBOARDING_DISMISS_KEY) !== "true") {
      setShowOnboarding(true);
    }
  }, []);

  useEffect(() => {
    setInferenceSelectedImageIds([]);
    setFocusedGalleryImageId(null);
    setSelectedReviewQueueId(null);
    setVideoWorkspaceContext(null);
    setVideoWorkspaceCommand(null);

    if (!selectedProjectId) {
      setWorkspacePresetId("annotation");
      return;
    }
    const saved = window.localStorage.getItem(
      `reefvision.ui.workspace-preset.${selectedProjectId}.v1`,
    );
    setWorkspacePresetId(
      workspacePreset((saved ?? "annotation") as WorkspacePresetId).id,
    );
  }, [selectedProjectId]);

  const handleInferenceSelectionChange = useCallback((imageIds: string[]) => {
    setInferenceSelectedImageIds(imageIds);
  }, []);

  const handleFocusedGalleryImageChange = useCallback(
    (imageId: string | null) => {
      setFocusedGalleryImageId(imageId);
    },
    [],
  );

  const handleSelectedReviewQueueChange = useCallback(
    (queueId: string | null) => {
      setSelectedReviewQueueId(queueId);
    },
    [],
  );

  const handleOpenReviewItem = useCallback((item: ReviewQueueItem) => {
    setEditorLaunch({
      imageId: item.image_id,
      returnLabel: "Back to Review Queue",
      contextTitle: `Review score ${item.score.toFixed(2)}`,
      contextDescription:
        item.reason_summary ?? "This image was ranked for human review.",
    });
  }, []);

  const handleVideoWorkspaceContextChange = useCallback(
    (context: VideoWorkspaceContext | null) => {
      setVideoWorkspaceContext(context);
    },
    [],
  );

  const handleVideoSelect = useCallback((videoId: string) => {
    videoWorkspaceCommandSequenceRef.current += 1;
    setVideoWorkspaceCommand({
      id: videoWorkspaceCommandSequenceRef.current,
      type: "select_video",
      videoId,
    });
  }, []);

  const handleVideoFrameChange = useCallback((frameIndex: number) => {
    videoWorkspaceCommandSequenceRef.current += 1;
    setVideoWorkspaceCommand({
      id: videoWorkspaceCommandSequenceRef.current,
      type: "seek_frame",
      frameIndex,
    });
  }, []);

  const handleVideoTrackChange = useCallback((trackId: string) => {
    videoWorkspaceCommandSequenceRef.current += 1;
    setVideoWorkspaceCommand({
      id: videoWorkspaceCommandSequenceRef.current,
      type: "select_track",
      trackId,
    });
  }, []);

  const handleVideoWorkspaceCommandHandled = useCallback(
    (commandId: number) => {
      setVideoWorkspaceCommand((current) =>
        current?.id === commandId ? null : current,
      );
    },
    [],
  );

  function selectWorkspacePreset(presetId: WorkspacePresetId): void {
    const preset = workspacePreset(presetId);
    setWorkspacePresetId(preset.id);
    if (selectedProjectId) {
      window.localStorage.setItem(
        `reefvision.ui.workspace-preset.${selectedProjectId}.v1`,
        preset.id,
      );
    }
    if (preset.id !== "custom") {
      setActiveView(preset.defaultView);
    }
  }

  function submitProject(event: FormEvent) {
    event.preventDefault();
    createMutation.mutate();
  }

  function dismissOnboardingPermanently() {
    window.localStorage.setItem(ONBOARDING_DISMISS_KEY, "true");
    setShowOnboarding(false);
  }

  function handleTabKeys<T extends string>(
    event: KeyboardEvent<HTMLButtonElement>,
    values: readonly T[],
    current: T,
    select: (value: T) => void,
  ) {
    const keyOffset =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    let targetIndex = values.indexOf(current);
    if (event.key === "Home") targetIndex = 0;
    else if (event.key === "End") targetIndex = values.length - 1;
    else if (keyOffset)
      targetIndex = (targetIndex + keyOffset + values.length) % values.length;
    else return;
    event.preventDefault();
    select(values[targetIndex]);
    const tablist = event.currentTarget.closest('[role="tablist"]');
    requestAnimationFrame(() => {
      tablist?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus();
    });
  }

  const activeProjectGroup = PROJECT_NAV_GROUPS.find((group) =>
    group.items.some((item) => item.id === activeView),
  );
  const activeProjectItem = activeProjectGroup?.items.find(
    (item) => item.id === activeView,
  );

  const detachedInspectorSnapshot =
    useMemo<DetachedInspectorSnapshot | null>(() => {
      if (!selectedProject || activeView === "system") {
        return null;
      }

      return {
        projectId: selectedProject.id,
        projectName: selectedProject.name,
        contextTitle: activeProjectItem?.label ?? "Project workspace",
        contextDescription:
          activeProjectItem?.description ??
          "Work with project data, models, review, and reproducible outputs.",
        activeView,
        activePreset: workspacePresetId,
        activeClassCount: selectedProject.label_classes.filter(
          (item) => item.is_active,
        ).length,
        annotationType: selectedProject.default_annotation_type,
        inferenceSelectedImageIds,
        focusedImageId: focusedGalleryImageId,
        selectedReviewQueueId,
        videoWorkspaceContext,
      };
    }, [
      activeProjectItem,
      activeView,
      focusedGalleryImageId,
      inferenceSelectedImageIds,
      selectedProject,
      selectedReviewQueueId,
      videoWorkspaceContext,
      workspacePresetId,
    ]);

  useEffect(() => {
    detachedInspectorSnapshotRef.current = detachedInspectorSnapshot;

    if (!detachedInspectorSnapshot || typeof BroadcastChannel === "undefined") {
      return;
    }

    const channel = new BroadcastChannel(
      detachedPanelChannelName(detachedInspectorSnapshot.projectId),
    );

    const message: DetachedInspectorMessage = {
      kind: "snapshot",
      projectId: detachedInspectorSnapshot.projectId,
      snapshot: detachedInspectorSnapshot,
    };

    channel.postMessage(message);
    channel.close();
  }, [detachedInspectorSnapshot]);

  useEffect(() => {
    if (!selectedProject || typeof BroadcastChannel === "undefined") {
      return;
    }

    const projectId = selectedProject.id;
    const channel = new BroadcastChannel(detachedPanelChannelName(projectId));

    const receive = (event: MessageEvent<unknown>) => {
      if (!isDetachedInspectorMessage(event.data)) {
        return;
      }

      if (event.data.projectId !== projectId) {
        return;
      }

      if (event.data.kind === "ready") {
        const snapshot = detachedInspectorSnapshotRef.current;

        if (snapshot && snapshot.projectId === projectId) {
          const response: DetachedInspectorMessage = {
            kind: "snapshot",
            projectId,
            snapshot,
          };

          channel.postMessage(response);
        }

        return;
      }

      if (event.data.kind !== "command") {
        return;
      }

      const command = event.data.command;

      switch (command.type) {
        case "navigate":
          setEditorLaunch(null);
          setActiveView(command.view);
          break;

        case "open_measurements":
          setEditorLaunch({
            imageId: command.imageId,
            returnLabel: "Back to morphometrics",
            contextTitle: "Morphometrics & scale calibration",
            contextDescription:
              "Review masks, calibration, measurements, and skeleton-derived morphology.",
            initialWorkspace: "masks",
          });
          break;

        case "open_review_item":
          handleOpenReviewItem(command.item);
          break;

        case "video_select":
          handleVideoSelect(command.videoId);
          break;

        case "video_frame":
          handleVideoFrameChange(command.frameIndex);
          break;

        case "video_track":
          handleVideoTrackChange(command.trackId);
          break;

        case "dock":
          // ProjectWorkbenchShell owns local layout
          // state and handles this same channel event.
          break;
      }
    };

    channel.addEventListener("message", receive);

    return () => {
      channel.removeEventListener("message", receive);
      channel.close();
    };
  }, [
    handleOpenReviewItem,
    handleVideoFrameChange,
    handleVideoSelect,
    handleVideoTrackChange,
    selectedProject,
  ]);

  return (
    <main className="app-shell">
      <a className="rv-skip-link" href="#reefvision-main-content">
        Skip to main content
      </a>
      <header className="rv-global-bar">
        <div className="rv-global-brand">
          <span className="rv-brand-mark" aria-hidden="true">
            RV
          </span>
          <div>
            <p className="eyebrow">Marine computer vision</p>
            <h1>ReefVision</h1>
          </div>
        </div>

        <div className="rv-global-context" aria-live="polite">
          <span>{selectedProject ? "Project" : "Home"}</span>
          <strong>{selectedProject?.name ?? "Scientist workspace"}</strong>
        </div>

        <div className="rv-global-actions">
          {(selectedProjectId || activeView === "system") && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setSelectedProjectId(null);
                setEditorLaunch(null);
                setActiveView("gallery");
              }}
            >
              Home
            </button>
          )}
          <button
            type="button"
            className="secondary"
            onClick={() => setShowOnboarding(true)}
          >
            Help
          </button>
          <button
            ref={keyboardShortcutsButtonRef}
            type="button"
            className="secondary"
            onClick={() => setShowKeyboardShortcuts(true)}
          >
            Keyboard shortcuts
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setSelectedProjectId(null);
              setEditorLaunch(null);
              setActiveView("system");
            }}
          >
            System status
          </button>
          <div className="api-status" aria-live="polite">
            <StatusBadge
              status={
                health.isPending
                  ? "pending"
                  : health.isError
                    ? "unavailable"
                    : "ready"
              }
              label={
                health.isPending
                  ? "Connecting"
                  : health.isError
                    ? "Service unavailable"
                    : `Local service ${health.data?.version}`
              }
            />
          </div>
        </div>
      </header>

      <section
        id="reefvision-main-content"
        className="rv-phase12-surface"
        tabIndex={-1}
      >
        {!selectedProjectId && activeView !== "system" && (
          <ProjectLauncher
            projects={projectSummaries.data ?? []}
            version={health.data?.version ?? applicationVersion}
            serviceState={
              health.isPending
                ? "pending"
                : health.isError
                  ? "unavailable"
                  : "ready"
            }
            onCreateProject={() => setShowCreate(true)}
            onQuickStart={() => {
              setShowCreate(true);
            }}
            onOpenProject={(projectId) => {
              setSelectedProjectId(projectId);
              setEditorLaunch(null);
              setActiveView("gallery");
            }}
            onImportPackage={() => {
              setShowImport(true);
            }}
            onOpenSystem={() => {
              setSelectedProjectId(null);
              setEditorLaunch(null);
              setActiveView("system");
            }}
            onOpenOnboarding={() => setShowOnboarding(true)}
          />
        )}

        {activeView === "system" && (
          <div className="rv-system-surface">
            <SystemPanel onOpenOnboarding={() => setShowOnboarding(true)} />
          </div>
        )}

        {selectedProjectId &&
          activeView !== "system" &&
          !selectedProject &&
          selectedProjectQuery.isPending && (
            <div className="rv-system-surface">
              <LoadingState
                title={`Opening ${selectedProjectSummary?.name ?? "project"}`}
                description="Loading classes, settings, and workspace details."
              />
            </div>
          )}

        {selectedProjectId &&
          activeView !== "system" &&
          selectedProjectQuery.error && (
            <div className="rv-system-surface">
              <ErrorState
                title="The requested project could not be loaded"
                message={`${selectedProjectSummary?.name ?? "This project"} is currently unavailable.`}
                error={selectedProjectQuery.error}
                onRetry={() => void selectedProjectQuery.refetch()}
                onBack={() => {
                  setSelectedProjectId(null);
                  setActiveView("gallery");
                }}
              />
            </div>
          )}

        {selectedProject && activeView !== "system" && (
          <ProjectWorkbenchShell
            project={selectedProject}
            contextTitle={activeProjectItem?.label ?? "Project workspace"}
            contextDescription={
              activeProjectItem?.description ??
              "Work with project data, models, review, and reproducible outputs."
            }
            activePreset={workspacePresetId}
            onPresetChange={selectWorkspacePreset}
            onHome={() => {
              setSelectedProjectId(null);
              setEditorLaunch(null);
              setActiveView("gallery");
            }}
            onSystem={() => {
              setSelectedProjectId(null);
              setEditorLaunch(null);
              setActiveView("system");
            }}
            onArchive={() => {
              if (window.confirm(`Archive ${selectedProject.name}?`)) {
                archiveMutation.mutate(selectedProject.id);
              }
            }}
            inspector={
              <ScientistWorkspaceInspector
                activeView={activeView as Exclude<ProjectView, "system">}
                activePreset={workspacePresetId}
                activeClassCount={
                  selectedProject.label_classes.filter((item) => item.is_active)
                    .length
                }
                annotationType={selectedProject.default_annotation_type}
                projectId={selectedProject.id}
                inferenceSelectedImageIds={inferenceSelectedImageIds}
                focusedImageId={focusedGalleryImageId}
                selectedReviewQueueId={selectedReviewQueueId}
                videoWorkspaceContext={videoWorkspaceContext}
                onOpenReviewItem={handleOpenReviewItem}
                onVideoSelect={handleVideoSelect}
                onVideoFrameChange={handleVideoFrameChange}
                onVideoTrackChange={handleVideoTrackChange}
                onOpenMeasurements={(imageId) =>
                  setEditorLaunch({
                    imageId,
                    returnLabel: "Back to morphometrics",
                    contextTitle: "Morphometrics & scale calibration",
                    contextDescription:
                      "Review masks, calibration, measurements, and skeleton-derived morphology.",
                    initialWorkspace: "masks",
                  })
                }
                onNavigate={(view) => {
                  setEditorLaunch(null);
                  setActiveView(view);
                }}
              />
            }
            navigation={
              <nav
                className="rv-project-nav"
                aria-label="Project workspace navigation"
              >
                {PROJECT_NAV_GROUPS.map((group) => {
                  const selected = group.id === activeProjectGroup?.id;
                  return (
                    <section className="rv-project-nav-group" key={group.id}>
                      <button
                        type="button"
                        role="tab"
                        aria-label={group.label}
                        aria-selected={selected}
                        tabIndex={selected ? 0 : -1}
                        className={selected ? "active" : ""}
                        title={group.description}
                        onClick={() => setActiveView(group.items[0].id)}
                        onKeyDown={(event) =>
                          handleTabKeys(
                            event,
                            PROJECT_NAV_GROUPS.map((value) => value.id),
                            activeProjectGroup?.id ?? PROJECT_NAV_GROUPS[0].id,
                            (groupId) => {
                              const next = PROJECT_NAV_GROUPS.find(
                                (value) => value.id === groupId,
                              );
                              if (next) setActiveView(next.items[0].id);
                            },
                          )
                        }
                      >
                        <strong>{group.label}</strong>
                        <span aria-hidden="true">{selected ? "—" : "+"}</span>
                      </button>

                      {selected && (
                        <div
                          className="rv-project-nav-items"
                          role="tablist"
                          aria-label={group.label}
                        >
                          {group.items.map((item) => (
                            <button
                              key={item.id}
                              type="button"
                              role="tab"
                              aria-selected={activeView === item.id}
                              tabIndex={activeView === item.id ? 0 : -1}
                              className={activeView === item.id ? "active" : ""}
                              title={item.description}
                              onClick={() => setActiveView(item.id)}
                              onKeyDown={(event) =>
                                handleTabKeys(
                                  event,
                                  group.items.map((value) => value.id),
                                  activeView as ProjectTab,
                                  setActiveView,
                                )
                              }
                            >
                              {item.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </section>
                  );
                })}
              </nav>
            }
          >
            {activeView === "gallery" && (
              <Gallery
                key={selectedProject.id}
                project={selectedProject}
                onInferenceSelectionChange={handleInferenceSelectionChange}
                onFocusedImageChange={handleFocusedGalleryImageChange}
                onOpenAnnotation={(imageId) =>
                  setEditorLaunch({
                    imageId,
                    returnLabel: "Back to gallery",
                  })
                }
              />
            )}
            {activeView === "versions" && (
              <DatasetVersionsPanel project={selectedProject} />
            )}
            {activeView === "interoperability" && (
              <InteroperabilityWorkspace project={selectedProject} />
            )}
            {activeView === "environmental_context" && (
              <EnvironmentalContextPanel
                key={selectedProject.id}
                project={selectedProject}
              />
            )}
            {activeView === "computed_metrics" && (
              <ComputedMetricsPanel
                key={selectedProject.id}
                project={selectedProject}
              />
            )}
            {activeView === "scientific_heatmaps" && (
              <ScientificHeatmapsPanel
                key={selectedProject.id}
                project={selectedProject}
              />
            )}
            {activeView === "classification" && (
              <ClassificationWorkspace
                project={selectedProject}
                initialArchitecture={classificationArchitecture}
              />
            )}
            {activeView === "advanced_providers" && (
              <AdvancedProviderWorkspace project={selectedProject} />
            )}
            {activeView === "workflows" && (
              <WorkflowGraphWorkspace
                project={selectedProject}
                initialPoseArchitecture={poseArchitecture}
              />
            )}
            {activeView === "video" && (
              <>
                <VideoTrackingWorkspace
                  project={selectedProject}
                  onWorkspaceContextChange={handleVideoWorkspaceContextChange}
                  workspaceCommand={videoWorkspaceCommand}
                  onWorkspaceCommandHandled={handleVideoWorkspaceCommandHandled}
                />
                <VideoTrackExchangePanel project={selectedProject} />
              </>
            )}
            {activeView === "active_learning" && (
              <ActiveLearningWorkspace
                project={selectedProject}
                onOpenReviewQueue={() => setActiveView("review_queue")}
              />
            )}
            {activeView === "models" && (
              <ModelManager
                project={selectedProject}
                onTrainPoseArchitecture={(architecture) => {
                  setPoseArchitecture(architecture);
                  setActiveView("workflows");
                }}
                onTrainClassificationArchitecture={(architecture) => {
                  setClassificationArchitecture(architecture);
                  setActiveView("classification");
                }}
                onSelectCatalogModel={(catalogId) => {
                  setTrainingCatalogModelId(catalogId);
                  setActiveView("training");
                }}
              />
            )}
            {activeView === "training" && (
              <TrainingWorkspace
                project={selectedProject}
                initialCatalogModelId={trainingCatalogModelId}
                onCatalogSelectionConsumed={() =>
                  setTrainingCatalogModelId(null)
                }
              />
            )}
            {activeView === "quality_control" && (
              <QualityControlDashboard
                project={selectedProject}
                onOpenImage={(issue: QualityControlIssue) =>
                  setEditorLaunch({
                    imageId: issue.image_id as string,
                    returnLabel: "Back to Quality Control",
                    contextTitle: issue.title,
                    contextDescription: issue.explanation,
                    highlightAnnotationIds: issue.annotation_ids_json,
                    highlightPredictionIds: issue.prediction_ids_json,
                  })
                }
              />
            )}
            {activeView === "review_queue" && (
              <ReviewQueueDashboard
                project={selectedProject}
                onOpenImage={handleOpenReviewItem}
                onSelectedQueueChange={handleSelectedReviewQueueChange}
              />
            )}
            {activeView === "classes" && (
              <ClassManagerPanel project={selectedProject} />
            )}
          </ProjectWorkbenchShell>
        )}
      </section>

      {selectedProject && !editorLaunch && (
        <ReefVisionAssistant
          project={selectedProject}
          activeView={activeView}
          onNavigate={(view) => setActiveView(view as ProjectView)}
        />
      )}
      {showCreate && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-project-title"
          >
            <div className="section-heading">
              <h2 id="new-project-title">Create project</h2>
              <button
                type="button"
                className="icon-button"
                aria-label="Close create-project dialog"
                onClick={() => setShowCreate(false)}
              >
                Close
              </button>
            </div>
            <form onSubmit={submitProject}>
              <label>
                Project name
                <input
                  required
                  autoFocus
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                />
              </label>
              <label>
                Description
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
              <div className="rv-project-baseline-note">
                <strong>Empty class list</strong>
                <p>
                  ReefVision projects start without a built-in taxonomy. Add
                  study-specific classes in the Classes workspace after
                  creation.
                </p>
              </div>
              <div className="modal-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setShowCreate(false)}
                >
                  Cancel
                </button>
                <button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? "Creating..." : "Create project"}
                </button>
              </div>
              {createMutation.error && (
                <p className="form-error">{createMutation.error.message}</p>
              )}
            </form>
          </section>
        </div>
      )}
      {showImport && (
        <ProjectImportDialog
          onClose={() => setShowImport(false)}
          onImported={(projectId) => {
            setShowImport(false);
            setSelectedProjectId(projectId);
            setEditorLaunch(null);
            setActiveView("gallery");
          }}
        />
      )}
      {showOnboarding && (
        <OnboardingModal
          version={health.data?.version ?? applicationVersion}
          onClose={() => setShowOnboarding(false)}
          onDismissPermanently={dismissOnboardingPermanently}
        />
      )}
      {showKeyboardShortcuts && (
        <KeyboardShortcutsDialog
          onClose={() => {
            setShowKeyboardShortcuts(false);
            window.requestAnimationFrame(() =>
              keyboardShortcutsButtonRef.current?.focus(),
            );
          }}
        />
      )}
      {selectedProject && editorLaunch && (
        <EnhancedAnnotationEditor
          project={selectedProject}
          initialImageId={editorLaunch.imageId}
          launchContext={editorLaunch}
          onClose={() => setEditorLaunch(null)}
        />
      )}
    </main>
  );
}

export function App() {
  const detachedRequest = parseDetachedPanelRequest(window.location.search);

  if (detachedRequest?.panelId === "inspector") {
    return <DetachedInspectorWindow projectId={detachedRequest.projectId} />;
  }

  return <ReefVisionMainApp />;
}
