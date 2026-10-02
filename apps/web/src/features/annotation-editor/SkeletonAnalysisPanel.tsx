import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { EditorMaskAnnotation } from "./types";
import {
  correctSkeletonAnalysis,
  createSkeletonAnalysis,
  exportSkeletonAnalysis,
  getSkeletonReadiness,
  listSkeletonAnalyses,
  reviewSkeletonAnalysis,
  skeletonExportDownloadUrl,
  type SkeletonAnalysisRevision,
  type SkeletonPixel,
} from "./skeletonAnalysisApi";
import type {
  SkeletonEditMode,
  SkeletonOverlayModel,
} from "./SkeletonOverlayLayer";

interface SkeletonAnalysisPanelProps {
  selectedMask: EditorMaskAnnotation | null;
  documentDirty: boolean;
  onOverlayChange: (overlay: SkeletonOverlayModel | null) => void;
}

function pixelKey(point: SkeletonPixel): string {
  return point.x + "," + point.y;
}

function formatLength(
  pixels: number,
  physical: number | null,
  unit: string | null,
): string {
  const pixelText = pixels.toFixed(2) + " px";
  if (physical == null || !unit) return pixelText;
  return pixelText + " | " + physical.toFixed(4) + " " + unit;
}

export function SkeletonAnalysisPanel({
  selectedMask,
  documentDirty,
  onOverlayChange,
}: SkeletonAnalysisPanelProps) {
  const queryClient = useQueryClient();
  const maskId = selectedMask?.id ?? null;
  const enabled =
    selectedMask !== null &&
    selectedMask.persisted &&
    !documentDirty;
  const [spurThreshold, setSpurThreshold] = useState("0");
  const [editMode, setEditMode] = useState<SkeletonEditMode>("view");
  const [addedPixels, setAddedPixels] = useState<SkeletonPixel[]>([]);
  const [removedPixels, setRemovedPixels] = useState<SkeletonPixel[]>([]);
  const [correctionReason, setCorrectionReason] = useState("");
  const [correctionNote, setCorrectionNote] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  const readinessQuery = useQuery({
    queryKey: ["skeleton-readiness", maskId],
    queryFn: ({ signal }) => {
      if (!maskId) throw new Error("No mask is selected");
      return getSkeletonReadiness(maskId, signal);
    },
    enabled,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const historyQuery = useQuery({
    queryKey: ["skeleton-analyses", maskId],
    queryFn: ({ signal }) => {
      if (!maskId) throw new Error("No mask is selected");
      return listSkeletonAnalyses(maskId, signal);
    },
    enabled,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const latest = useMemo<SkeletonAnalysisRevision | null>(() => {
    const history = historyQuery.data ?? [];
    return history.length > 0 ? history[history.length - 1] : null;
  }, [historyQuery.data]);

  useEffect(() => {
    setAddedPixels([]);
    setRemovedPixels([]);
    setEditMode("view");
    setCorrectionReason("");
    setCorrectionNote("");
    setReviewNote("");
  }, [maskId]);

  useEffect(() => {
    if (latest) {
      setSpurThreshold(String(latest.terminal_spur_max_length_pixels));
      setReviewNote(latest.review_note ?? "");
    }
  }, [latest?.id]);

  async function refreshHistory() {
    await queryClient.invalidateQueries({
      queryKey: ["skeleton-analyses", maskId],
    });
    await queryClient.invalidateQueries({
      queryKey: ["skeleton-readiness", maskId],
    });
  }

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!maskId) throw new Error("Select one persisted mask first");
      const threshold = Number(spurThreshold);
      if (!Number.isFinite(threshold) || threshold < 0) {
        throw new Error("Spur threshold must be zero or greater");
      }
      if (!readinessQuery.data?.ready_for_skeletonization) {
        throw new Error("Resolve the mask readiness issues before analysis");
      }
      return createSkeletonAnalysis(maskId, threshold);
    },
    onSuccess: async () => {
      setAddedPixels([]);
      setRemovedPixels([]);
      setEditMode("view");
      await refreshHistory();
    },
  });

  const reviewMutation = useMutation({
    mutationFn: async (
      status: "approved" | "needs_correction" | "rejected",
    ) => {
      if (!latest) throw new Error("No persisted analysis is available");
      return reviewSkeletonAnalysis(
        latest.id,
        status,
        reviewNote.trim() || null,
      );
    },
    onSuccess: refreshHistory,
  });

  const correctionMutation = useMutation({
    mutationFn: async () => {
      if (!latest) throw new Error("No persisted analysis is available");
      if (!correctionReason.trim()) {
        throw new Error("A correction reason is required");
      }
      if (addedPixels.length === 0 && removedPixels.length === 0) {
        throw new Error("Add or remove at least one skeleton pixel");
      }
      return correctSkeletonAnalysis(latest.id, {
        add_pixels: addedPixels,
        remove_pixels: removedPixels,
        reason_code: correctionReason.trim(),
        note: correctionNote.trim() || null,
      });
    },
    onSuccess: async () => {
      setAddedPixels([]);
      setRemovedPixels([]);
      setEditMode("view");
      setCorrectionReason("");
      setCorrectionNote("");
      await refreshHistory();
    },
  });

  const exportMutation = useMutation({
    mutationFn: async () => {
      if (!latest) throw new Error("No persisted analysis is available");
      return exportSkeletonAnalysis(latest.id);
    },
  });

  const handlePixelClick = useCallback(
    (point: SkeletonPixel) => {
      if (!latest || editMode === "view") return;
      const key = pixelKey(point);
      const base = new Set(
        latest.result.final_skeleton_pixels.map(pixelKey),
      );

      if (editMode === "add") {
        setRemovedPixels((current) =>
          current.filter((item) => pixelKey(item) !== key),
        );
        if (base.has(key)) return;
        setAddedPixels((current) =>
          current.some((item) => pixelKey(item) === key)
            ? current.filter((item) => pixelKey(item) !== key)
            : [...current, point],
        );
        return;
      }

      setAddedPixels((current) =>
        current.filter((item) => pixelKey(item) !== key),
      );
      if (!base.has(key)) return;
      setRemovedPixels((current) =>
        current.some((item) => pixelKey(item) === key)
          ? current.filter((item) => pixelKey(item) !== key)
          : [...current, point],
      );
    },
    [editMode, latest],
  );

  useEffect(() => {
    if (!enabled || !latest || latest.stale) {
      onOverlayChange(null);
      return;
    }
    onOverlayChange({
      pixels: latest.result.final_skeleton_pixels,
      addedPixels,
      removedPixels,
      editMode,
      onPixelClick: handlePixelClick,
    });
  }, [
    addedPixels,
    editMode,
    enabled,
    handlePixelClick,
    latest,
    onOverlayChange,
    removedPixels,
  ]);

  useEffect(
    () => () => {
      onOverlayChange(null);
    },
    [onOverlayChange],
  );

  const readiness = readinessQuery.data;
  const result = latest?.result;
  const mutationError =
    createMutation.error ??
    reviewMutation.error ??
    correctionMutation.error ??
    exportMutation.error;

  return (
    <div
      className="annotation-selection-list"
      data-testid="skeleton-analysis-panel"
      aria-live="polite"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Structure</p>
          <h3>Coral skeleton</h3>
        </div>
      </div>

      {!selectedMask && (
        <p className="annotation-helper">
          Select one mask to analyze its branching skeleton.
        </p>
      )}
      {selectedMask && !selectedMask.persisted && (
        <p className="annotation-helper">
          Save the mask before running skeletonization.
        </p>
      )}
      {selectedMask?.persisted && documentDirty && (
        <p className="annotation-helper">
          Waiting for mask edits to save before skeleton analysis.
        </p>
      )}

      {readinessQuery.error instanceof Error && (
        <p className="form-error">{readinessQuery.error.message}</p>
      )}
      {readiness && (
        <>
          <div className="annotation-selection-row">
            <strong>Connectivity gate</strong>
            <span>
              {readiness.component_count} component
              {readiness.component_count === 1 ? "" : "s"} | 8-connected
            </span>
          </div>
          {!readiness.ready_for_skeletonization && (
            <div>
              <p className="form-error">
                Skeletonization blocked: {readiness.blocking_reason}
              </p>
              {readiness.resolution_actions.length > 0 && (
                <p className="annotation-helper">
                  Resolve explicitly by repairing the gap, deleting an
                  artifact, or classifying a separate object. ReefVision will
                  not bridge components automatically.
                </p>
              )}
            </div>
          )}
        </>
      )}

      {enabled && (
        <details open>
          <summary>Automatic analysis</summary>
          <label>
            Terminal spur threshold (px)
            <input
              type="number"
              min="0"
              step="any"
              value={spurThreshold}
              onChange={(event) => setSpurThreshold(event.target.value)}
            />
          </label>
          <p className="annotation-helper">
            Zero disables pruning. Only short endpoint-to-junction terminal
            branches are eligible, and every removal is audited.
          </p>
          <button
            type="button"
            className="secondary"
            disabled={
              !readiness?.ready_for_skeletonization ||
              createMutation.isPending
            }
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending
              ? "Analyzing..."
              : latest
                ? "Regenerate analysis"
                : "Generate analysis"}
          </button>
        </details>
      )}

      {latest && result && (
        <>
          <div className="annotation-selection-row">
            <strong>Revision</strong>
            <span>
              {latest.analysis_revision} | {latest.source_kind}
              {latest.stale ? " | stale" : ""}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Review</strong>
            <span>{latest.review_status}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Raw TLE</strong>
            <span>
              {formatLength(
                result.raw_total_linear_extension_pixels,
                result.raw_total_linear_extension_physical,
                result.physical_unit,
              )}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Auto-pruned TLE</strong>
            <span>
              {formatLength(
                result.pruned_total_linear_extension_pixels,
                result.pruned_total_linear_extension_physical,
                result.physical_unit,
              )}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Final TLE</strong>
            <span>
              {formatLength(
                result.final_total_linear_extension_pixels,
                result.final_total_linear_extension_physical,
                result.physical_unit,
              )}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Final branches</strong>
            <span>{result.final_branch_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Longest path</strong>
            <span>
              {formatLength(
                result.final_longest_path_pixels,
                result.final_longest_path_physical,
                result.physical_unit,
              )}
            </span>
          </div>
          <p className="annotation-helper">
            Final source: {result.final_skeleton_source.replace("_", " ")}.
            Raw and automatically pruned measurements are retained separately.
          </p>
          {result.perspective_corrected && (
            <p className="annotation-helper">
              Physical lengths and branch angles use the accepted reference
              plane homography.
            </p>
          )}

          {latest.stale ? (
            <p className="form-error">
              The mask or calibration changed after this revision. Regenerate
              before review, correction, or export.
            </p>
          ) : (
            <details>
              <summary>Human correction</summary>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className={editMode === "view" ? "secondary" : ""}
                  onClick={() => setEditMode("view")}
                >
                  View
                </button>
                <button
                  type="button"
                  className={editMode === "add" ? "secondary" : ""}
                  onClick={() => setEditMode("add")}
                >
                  Add pixels
                </button>
                <button
                  type="button"
                  className={editMode === "remove" ? "secondary" : ""}
                  onClick={() => setEditMode("remove")}
                >
                  Remove pixels
                </button>
              </div>
              <p className="annotation-helper">
                Pending: +{addedPixels.length} / -{removedPixels.length} pixels.
                Click directly on the image while Add or Remove is active.
              </p>
              <label>
                Correction reason
                <input
                  value={correctionReason}
                  onChange={(event) =>
                    setCorrectionReason(event.target.value)
                  }
                  placeholder="e.g. extend_visible_branch"
                />
              </label>
              <label>
                Correction note
                <textarea
                  value={correctionNote}
                  onChange={(event) => setCorrectionNote(event.target.value)}
                />
              </label>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={
                    correctionMutation.isPending ||
                    (addedPixels.length === 0 &&
                      removedPixels.length === 0)
                  }
                  onClick={() => correctionMutation.mutate()}
                >
                  {correctionMutation.isPending
                    ? "Saving..."
                    : "Save correction"}
                </button>
                <button
                  type="button"
                  className="danger-ghost"
                  disabled={
                    addedPixels.length === 0 &&
                    removedPixels.length === 0
                  }
                  onClick={() => {
                    setAddedPixels([]);
                    setRemovedPixels([]);
                    setEditMode("view");
                  }}
                >
                  Clear draft
                </button>
              </div>
            </details>
          )}

          {!latest.stale && (
            <details>
              <summary>Scientific review</summary>
              <label>
                Review note
                <textarea
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                />
              </label>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={reviewMutation.isPending}
                  onClick={() => reviewMutation.mutate("approved")}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={reviewMutation.isPending}
                  onClick={() => reviewMutation.mutate("needs_correction")}
                >
                  Needs correction
                </button>
                <button
                  type="button"
                  className="danger-ghost"
                  disabled={reviewMutation.isPending}
                  onClick={() => reviewMutation.mutate("rejected")}
                >
                  Reject
                </button>
              </div>
            </details>
          )}

          <details>
            <summary>Scientific export</summary>
            <button
              type="button"
              className="secondary"
              disabled={
                latest.stale ||
                latest.review_status !== "approved" ||
                exportMutation.isPending
              }
              onClick={() => exportMutation.mutate()}
            >
              {exportMutation.isPending
                ? "Building..."
                : "Build verified export"}
            </button>
            {latest.review_status !== "approved" && (
              <p className="annotation-helper">
                Approve the current revision before export.
              </p>
            )}
            {exportMutation.data && (
              <div>
                <p className="annotation-helper">
                  Verified package: {exportMutation.data.archive_name}
                </p>
                <a href={skeletonExportDownloadUrl(latest.id)}>
                  Download skeleton package
                </a>
              </div>
            )}
          </details>
        </>
      )}

      {mutationError instanceof Error && (
        <p className="form-error">{mutationError.message}</p>
      )}
    </div>
  );
}
