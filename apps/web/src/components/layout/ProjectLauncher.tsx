import { useMemo, useState } from "react";

import type { ProjectSummary } from "../../api/client";
import { ErrorState, LoadingState } from "../ui/AsyncState";
import { StatusBadge } from "../ui/StatusBadge";

const PINNED_PROJECTS_KEY = "reefvision.ui.pinned-projects.v1";

function readPinnedProjects(): string[] {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(PINNED_PROJECTS_KEY) ?? "[]",
    ) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((value): value is string => typeof value === "string")
      : [];
  } catch {
    return [];
  }
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Updated recently";
  return `Updated ${date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year:
      date.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  })}`;
}

export function ProjectLauncher({
  projects,
  projectsState,
  version,
  serviceState,
  onRetryProjects,
  onCreateProject,
  onQuickStart,
  onOpenProject,
  onImportPackage,
  onOpenSystem,
  onOpenOnboarding,
}: {
  projects: ProjectSummary[];
  projectsState: "pending" | "ready" | "error";
  version: string;
  serviceState: "pending" | "ready" | "unavailable";
  onRetryProjects: () => void;
  onCreateProject: () => void;
  onQuickStart: (template: "blank") => void;
  onOpenProject: (projectId: string) => void;
  onImportPackage: () => void;
  onOpenSystem: () => void;
  onOpenOnboarding: () => void;
}) {
  const [pinnedIds, setPinnedIds] = useState<string[]>(readPinnedProjects);
  const [projectQuery, setProjectQuery] = useState("");
  const [showAllProjects, setShowAllProjects] = useState(false);

  const recentProjects = useMemo(
    () =>
      [...projects].sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      ),
    [projects],
  );

  const pinnedProjects = recentProjects.filter((project) =>
    pinnedIds.includes(project.id),
  );

  function togglePinned(projectId: string): void {
    setPinnedIds((current) => {
      const next = current.includes(projectId)
        ? current.filter((value) => value !== projectId)
        : [...current, projectId];
      window.localStorage.setItem(PINNED_PROJECTS_KEY, JSON.stringify(next));
      return next;
    });
  }

  const projectCollection =
    pinnedProjects.length > 0
      ? [
          ...pinnedProjects,
          ...recentProjects.filter(
            (project) => !pinnedIds.includes(project.id),
          ),
        ]
      : recentProjects;

  // The first twelve cards are a quick preview, not the complete project list.
  // Researchers must be able to reopen older projects without changing data.
  const normalizedQuery = projectQuery.trim().toLocaleLowerCase();
  const matchingProjects = normalizedQuery
    ? projectCollection.filter((project) =>
        `${project.name} ${project.description ?? ""}`
          .toLocaleLowerCase()
          .includes(normalizedQuery),
      )
    : projectCollection;
  const visibleProjects = showAllProjects
    ? matchingProjects
    : matchingProjects.slice(0, 12);

  return (
    <section className="rv-launcher" aria-label="ReefVision project launcher">
      <header className="rv-launcher-hero">
        <div className="rv-launcher-copy">
          <p className="eyebrow">Scientist workspace</p>
          <h2>Turn imagery into reviewable scientific evidence.</h2>
          <p>
            Start or reopen a local ReefVision project, then move between
            annotation, model inference, pose tracking, measurements, review,
            and reproducible exports without leaving the project workspace.
          </p>
          <div className="rv-launcher-actions">
            <button type="button" onClick={onCreateProject}>
              New project
            </button>
            <button
              type="button"
              className="secondary"
              onClick={onImportPackage}
              title="Import a portable ReefVision project package as a new local project."
            >
              Import project
            </button>
            <button
              type="button"
              className="secondary"
              onClick={onOpenOnboarding}
            >
              Quick start guide
            </button>
          </div>
        </div>

        <aside
          className="rv-launcher-release"
          aria-label="Local system summary"
        >
          <div className="rv-launcher-release-heading">
            <span className="rv-brand-mark" aria-hidden="true">
              RV
            </span>
            <div>
              <strong>ReefVision {version}</strong>
              <small>Local-first research environment</small>
            </div>
          </div>
          <dl>
            <div>
              <dt>Local service</dt>
              <dd>
                <StatusBadge
                  status={
                    serviceState === "ready"
                      ? "ready"
                      : serviceState === "pending"
                        ? "pending"
                        : "unavailable"
                  }
                  label={
                    serviceState === "ready"
                      ? "Ready"
                      : serviceState === "pending"
                        ? "Connecting"
                        : "Unavailable"
                  }
                />
              </dd>
            </div>
            <div>
              <dt>Projects</dt>
              <dd>{projectsState === "ready" ? projects.length : "Unknown"}</dd>
            </div>
            <div>
              <dt>Execution</dt>
              <dd>Local / offline-capable</dd>
            </div>
          </dl>
          <button type="button" className="secondary" onClick={onOpenSystem}>
            System status
          </button>
        </aside>
      </header>

      <div className="rv-launcher-section-heading">
        <div>
          <p className="eyebrow">Recent work</p>
          <h3>
            {pinnedProjects.length > 0
              ? "Pinned and recent projects"
              : "Recent projects"}
          </h3>
        </div>
        <span>
          {projectsState === "ready"
            ? `${projects.length} local project${projects.length === 1 ? "" : "s"}`
            : projectsState === "pending"
              ? "Loading projects"
              : "Project list unavailable"}
        </span>
      </div>

      {projectsState === "ready" && projects.length > 0 && (
        <label className="rv-project-launcher-search">
          Find a saved project
          <input
            type="search"
            value={projectQuery}
            onChange={(event) => {
              setProjectQuery(event.target.value);
              setShowAllProjects(false);
            }}
            placeholder="Search project names or descriptions"
          />
        </label>
      )}

      {projectsState === "pending" ? (
        <LoadingState
          title="Loading local projects"
          description="Checking saved project summaries without changing research data."
        />
      ) : projectsState === "error" ? (
        <div className="rv-launcher-recovery">
          <ErrorState
            title="Local projects could not be loaded"
            message="The project list is unavailable. This does not mean saved projects were deleted or that the workspace is empty."
            onRetry={onRetryProjects}
          />
        </div>
      ) : matchingProjects.length > 0 ? (
        <div>
          <div className="rv-project-launcher-grid">
            {visibleProjects.map((project) => {
            const pinned = pinnedIds.includes(project.id);
            return (
              <article className="rv-project-launcher-card" key={project.id}>
                <button
                  type="button"
                  className="rv-project-launcher-open"
                  onClick={() => onOpenProject(project.id)}
                  aria-label={`Open ${project.name}`}
                >
                  <span className="rv-project-card-kicker">
                    {pinned ? "Pinned project" : "Research project"}
                  </span>
                  <strong>{project.name}</strong>
                  <span>
                    {project.description || "No project description."}
                  </span>
                  <small>
                    {project.active_label_class_count} active{" "}
                    {project.active_label_class_count === 1
                      ? "class"
                      : "classes"}{" "}
                    · {formatUpdatedAt(project.updated_at)}
                  </small>
                </button>
                <button
                  type="button"
                  className="rv-pin-button"
                  aria-pressed={pinned}
                  onClick={() => togglePinned(project.id)}
                >
                  {pinned ? "Unpin" : "Pin"}
                </button>
              </article>
            );
            })}
          </div>
          {matchingProjects.length > 12 && (
            <button
              type="button"
              className="secondary"
              onClick={() => setShowAllProjects((current) => !current)}
            >
              {showAllProjects
                ? "Show fewer projects"
                : `Show all ${matchingProjects.length} matching projects`}
            </button>
          )}
        </div>
      ) : normalizedQuery ? (
        <div className="rv-launcher-empty" role="status">
          <h3>No matching projects</h3>
          <p>Try another name or description. Saved projects have not been changed.</p>
        </div>
      ) : (
        <div className="rv-launcher-empty">
          <span className="rv-empty-glyph" aria-hidden="true">
            +
          </span>
          <div>
            <h3>No projects yet</h3>
            <p>
              Create a project to start organizing images, annotations,
              measurements, models, and review evidence.
            </p>
          </div>
          <button type="button" onClick={onCreateProject}>
            Create project
          </button>
        </div>
      )}

      <div className="rv-launcher-lower-grid">
        <section className="rv-launcher-panel">
          <div className="rv-launcher-section-heading">
            <div>
              <p className="eyebrow">Quick start</p>
              <h3>Start with the right scientific workspace</h3>
            </div>
          </div>
          <div className="rv-quick-start-grid">
            <button type="button" onClick={() => onQuickStart("blank")}>
              <span>01</span>
              <strong>General image analysis</strong>
              <small>
                Empty class list for detection, segmentation, measurements,
                classification, or custom scientific annotation.
              </small>
            </button>
            <button type="button" onClick={() => onQuickStart("blank")}>
              <span>02</span>
              <strong>Video + pose study</strong>
              <small>
                Empty class list ready for video tracking, repeated landmarks,
                behavior workflows, and custom taxonomies.
              </small>
            </button>
            <button type="button" onClick={onImportPackage}>
              <span>03</span>
              <strong>Import existing project</strong>
              <small>
                Receive a portable ReefVision project from another computer or
                collaborator.
              </small>
            </button>
          </div>
        </section>

        <section className="rv-launcher-panel rv-whats-new">
          <p className="eyebrow">What&apos;s new</p>
          <h3>Scientist Workspace redesign</h3>
          <p>
            ReefVision is moving to a persistent project workbench with a
            compact navigation rail, context inspector, review-first workflows,
            and saved workspace layouts while preserving the validated
            scientific backend.
          </p>
          <ul>
            <li>Packaged CPU/CUDA provider validation</li>
            <li>Pose Active Learning workflow builder</li>
            <li>Project Exchange and Results Package provenance</li>
          </ul>
        </section>
      </div>
    </section>
  );
}
