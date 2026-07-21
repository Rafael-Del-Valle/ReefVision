import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  archiveProject,
  createProject,
  getHealth,
  getProject,
  getProjectSummaries,
  type ProjectSummary,
  type QualityControlIssue,
  type ReviewQueueItem,
} from "./api/client";
import { EnhancedAnnotationEditor } from "./features/annotation-editor/EnhancedAnnotationEditor";
import { ModelEvaluationDashboard } from "./features/advancement/ModelEvaluationDashboard";
import { ProjectIntegrityDashboard } from "./features/advancement/ProjectIntegrityDashboard";
import { WorkflowDashboard } from "./features/advancement/WorkflowDashboard";
import { ClassManagerPanel } from "./features/classes/ClassManagerPanel";
import { ClassificationDashboard } from "./features/classification/ClassificationDashboard";
import { DatasetVersionsPanel } from "./features/dataset-versions/DatasetVersionsPanel";
import { DepthDashboard } from "./features/depth/DepthDashboard";
import { EmbeddingDashboard } from "./features/embeddings/EmbeddingDashboard";
import { Gallery } from "./features/gallery/Gallery";
import { MeasurementsDashboard } from "./features/measurements/MeasurementsDashboard";
import { ModelManager } from "./features/models/ModelManager";
import { OnboardingModal } from "./features/onboarding/OnboardingModal";
import "./features/phase456/phase456.css";
import { QualityControlDashboard } from "./features/quality-control/QualityControlDashboard";
import { ProviderDashboard } from "./features/providers/ProviderDashboard";
import { TrainingReportsDashboard } from "./features/reports/TrainingReportsDashboard";
import { ReviewQueueDashboard } from "./features/review-queues/ReviewQueueDashboard";
import { SystemPanel } from "./features/system/SystemPanel";
import { TrainingWorkspace } from "./features/training/TrainingWorkspace";
import { TuningDashboard } from "./features/tuning/TuningDashboard";
import { VideoDashboard } from "./features/videos/VideoDashboard";
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
  | "models"
  | "training"
  | "tuning"
  | "reports"
  | "measurements"
  | "depth"
  | "classification"
  | "videos"
  | "evaluation"
  | "active_learning"
  | "providers"
  | "integrity"
  | "workflows"
  | "classes"
  | "quality_control"
  | "review_queue"
  | "system";

const ONBOARDING_DISMISS_KEY = "reefvision.onboarding.dismissed.1.6.0";

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
  const activeProjectTabRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const activeTab = activeProjectTabRef.current;
    if (activeTab && typeof activeTab.scrollIntoView === "function") {
      activeTab.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "nearest",
      });
    }
  }, [activeView]);
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

  const projectTabs: Array<{ id: ProjectView; label: string }> = [
    { id: "gallery", label: "Images" },
    { id: "versions", label: "Versions" },
    { id: "training", label: "Training" },
    { id: "tuning", label: "Tuning" },
    { id: "reports", label: "Reports" },
    { id: "models", label: "Models" },
    { id: "measurements", label: "Measurements" },
    { id: "depth", label: "Depth" },
    { id: "classification", label: "Classification" },
    { id: "videos", label: "Video" },
    { id: "evaluation", label: "Evaluation" },
    { id: "active_learning", label: "Active Learning" },
    { id: "providers", label: "Providers" },
    { id: "quality_control", label: "Quality Control" },
    { id: "review_queue", label: "Review Queue" },
    { id: "integrity", label: "Integrity" },
    { id: "workflows", label: "Workflows" },
    { id: "classes", label: "Classes" },
  ];

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
            <span
              className={`status-dot ${health.isSuccess ? "online" : ""}`}
            />
            {health.isPending && "Checking API..."}
            {health.isError && "API unavailable"}
            {health.data && `Local API ${health.data.version}`}
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

          {projectSummaries.isPending && <p>Loading projects...</p>}
          {projectSummaries.error && (
            <p className="form-error">{projectSummaries.error.message}</p>
          )}
          {projectSummaries.data?.length === 0 && (
            <div className="empty-state">
              <h3>No projects yet</h3>
              <p>
                Create a project to establish its class map and managed research
                directory.
              </p>
            </div>
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
              <span>Version, schema, compatibility, and logs</span>
              <small>Milestone 8 foundations</small>
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
                <span>{project.active_label_class_count} active classes</span>
                <small>{project.slug}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="detail-panel" aria-live="polite">
          {activeView === "system" && (
            <SystemPanel onOpenOnboarding={() => setShowOnboarding(true)} />
          )}
          {!selectedProjectId && activeView !== "system" && (
            <div className="welcome-panel">
              <p className="eyebrow">Local-first research data</p>
              <h2>Select a project</h2>
              <p>
                Select a project to import marine imagery, organize related
                samples, and manage stable annotation classes.
              </p>
            </div>
          )}
          {selectedProjectId &&
            !selectedProject &&
            selectedProjectQuery.isPending && (
              <div className="welcome-panel">
                <p className="eyebrow">Opening project</p>
                <h2>{selectedProjectSummary?.name ?? "Loading project"}</h2>
                <p>Loading classes, settings, and workspace details.</p>
              </div>
            )}
          {selectedProjectId && selectedProjectQuery.error && (
            <div className="welcome-panel">
              <p className="eyebrow">Project unavailable</p>
              <h2>{selectedProjectSummary?.name ?? "Project"}</h2>
              <p className="form-error">{selectedProjectQuery.error.message}</p>
            </div>
          )}
          {selectedProject && activeView !== "system" && (
            <div>
              <div className="project-header">
                <div>
                  <p className="eyebrow">Project settings</p>
                  <h2>{selectedProject.name}</h2>
                  <p>
                    {selectedProject.description || "No project description."}
                  </p>
                  <code>{selectedProject.storage_root}</code>
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

              <div
                className="project-tabs"
                role="tablist"
                aria-label="Project sections"
                aria-description="Scroll horizontally to reach additional project sections."
              >
                {projectTabs.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    ref={
                      activeView === tab.id ? activeProjectTabRef : undefined
                    }
                    aria-selected={activeView === tab.id}
                    className={activeView === tab.id ? "active" : "secondary"}
                    onClick={() => setActiveView(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

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
              {activeView === "tuning" && (
                <TuningDashboard project={selectedProject} />
              )}
              {activeView === "reports" && (
                <TrainingReportsDashboard project={selectedProject} />
              )}
              {activeView === "measurements" && (
                <MeasurementsDashboard project={selectedProject} />
              )}
              {activeView === "depth" && (
                <DepthDashboard project={selectedProject} />
              )}
              {activeView === "classification" && (
                <ClassificationDashboard project={selectedProject} />
              )}
              {activeView === "videos" && (
                <VideoDashboard project={selectedProject} />
              )}
              {activeView === "evaluation" && (
                <ModelEvaluationDashboard project={selectedProject} />
              )}
              {activeView === "active_learning" && (
                <EmbeddingDashboard
                  project={selectedProject}
                  onOpenImage={(item: ReviewQueueItem) =>
                    setEditorLaunch({
                      imageId: item.image_id,
                      returnLabel: "Back to Active Learning",
                      contextTitle: `Active-learning rank ${item.rank_position}`,
                      contextDescription:
                        item.reason_summary ||
                        item.selection_reasons_json.join(" · ") ||
                        "Selected for active-learning review.",
                    })
                  }
                  onLaunchTraining={() => setActiveView("training")}
                />
              )}
              {activeView === "providers" && (
                <ProviderDashboard project={selectedProject} />
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
              {activeView === "integrity" && (
                <ProjectIntegrityDashboard project={selectedProject} />
              )}
              {activeView === "workflows" && (
                <WorkflowDashboard project={selectedProject} />
              )}
              {activeView === "classes" && (
                <ClassManagerPanel project={selectedProject} />
              )}
            </div>
          )}
        </section>
      </section>

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
          version={health.data?.version ?? "1.6.0"}
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
