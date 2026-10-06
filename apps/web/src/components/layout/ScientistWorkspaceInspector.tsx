import type { WorkspacePresetId } from "./workspacePresets";
import { workspacePreset } from "./workspacePresets";
import {
  workspaceInspectorDefinition,
  workspacePresetInspectorGuidance,
  type WorkspaceEvidenceBoundary,
  type WorkspaceInspectorView,
} from "./workspaceInspector";

const BOUNDARY_LABELS: Record<WorkspaceEvidenceBoundary, string> = {
  mixed: "Reviewable evidence",
  provisional: "Machine output provisional",
  review: "Scientist decision required",
  record: "Persisted project record",
};

export function ScientistWorkspaceInspector({
  activeView,
  activePreset,
  activeClassCount,
  annotationType,
  onNavigate,
}: {
  activeView: WorkspaceInspectorView;
  activePreset: WorkspacePresetId;
  activeClassCount: number;
  annotationType: string;
  onNavigate: (view: WorkspaceInspectorView) => void;
}) {
  const definition = workspaceInspectorDefinition(activeView);
  const guidance = workspacePresetInspectorGuidance(activePreset);
  const preset = workspacePreset(activePreset);
  const reviewMode = activePreset === "review";

  return (
    <div
      className="rv-scientist-inspector"
      data-workspace-view={activeView}
      data-workspace-preset={activePreset}
    >
      <section
        className="rv-inspector-card"
        aria-label="Scientist workflow context"
      >
        <div className="rv-inspector-card-heading">
          <span
            className={`rv-inspector-boundary boundary-${definition.boundary}`}
            data-boundary={definition.boundary}
          >
            {BOUNDARY_LABELS[definition.boundary]}
          </span>
        </div>

        <strong>{definition.title}</strong>
        <p>{definition.summary}</p>

        <div className="rv-inspector-policy">
          <span>Record policy</span>
          <p>{definition.recordPolicy}</p>
        </div>
      </section>

      <section
        className="rv-inspector-card rv-inspector-truth"
        aria-label="Scientific truth boundary"
      >
        <div className="rv-inspector-card-heading">
          <strong>Scientific truth boundary</strong>
          <span
            className={reviewMode ? "review-required" : ""}
            data-review-mode={reviewMode ? "true" : "false"}
          >
            {reviewMode
              ? "Human verification required"
              : "Human verification available"}
          </span>
        </div>

        <div className="rv-inspector-truth-grid">
          <div>
            <span>Machine output</span>
            <strong>Provisional</strong>
            <small>
              Predictions, scores, tracks, provider results, and automated
              measurements remain reviewable evidence.
            </small>
          </div>

          <div>
            <span>Scientist truth</span>
            <strong>Explicitly verified</strong>
            <small>
              Accepted project truth changes only through the canonical workflow
              and an explicit scientist action.
            </small>
          </div>
        </div>
      </section>

      <section
        className="rv-inspector-card"
        aria-label="Workspace preset guidance"
      >
        <span className="rv-inspector-kicker">{preset.label}</span>
        <strong>{guidance.title}</strong>
        <p>{guidance.description}</p>
      </section>

      <section
        className="rv-inspector-card"
        aria-label="Related canonical tools"
      >
        <strong>Related canonical tools</strong>
        <p>
          These shortcuts only change the visible workspace. Scientific state
          remains owned by the destination tool.
        </p>

        <div className="rv-inspector-actions">
          {definition.actions.map((action) => (
            <button
              key={`${activeView}-${action.target}`}
              type="button"
              className="secondary"
              onClick={() => onNavigate(action.target)}
            >
              <strong>{action.label}</strong>
              <small>{action.description}</small>
            </button>
          ))}
        </div>
      </section>

      <section
        className="rv-inspector-card"
        aria-label="Project inspector context"
      >
        <strong>Project context</strong>

        <dl>
          <div>
            <dt>Active classes</dt>
            <dd>{activeClassCount}</dd>
          </div>
          <div>
            <dt>Annotation type</dt>
            <dd>{annotationType}</dd>
          </div>
          <div>
            <dt>Preset</dt>
            <dd>{preset.label}</dd>
          </div>
          <div>
            <dt>State owner</dt>
            <dd>Canonical workspace</dd>
          </div>
        </dl>

        <p>
          Inspector content is contextual UI only. It does not create a second
          source of scientific state.
        </p>
      </section>
    </div>
  );
}
