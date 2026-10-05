import { useMemo, useState } from "react";

import type { ProjectSummary } from "../../api/client";
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
  version,
  serviceState,
  onCreateProject,
  onQuickStart,
  onOpenProject,
  onImportPackage,
  onOpenSystem,
  onOpenOnboarding,
}: {
  projects: ProjectSummary[];
  version: string;
  serviceState: "pending" | "ready" | "unavailable";
  onCreateProject: () => void;
  onQuickStart: (template: "blank" | "octocoral") => void;
  onOpenProject: (projectId: string) => void;
  onImportPackage: () => void;
  onOpenSystem: () => void;
  onOpenOnboarding: () => void;
}) {
  const [pinnedIds, setPinnedIds] = useState<string[]>(readPinnedProjects);

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
              disabled={projects.length === 0}
              title={
                projects.length === 0
                  ? "Create or open a project before importing an exchange package."
                  : "Open Project Exchange import in the most recent project."
              }
            >
              Import package
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
              <dd>{projects.length}</dd>
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
          {projects.length} local project{projects.length === 1 ? "" : "s"}
        </span>
      </div>

      {projectCollection.length > 0 ? (
        <div className="rv-project-launcher-grid">
          {projectCollection.slice(0, 12).map((project) => {
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
            <button type="button" onClick={() => onQuickStart("octocoral")}>
              <span>01</span>
              <strong>Octocoral monitoring</strong>
              <small>
                Start with the six-class octocoral annotation template.
              </small>
            </button>
            <button type="button" onClick={() => onQuickStart("blank")}>
              <span>02</span>
              <strong>General image analysis</strong>
              <small>
                Blank project for detection, segmentation, measurements, or
                classification.
              </small>
            </button>
            <button type="button" onClick={() => onQuickStart("blank")}>
              <span>03</span>
              <strong>Video + pose study</strong>
              <small>
                Blank project ready for video tracking, repeated landmarks, and
                behavior workflows.
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
