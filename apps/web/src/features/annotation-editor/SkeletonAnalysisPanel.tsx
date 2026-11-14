import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { EditorMaskAnnotation } from "./types";
import {
  correctSkeletonAnalysis,
  createSkeletonAnalysis,
  exportSkeletonAnalysis,
  getSkeletonReadiness,
  listSkeletonAnalyses,
  previewConnectedBranch,
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

// Rasterize the straight segments between user-chosen waypoints in source
// pixels. The backend validates the exact attachment and connected topology.
function rasterizeBranch(waypoints: SkeletonPixel[]): SkeletonPixel[] {
  if (waypoints.length === 0) return [];
  const pixels = [waypoints[0]];
  for (let index = 1; index < waypoints.length; index++) {
    let { x, y } = waypoints[index - 1];
    const end = waypoints[index];
    const dx = Math.abs(end.x - x);
    const dy = -Math.abs(end.y - y);
    const stepX = Math.sign(end.x - x);
    const stepY = Math.sign(end.y - y);
    let error = dx + dy;
    while (x !== end.x || y !== end.y) {
      const doubled = 2 * error;
      if (doubled >= dy) {
        error += dy;
        x += stepX;
      }
      if (doubled <= dx) {
        error += dx;
        y += stepY;
      }
      pixels.push({ x, y });
    }
  }
  return pixels;
}

interface BranchDraft {
  waypoints: SkeletonPixel[];
  count: number;
}

const emptyBranch: BranchDraft = { waypoints: [], count: 0 };

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
    selectedMask !== null && selectedMask.persisted && !documentDirty;
  const [spurThreshold, setSpurThreshold] = useState("0");
  const [editMode, setEditMode] = useState<SkeletonEditMode>("view");
  const [overlaySource, setOverlaySource] = useState<
    "raw" | "pruned" | "final"
  >("final");
  const [addedPixels, setAddedPixels] = useState<SkeletonPixel[]>([]);
  const [removedPixels, setRemovedPixels] = useState<SkeletonPixel[]>([]);
  const [correctionReason, setCorrectionReason] = useState("");
  const [correctionNote, setCorrectionNote] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [branchDraft, setBranchDraft] = useState(emptyBranch);

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
  const branchSource =
    enabled && latest?.is_latest_revision && !latest.stale ? latest : null;
  const branchPixels = useMemo(
    () => rasterizeBranch(branchDraft.waypoints.slice(0, branchDraft.count)),
    [branchDraft],
  );

  useEffect(() => {
    setAddedPixels([]);
    setRemovedPixels([]);
    setEditMode("view");
    setOverlaySource("final");
    setCorrectionReason("");
    setCorrectionNote("");
    setReviewNote("");
  }, [maskId]);

  useEffect(() => {
    setBranchDraft(emptyBranch);
    setEditMode((mode) => (mode === "branch" ? "view" : mode));
  }, [branchSource?.id, branchSource?.result_sha256]);

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
      setOverlaySource("final");
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
      setOverlaySource("final");
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

  const branchMutation = useMutation({
    mutationFn: async ({
      source,
      points,
    }: {
      source: SkeletonAnalysisRevision;
      points: SkeletonPixel[];
    }) => {
      const preview = await previewConnectedBranch(
        source.id,
        globalThis.crypto.randomUUID(),
        points,
      );
      if (
        preview.base_analysis_id !== source.id ||
        preview.base_result_sha256 !== source.result_sha256 ||
        preview.mask_annotation_id !== source.mask_annotation_id ||
        preview.image_id !== source.image_id ||
        !preview.edges.some((edge) => edge.id === preview.added_edge_id)
      ) {
        throw new Error(
          "The branch preview does not match this skeleton revision.",
        );
      }
      return preview;
    },
  });
  const requestSource = branchMutation.variables?.source;
  const currentBranchRequest =
    branchSource !== null &&
    requestSource?.id === branchSource.id &&
    requestSource.result_sha256 === branchSource.result_sha256 &&
    branchMutation.variables?.points === branchPixels;
  const branchPreview = currentBranchRequest ? branchMutation.data : undefined;
  const branchCalibration = branchPreview?.calibration;
  const branchPending = currentBranchRequest && branchMutation.isPending;
  const drawingBranch = editMode === "branch";

  function drawBranch() {
    setOverlaySource("final");
    setEditMode("branch");
  }

  const handlePixelClick = useCallback(
    (point: SkeletonPixel) => {
      if (!latest || editMode === "view") return;
      if (editMode === "branch") {
        setBranchDraft((draft) => {
          const previous = draft.waypoints[draft.count - 1];
          if (previous?.x === point.x && previous.y === point.y) return draft;
          return {
            waypoints: [...draft.waypoints.slice(0, draft.count), point],
            count: draft.count + 1,
          };
        });
        return;
      }
      const key = pixelKey(point);
      const base = new Set(latest.result.final_skeleton_pixels.map(pixelKey));

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
    const pixels =
      overlaySource === "raw"
        ? latest.result.raw_skeleton_pixels
        : overlaySource === "pruned"
          ? latest.result.pruned_skeleton_pixels
          : latest.result.final_skeleton_pixels;
    const nodes =
      overlaySource === "raw"
        ? latest.result.graph_nodes
        : overlaySource === "pruned"
          ? latest.result.pruned_graph_nodes
          : latest.result.final_graph_nodes;
    const finalOverlay = overlaySource === "final";
    const showBranch =
      finalOverlay && editMode === "branch" && branchSource !== null;
    onOverlayChange({
      pixels,
      nodes: showBranch && branchPreview ? branchPreview.nodes : nodes,
      addedPixels: finalOverlay && !showBranch ? addedPixels : [],
      removedPixels: finalOverlay && !showBranch ? removedPixels : [],
      branchPixels: showBranch
        ? (branchPreview?.edges.find(
            (edge) => edge.id === branchPreview.added_edge_id,
          )?.pixels ?? branchPixels)
        : [],
      editMode: finalOverlay ? editMode : "view",
      onPixelClick: handlePixelClick,
    });
  }, [
    addedPixels,
    branchPixels,
    branchPreview,
    branchSource,
    editMode,
    enabled,
    handlePixelClick,
    latest,
    onOverlayChange,
    overlaySource,
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
                  Resolve explicitly by repairing the gap, deleting an artifact,
                  or classifying a separate object. ReefVision will not bridge
                  components automatically.
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
              !readiness?.ready_for_skeletonization || createMutation.isPending
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
            Final source: {result.final_skeleton_source.replace("_", " ")}. Raw
            and automatically pruned measurements are retained separately.
          </p>
          <div>
            <p className="annotation-helper">Canvas overlay</p>
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className={overlaySource === "raw" ? "secondary" : ""}
                onClick={() => {
                  setEditMode("view");
                  setOverlaySource("raw");
                }}
              >
                Raw
              </button>
              <button
                type="button"
                className={overlaySource === "pruned" ? "secondary" : ""}
                onClick={() => {
                  setEditMode("view");
                  setOverlaySource("pruned");
                }}
              >
                Auto-pruned
              </button>
              <button
                type="button"
                className={overlaySource === "final" ? "secondary" : ""}
                onClick={() => setOverlaySource("final")}
              >
                Final
              </button>
            </div>
          </div>
          {result.perspective_corrected && (
            <p className="annotation-helper">
              Physical lengths and branch angles use the accepted reference
              plane homography.
            </p>
          )}

          {branchSource && (
            <details open>
              <summary>Connected branch preview</summary>
              <p className="annotation-helper">
                Start on an existing skeleton pixel and click along the visible
                branch to place waypoints. Blue pixels show the draft path.
              </p>
              <div className="annotation-editor-inline-actions">
                <button
                  type="button"
                  className={drawingBranch ? "secondary" : ""}
                  aria-pressed={drawingBranch}
                  onClick={drawBranch}
                >
                  Draw branch
                </button>
                <button
                  type="button"
                  disabled={branchDraft.count === 0}
                  onClick={() => {
                    drawBranch();
                    setBranchDraft((draft) => ({
                      ...draft,
                      count: draft.count - 1,
                    }));
                  }}
                >
                  Undo waypoint
                </button>
                <button
                  type="button"
                  disabled={branchDraft.count === branchDraft.waypoints.length}
                  onClick={() => {
                    drawBranch();
                    setBranchDraft((draft) => ({
                      ...draft,
                      count: draft.count + 1,
                    }));
                  }}
                >
                  Redo waypoint
                </button>
                <button
                  type="button"
                  className="danger-ghost"
                  disabled={
                    branchDraft.waypoints.length === 0 && !drawingBranch
                  }
                  onClick={() => {
                    setBranchDraft(emptyBranch);
                    if (drawingBranch) setEditMode("view");
                  }}
                >
                  Discard branch draft
                </button>
              </div>
              <button
                type="button"
                className="secondary"
                disabled={branchPixels.length < 2 || branchPending}
                onClick={() => {
                  drawBranch();
                  branchMutation.mutate({
                    source: branchSource,
                    points: branchPixels,
                  });
                }}
              >
                {branchPending ? "Checking branch…" : "Preview branch"}
              </button>
              {drawingBranch &&
                currentBranchRequest &&
                branchMutation.error && (
                  <p className="form-error" role="alert">
                    {branchMutation.error.message}
                  </p>
                )}
              {drawingBranch && branchPreview && (
                <>
                  <p className="annotation-helper">
                    <strong>Scientist review required</strong>
                    {" · Unsaved 2D proposal."}
                  </p>
                  {branchCalibration && (
                    <p className="annotation-helper">
                      {branchCalibration.method === "reference_plane_homography"
                        ? "Reference-plane calibration"
                        : "Image-scale calibration"}{" "}
                      ({branchCalibration.source})
                    </p>
                  )}
                  <div className="annotation-selection-row">
                    <strong>Added segment length</strong>
                    <span>
                      {formatLength(
                        branchPreview.added_length_pixels,
                        branchCalibration?.added_length ?? null,
                        branchCalibration?.unit ?? null,
                      )}
                    </span>
                  </div>
                  <div className="annotation-selection-row">
                    <strong>Proposed total linear extension</strong>
                    <span>
                      {formatLength(
                        branchPreview.proposed_total_length_pixels,
                        branchCalibration?.proposed_total_length ?? null,
                        branchCalibration?.unit ?? null,
                      )}
                    </span>
                  </div>
                  {branchPreview.superseded_edge_ids.length === 1 && (
                    <p className="annotation-helper">
                      1 existing segment splits into{" "}
                      {branchPreview.replacement_edge_ids.length} at the new
                      junction.
                    </p>
                  )}
                  <details>
                    <summary>Proposed segment lengths</summary>
                    {branchPreview.edges.map((edge) => (
                      <div className="annotation-selection-row" key={edge.id}>
                        <strong>
                          {edge.id === branchPreview.added_edge_id
                            ? "New segment"
                            : edge.id}
                        </strong>
                        <span>
                          {formatLength(
                            edge.node_to_node_length_pixels,
                            edge.length_physical ?? null,
                            branchCalibration?.unit ?? null,
                          )}
                        </span>
                      </div>
                    ))}
                  </details>
                </>
              )}
            </details>
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
                  onClick={() => {
                    setOverlaySource("final");
                    setEditMode("add");
                  }}
                >
                  Add pixels
                </button>
                <button
                  type="button"
                  className={editMode === "remove" ? "secondary" : ""}
                  onClick={() => {
                    setOverlaySource("final");
                    setEditMode("remove");
                  }}
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
                  onChange={(event) => setCorrectionReason(event.target.value)}
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
                    drawingBranch ||
                    correctionMutation.isPending ||
                    (addedPixels.length === 0 && removedPixels.length === 0)
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
                    addedPixels.length === 0 && removedPixels.length === 0
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
              {drawingBranch && (
                <p className="annotation-helper">
                  Discard the branch draft or switch to View to review the saved
                  skeleton.
                </p>
              )}
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
                  disabled={drawingBranch || reviewMutation.isPending}
                  onClick={() => reviewMutation.mutate("approved")}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={drawingBranch || reviewMutation.isPending}
                  onClick={() => reviewMutation.mutate("needs_correction")}
                >
                  Needs correction
                </button>
                <button
                  type="button"
                  className="danger-ghost"
                  disabled={drawingBranch || reviewMutation.isPending}
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
                drawingBranch ||
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
            {!drawingBranch && exportMutation.data && (
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
