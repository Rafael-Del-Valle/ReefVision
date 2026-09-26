import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from "react";

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
import { DatasetVersionsPanel } from "./features/dataset-versions/DatasetVersionsPanel";
import { Gallery } from "./features/gallery/Gallery";
import { InteroperabilityWorkspace } from "./features/interoperability/InteroperabilityWorkspace";
import { ModelManager } from "./features/models/ModelManager";
import { OnboardingModal } from "./features/onboarding/OnboardingModal";
import { QualityControlDashboard } from "./features/quality-control/QualityControlDashboard";
import { ReviewQueueDashboard } from "./features/review-queues/ReviewQueueDashboard";
import { SystemPanel } from "./features/system/SystemPanel";
import { TrainingWorkspace } from "./features/training/TrainingWorkspace";
import { VideoTrackExchangePanel } from "./features/video/VideoTrackExchangePanel";
import { VideoTrackingWorkspace } from "./features/video/VideoTrackingWorkspace";
import { WorkflowGraphWorkspace } from "./features/workflow-graphs/WorkflowGraphWorkspace";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "./components/ui/AsyncState";
import { StatusBadge } from "./components/ui/StatusBadge";
import { WorkspaceShell } from "./components/ui/WorkspaceShell";
import "./styles/design-system.css";
import "./styles/app.css";

interface AnnotationLaunchState {
  imageId: string;
  returnLabel: string;
  contextTitle?: string;
  contextDescription?: string;
  highlightAnnotationIds?: string[];
  highlightPredictionIds?: string[];
}

type ProjectView =
  | "gallery"
  | "versions"
  | "interoperability"
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

const ONBOARDING_DISMISS_KEY = "reefvision.onboarding.dismissed.1.0.5";

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
        description: "Manage verified pretrained and project-specific models.",
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

export function App() {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  );
  const [showCreate, setShowCreate] = useState(false);
  const [editorLaunch, setEditorLaunch] =
    useState<AnnotationLaunchState | null>(null);
  const [trainingCatalogModelId, setTrainingCatalogModelId] = useState<
    string | null
  >(null);
  const [activeView, setActiveView] = useState<ProjectView>("gallery");
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState<"blank" | "octocoral">("octocoral");
  const [showOnboarding, setShowOnboarding] = useState(false);

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
      createProject({ name: projectName, description, template }),
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

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Marine computer vision workspace</p>
          <h1>ReefVision</h1>
        </div>
        <div className="topbar-actions">
          <button
            type="button"
            className="secondary"
            onClick={() => setShowOnboarding(true)}
          >
            Help and onboarding
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

      <section className="workspace">
        <aside className="sidebar" aria-label="Project dashboard">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Research projects</p>
              <h2>Dashboard</h2>
            </div>
            <button type="button" onClick={() => setShowCreate(true)}>
              New project
            </button>
          </div>

          {projectSummaries.isPending && (
            <LoadingState
              title="Loading projects"
              description="Finding your local ReefVision projects."
            />
          )}
          {projectSummaries.error && (
            <ErrorState
              title="Projects could not be loaded"
              message="ReefVision could not connect to its local service."
              error={projectSummaries.error}
              onRetry={() => void projectSummaries.refetch()}
            />
          )}
          {projectSummaries.data?.length === 0 && (
            <EmptyState
              title="No projects yet"
              description="Create a project to begin organizing images, annotations, and datasets."
              action={
                <button type="button" onClick={() => setShowCreate(true)}>
                  Create project
                </button>
              }
            />
          )}
          <div className="project-list">
            <button
              type="button"
              className={`project-card ${activeView === "system" ? "selected" : ""}`}
              onClick={() => {
                setSelectedProjectId(null);
                setEditorLaunch(null);
                setActiveView("system");
              }}
            >
              <strong>System status</strong>
              <span>Application health, backups, and diagnostics</span>
              <small>Local ReefVision service</small>
            </button>
            {projectSummaries.data?.map((project: ProjectSummary) => (
              <button
                type="button"
                key={project.id}
                className={`project-card ${selectedProjectId === project.id ? "selected" : ""}`}
                onClick={() => {
                  setSelectedProjectId(project.id);
                  setEditorLaunch(null);
                  setActiveView("gallery");
                }}
              >
                <strong>{project.name}</strong>
                <span>{project.description || "No description"}</span>
                <small>
                  {project.active_label_class_count} active{" "}
                  {project.active_label_class_count === 1 ? "class" : "classes"}{" "}
                  · Updated {new Date(project.updated_at).toLocaleDateString()}
                </small>
              </button>
            ))}
          </div>
        </aside>

        <section className="detail-panel" aria-live="polite">
          {activeView === "system" && (
            <SystemPanel onOpenOnboarding={() => setShowOnboarding(true)} />
          )}
          {!selectedProjectId && activeView !== "system" && (
            <WorkspaceShell
              eyebrow="Local-first scientific workspace"
              title="Welcome to ReefVision"
              description="Open a research project to manage imagery, annotations, models, review, and reproducible datasets."
              actions={
                <button type="button" onClick={() => setShowCreate(true)}>
                  Create project
                </button>
              }
            >
              <div className="dashboard-intro-grid">
                <article>
                  <h3>Keep research organized</h3>
                  <p>
                    Projects keep source imagery, stable classes, and scientific
                    provenance together on this computer.
                  </p>
                </article>
                <article>
                  <h3>Work with confidence</h3>
                  <p>
                    Predictions remain separate from verified annotations until
                    a researcher explicitly accepts them.
                  </p>
                </article>
                <article>
                  <h3>Build reproducible datasets</h3>
                  <p>
                    Create immutable dataset versions without changing original
                    source images.
                  </p>
                </article>
              </div>
            </WorkspaceShell>
          )}
          {selectedProjectId &&
            !selectedProject &&
            selectedProjectQuery.isPending && (
              <LoadingState
                title={`Opening ${selectedProjectSummary?.name ?? "project"}`}
                description="Loading classes, settings, and workspace details."
              />
            )}
          {selectedProjectId && selectedProjectQuery.error && (
            <ErrorState
              title="The requested project could not be loaded"
              message={`${selectedProjectSummary?.name ?? "This project"} is currently unavailable.`}
              error={selectedProjectQuery.error}
              onRetry={() => void selectedProjectQuery.refetch()}
              onBack={() => setSelectedProjectId(null)}
            />
          )}
          {selectedProject && activeView !== "system" && (
            <div>
              <div className="project-header">
                <div>
                  <p className="eyebrow">Open project</p>
                  <h2>{selectedProject.name}</h2>
                  <p>
                    {selectedProject.description || "No project description."}
                  </p>
                  <details className="project-details">
                    <summary>Project details</summary>
                    <code>{selectedProject.storage_root}</code>
                  </details>
                </div>
                <button
                  type="button"
                  className="danger-ghost"
                  onClick={() => {
                    if (window.confirm(`Archive ${selectedProject.name}?`)) {
                      archiveMutation.mutate(selectedProject.id);
                    }
                  }}
                >
                  Archive project
                </button>
              </div>

              <nav
                className="project-navigation"
                aria-label="Project workspace navigation"
              >
                <div
                  className="project-nav-groups"
                  role="tablist"
                  aria-label="Workspace groups"
                >
                  {PROJECT_NAV_GROUPS.map((group) => {
                    const selected = group.id === activeProjectGroup?.id;
                    return (
                      <button
                        key={group.id}
                        type="button"
                        role="tab"
                        aria-label={group.label}
                        aria-selected={selected}
                        tabIndex={selected ? 0 : -1}
                        className={selected ? "active" : "secondary"}
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
                        <span>{group.description}</span>
                      </button>
                    );
                  })}
                </div>
                <div
                  className="project-nav-items"
                  role="tablist"
                  aria-label={activeProjectGroup?.label ?? "Project sections"}
                >
                  {activeProjectGroup?.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="tab"
                      aria-selected={activeView === item.id}
                      tabIndex={activeView === item.id ? 0 : -1}
                      className={
                        activeView === item.id ? "active" : "secondary"
                      }
                      onClick={() => setActiveView(item.id)}
                      onKeyDown={(event) =>
                        handleTabKeys(
                          event,
                          activeProjectGroup.items.map((value) => value.id),
                          activeView as ProjectTab,
                          setActiveView,
                        )
                      }
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                {activeProjectItem && (
                  <div className="workspace-context" aria-live="polite">
                    <div>
                      <p className="eyebrow">{activeProjectGroup?.label}</p>
                      <h3>{activeProjectItem.label}</h3>
                    </div>
                    <p>{activeProjectItem.description}</p>
                  </div>
                )}
              </nav>

              {activeView === "gallery" && (
                <Gallery
                  project={selectedProject}
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
              {activeView === "classification" && (
                <ClassificationWorkspace project={selectedProject} />
              )}
              {activeView === "advanced_providers" && (
                <AdvancedProviderWorkspace project={selectedProject} />
              )}
              {activeView === "workflows" && (
                <WorkflowGraphWorkspace project={selectedProject} />
              )}
              {activeView === "video" && (
                <>
                  <VideoTrackingWorkspace project={selectedProject} />
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
                  onOpenImage={(item: ReviewQueueItem) =>
                    setEditorLaunch({
                      imageId: item.image_id,
                      returnLabel: "Back to Review Queue",
                      contextTitle: `Review score ${item.score.toFixed(2)}`,
                      contextDescription:
                        item.reason_summary ??
                        "This image was ranked for human review.",
                    })
                  }
                />
              )}
              {activeView === "classes" && (
                <ClassManagerPanel project={selectedProject} />
              )}
            </div>
          )}
        </section>
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
              <label>
                Class template
                <select
                  value={template}
                  onChange={(event) =>
                    setTemplate(event.target.value as "blank" | "octocoral")
                  }
                >
                  <option value="octocoral">
                    Six-class octocoral template
                  </option>
                  <option value="blank">Blank class list</option>
                </select>
              </label>
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
      {showOnboarding && (
        <OnboardingModal
          version={health.data?.version ?? applicationVersion}
          onClose={() => setShowOnboarding(false)}
          onDismissPermanently={dismissOnboardingPermanently}
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
