import type { ReactNode } from "react";

import type { Project } from "../../api/client";

export function ProjectWorkbenchShell({
  project,
  navigation,
  contextTitle,
  contextDescription,
  onHome,
  onSystem,
  onArchive,
  children,
  inspector,
}: {
  project: Project;
  navigation: ReactNode;
  contextTitle: string;
  contextDescription: string;
  onHome: () => void;
  onSystem: () => void;
  onArchive: () => void;
  children: ReactNode;
  inspector?: ReactNode;
}) {
  return (
    <section className="rv-project-workbench">
      <aside className="rv-workbench-rail" aria-label="Project workspace navigation">
        <div className="rv-workbench-project">
          <button
            type="button"
            className="rv-home-button"
            onClick={onHome}
            aria-label="Back to ReefVision home"
          >
            <span aria-hidden="true">RV</span>
          </button>
          <div>
            <p className="eyebrow">Open project</p>
            <h2 title={project.name}>{project.name}</h2>
            <p>{project.description || "No project description."}</p>
          </div>
        </div>

        {navigation}

        <div className="rv-workbench-rail-footer">
          <button type="button" className="secondary" onClick={onSystem}>
            System status
          </button>
          <details>
            <summary>Project options</summary>
            <code>{project.storage_root}</code>
            <button type="button" className="danger-ghost" onClick={onArchive}>
              Archive project
            </button>
          </details>
        </div>
      </aside>

      <section className="rv-workbench-main">
        <header className="rv-workbench-toolbar">
          <div>
            <p className="eyebrow">Scientist workspace</p>
            <h3>{contextTitle}</h3>
            <p>{contextDescription}</p>
          </div>
          <div className="rv-workbench-toolbar-meta" aria-label="Workspace context">
            <span>Local project</span>
            <span>Scientist review enabled</span>
          </div>
        </header>

        <div className="rv-workbench-stage">{children}</div>
      </section>

      <aside className="rv-workbench-inspector" aria-label="Workspace inspector">
        <div className="rv-inspector-heading">
          <p className="eyebrow">Inspector</p>
          <h3>{contextTitle}</h3>
          <p>{contextDescription}</p>
        </div>
        {inspector ?? (
          <div className="rv-inspector-card">
            <strong>Project context</strong>
            <dl>
              <div>
                <dt>Active classes</dt>
                <dd>{project.label_classes.filter((item) => item.is_active).length}</dd>
              </div>
              <div>
                <dt>Annotation type</dt>
                <dd>{project.default_annotation_type}</dd>
              </div>
              <div>
                <dt>Workspace</dt>
                <dd>Local</dd>
              </div>
            </dl>
            <p>
              Tool-specific controls stay inside each validated ReefVision
              workspace while this inspector provides stable project context.
            </p>
          </div>
        )}
      </aside>
    </section>
  );
}
