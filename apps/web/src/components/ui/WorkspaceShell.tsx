import type { ReactNode } from "react";

export function WorkspaceShell({
  eyebrow,
  title,
  description,
  actions,
  summary,
  children,
  advanced,
  className = "",
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  summary?: ReactNode;
  children: ReactNode;
  advanced?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rv-workspace-shell ${className}`.trim()}>
      <header className="rv-page-header">
        <div className="rv-page-heading">
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h2>{title}</h2>
          {description && <p className="page-subtitle">{description}</p>}
        </div>
        {actions && <div className="rv-page-actions">{actions}</div>}
      </header>
      {summary && <div className="rv-summary-grid">{summary}</div>}
      <div className="rv-workspace-content">{children}</div>
      {advanced && (
        <details className="rv-advanced">
          <summary>Advanced</summary>
          <div>{advanced}</div>
        </details>
      )}
    </section>
  );
}
