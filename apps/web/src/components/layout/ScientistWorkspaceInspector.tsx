import type { ReactNode } from "react";

import type { ReviewQueueItem } from "../../api/client";
import type { VideoWorkspaceContext } from "../../features/video/videoWorkspaceBridge";
import {
  panelPluginStatus,
  useContextualPanelLayout,
} from "./ContextualPanelLayout";
import {
  contextualPanels,
  emptyPanelPreferences,
} from "./contextualPanelPreferences";
import { ProjectInferenceInspector } from "./ProjectInferenceInspector";
import { ProjectMorphometricsInspector } from "./ProjectMorphometricsInspector";
import { ProjectTrainingMonitor } from "./ProjectTrainingMonitor";
import { ProjectReviewInspector } from "./ProjectReviewInspector";
import { ProjectVideoPoseInspector } from "./ProjectVideoPoseInspector";
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
  projectId,
  inferenceSelectedImageIds = [],
  focusedImageId = null,
  selectedReviewQueueId = null,
  videoWorkspaceContext = null,
  onOpenMeasurements,
  onOpenReviewItem,
  onVideoSelect,
  onVideoFrameChange,
  onVideoTrackChange,
  onNavigate,
}: {
  activeView: WorkspaceInspectorView;
  activePreset: WorkspacePresetId;
  activeClassCount: number;
  annotationType: string;
  projectId?: string;
  inferenceSelectedImageIds?: string[];
  focusedImageId?: string | null;
  selectedReviewQueueId?: string | null;
  videoWorkspaceContext?: VideoWorkspaceContext | null;
  onOpenMeasurements?: (imageId: string) => void;
  onOpenReviewItem?: (item: ReviewQueueItem) => void;
  onVideoSelect?: (videoId: string) => void;
  onVideoFrameChange?: (frameIndex: number) => void;
  onVideoTrackChange?: (trackId: string) => void;
  onNavigate: (view: WorkspaceInspectorView) => void;
}) {
  const definition = workspaceInspectorDefinition(activeView);
  const guidance = workspacePresetInspectorGuidance(activePreset);
  const preset = workspacePreset(activePreset);
  const reviewMode = activePreset === "review";
  const layout = useContextualPanelLayout();
  const panels =
    layout?.panels ??
    contextualPanels(emptyPanelPreferences(), activeView, activePreset);

  const cards: Record<string, ReactNode> = {
    "workflow-context": (
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

        <details className="rv-inspector-policy">
          <summary>Evidence and review policy</summary>
          <p>{definition.recordPolicy}</p>
        </details>
      </section>
    ),

    "image-inference": projectId && (
      <ProjectInferenceInspector
        projectId={projectId}
        selectedImageIds={inferenceSelectedImageIds}
        onOpenModelHub={() => onNavigate("models")}
        onOpenAdvancedProviders={() => onNavigate("advanced_providers")}
      />
    ),

    morphometrics: projectId && onOpenMeasurements && (
      <ProjectMorphometricsInspector
        projectId={projectId}
        imageId={focusedImageId}
        onOpenMeasurements={onOpenMeasurements}
      />
    ),

    "training-monitor": projectId && (
      <ProjectTrainingMonitor projectId={projectId} />
    ),

    "review-queue": projectId && onOpenReviewItem && (
      <ProjectReviewInspector
        projectId={projectId}
        selectedQueueId={selectedReviewQueueId}
        onOpenItem={onOpenReviewItem}
      />
    ),

    "video-pose": onVideoSelect && onVideoFrameChange && onVideoTrackChange && (
      <ProjectVideoPoseInspector
        context={videoWorkspaceContext}
        onSelectVideo={onVideoSelect}
        onSeekFrame={onVideoFrameChange}
        onSelectTrack={onVideoTrackChange}
      />
    ),

    "truth-boundary": (
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
    ),

    "preset-guidance": (
      <details
        className="rv-inspector-card"
        aria-label="Workspace preset guidance"
      >
        <summary>{guidance.title}</summary>
        <p>{guidance.description}</p>
      </details>
    ),

    "related-workspaces": (
      <section className="rv-inspector-card" aria-label="Related workspaces">
        <strong>Related workspaces</strong>

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
    ),

    "project-context": (
      <details
        className="rv-inspector-card"
        aria-label="Project inspector context"
      >
        <summary>Project context</summary>

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
        </dl>
      </details>
    ),
  };

  return (
    <div
      className="rv-scientist-inspector"
      data-workspace-view={activeView}
      data-workspace-preset={activePreset}
    >
      {panels.map((panel) => {
        const content =
          panel.pluginRecordId && layout ? (
            <section
              className="rv-inspector-card"
              aria-label={`${panel.label} plugin panel`}
            >
              <strong>{panel.label}</strong>
              <p>{panelPluginStatus(layout, panel)}</p>
              <button
                type="button"
                className="secondary"
                onClick={() => onNavigate("advanced_providers")}
              >
                Open Plugins and providers
              </button>
            </section>
          ) : (
            cards[panel.id]
          );
        if (!content || layout?.hidden.includes(panel.id)) return null;
        return (
          <div key={panel.id} data-contextual-panel={panel.id}>
            {content}
          </div>
        );
      })}
    </div>
  );
}
