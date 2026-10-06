import type { ReactNode } from "react";

function diagnosticText(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "No additional diagnostic information is available.";
}

export function LoadingState({
  title = "Loading",
  description = "ReefVision is preparing this workspace.",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="async-state loading-state" role="status" aria-live="polite">
      <span className="loading-spinner" aria-hidden="true" />
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div
      className="empty-state shared-empty-state"
      role="status"
      aria-live="polite"
    >
      <span className="empty-state-mark" aria-hidden="true">
        +
      </span>
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title,
  message,
  error,
  onRetry,
  onBack,
}: {
  title: string;
  message: string;
  error?: unknown;
  onRetry?: () => void;
  onBack?: () => void;
}) {
  return (
    <div className="async-state error-state" role="alert">
      <span className="error-state-mark" aria-hidden="true">
        !
      </span>
      <div className="error-state-content">
        <h3>{title}</h3>
        <p>{message}</p>
        {(onRetry || onBack) && (
          <div className="state-actions">
            {onRetry && (
              <button type="button" onClick={onRetry}>
                Retry
              </button>
            )}
            {onBack && (
              <button type="button" className="secondary" onClick={onBack}>
                Go back
              </button>
            )}
          </div>
        )}
        {error !== undefined && (
          <details className="diagnostic-details">
            <summary>View technical details</summary>
            <pre>{diagnosticText(error)}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
