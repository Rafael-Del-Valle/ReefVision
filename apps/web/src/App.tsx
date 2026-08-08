import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

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
import { EnhancedAnnotationEditor } from "./features/annotation-editor/EnhancedAnnotationEditor";
import { ClassManagerPanel } from "./features/classes/ClassManagerPanel";
import { ClassificationWorkspace } from "./features/classification/ClassificationWorkspace";
import { DatasetVersionsPanel } from "./features/dataset-versions/DatasetVersionsPanel";
import { Gallery } from "./features/gallery/Gallery";
import { ModelManager } from "./features/models/ModelManager";
import { OnboardingModal } from "./features/onboarding/OnboardingModal";
import { QualityControlDashboard } from "./features/quality-control/QualityControlDashboard";
import { ReviewQueueDashboard } from "./features/review-queues/ReviewQueueDashboard";
import { SystemPanel } from "./features/system/SystemPanel";
import { TrainingWorkspace } from "./features/training/TrainingWorkspace";
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
  | "classification"
  | "classes"
  | "quality_control"
  | "review_queue"
  | "system";

const ONBOARDING_DISMISS_KEY = "reefvision.onboarding.dismissed.1.6.0";

export function App() {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
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

  const projectTabs: Array<{ id: Exclude<ProjectView, "system">; label: string }> = [
    { id: "gallery", label: "Images" },
    { id: "versions", label: "Versions" },
    { id: "training", label: "Training" },
    { id: "classification", label: "Classification" },
    { id: "models", label: "Models" },
    { id: "quality_control", label: "Quality Control" },
    { id: "review_queue", label: "Review Queue" },
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
            <span className={`status-dot ${health.isSuccess ? "online" : ""}`} />
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
                  <p>{selectedProject.description || "No project description."}</p>
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
              >
                {projectTabs.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
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
              {activeView === "classification" && (
                <ClassificationWorkspace project={selectedProject} />
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
                  <option value="octocoral">Six-class octocoral template</option>
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
