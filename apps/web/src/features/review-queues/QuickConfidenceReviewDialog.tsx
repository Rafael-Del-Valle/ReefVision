import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  acceptPrediction,
  getAnnotationSession,
  getPredictions,
  imageDisplayUrl,
  imageThumbnailUrl,
  rejectPrediction,
  type PredictionProposal,
  type ReviewQueueItem,
} from "../../api/client";
import "./quickConfidenceReview.css";

interface QuickConfidenceReviewDialogProps {
  item: Pick<
    ReviewQueueItem,
    "image_id" | "project_id" | "review_queue_id" | "review_state"
  >;
  reviewBelowConfidence: number | null;
  position: number;
  total: number;
  showRankedPosition?: boolean;
  hasPreviousImage?: boolean;
  hasNextImage?: boolean;
  onClose: () => void;
  onPreviousImage: () => void;
  onNextImage: () => void;
  onOpenFullEditor?: () => void;
  onMarkComplete?: () => void;
  onReviewSaved?: () => void;
  markingComplete?: boolean;
}

function eligibleProposals(
  proposals: PredictionProposal[],
  threshold: number | null,
): PredictionProposal[] {
  return proposals.filter(
    (proposal) =>
      proposal.review_status === "pending" &&
      (threshold === null || proposal.confidence <= threshold),
  );
}

export function QuickConfidenceReviewDialog({
  item,
  reviewBelowConfidence,
  position,
  total,
  showRankedPosition = true,
  hasPreviousImage,
  hasNextImage,
  onClose,
  onPreviousImage,
  onNextImage,
  onOpenFullEditor,
  onMarkComplete,
  onReviewSaved,
  markingComplete = false,
}: QuickConfidenceReviewDialogProps) {
  const queryClient = useQueryClient();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(
    null,
  );
  const [previewSource, setPreviewSource] = useState<
    "full" | "thumbnail" | "failed"
  >("full");
  const [previewRetry, setPreviewRetry] = useState(0);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [classOverrides, setClassOverrides] = useState<Record<string, string>>(
    {},
  );

  useEffect(() => {
    setSelectedProposalId(null);
    setClassOverrides({});
    setPreviewSource("full");
    setPreviewRetry(0);
    setPreviewLoaded(false);
  }, [item.image_id]);

  useEffect(() => {
    const previousFocus = document.activeElement;
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
      } else if (event.key === "Tab" && dialogRef.current) {
        const focusable = Array.from(
          dialogRef.current.querySelectorAll<HTMLElement>(
            "button:not(:disabled), input:not(:disabled), select:not(:disabled), " +
              "textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
          ),
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);

  const imageQuery = useQuery({
    queryKey: ["annotations", item.image_id, "quick-review"],
    queryFn: ({ signal }) => getAnnotationSession(item.image_id, signal),
  });
  const predictionsQuery = useQuery({
    queryKey: ["predictions", item.image_id, "quick-review"],
    queryFn: ({ signal }) =>
      getPredictions(item.image_id, { reviewStatus: "pending" }, signal),
  });
  const proposals = useMemo(
    () =>
      eligibleProposals(
        predictionsQuery.data?.items ?? [],
        reviewBelowConfidence,
      ),
    [predictionsQuery.data?.items, reviewBelowConfidence],
  );
  const selectedProposal =
    proposals.find((proposal) => proposal.id === selectedProposalId) ??
    proposals[0] ??
    null;
  const currentIndex = selectedProposal
    ? proposals.findIndex((proposal) => proposal.id === selectedProposal.id)
    : -1;
  const classes = imageQuery.data?.label_classes ?? [];
  const chosenClassId = selectedProposal
    ? (classOverrides[selectedProposal.id] ??
      selectedProposal.label_class_id ??
      "")
    : "";
  const chosenClass = classes.find((item) => item.id === chosenClassId);
  const canCreateMissingClass =
    selectedProposal?.label_class_id == null &&
    chosenClassId === "" &&
    Boolean(selectedProposal?.predicted_label.trim()) &&
    selectedProposal?.predicted_label !== "SAM 2 mask" &&
    !selectedProposal?.model_display_name.startsWith("ReefVision managed") &&
    (selectedProposal?.predicted_label.length ?? 0) <= 200;
  const image = imageQuery.data?.image;

  const review = useMutation({
    mutationFn: async (action: "accept" | "reject") => {
      if (!selectedProposal) throw new Error("Select a pending prediction");
      if (action === "reject") return rejectPrediction(selectedProposal.id);
      if (canCreateMissingClass) {
        return acceptPrediction(selectedProposal.id, {});
      }
      if (!chosenClass || !chosenClass.is_active) {
        throw new Error(
          "Select an active project class before accepting this prediction.",
        );
      }
      return acceptPrediction(selectedProposal.id, {
        label_class_id: chosenClass.id,
      });
    },
    onSuccess: async () => {
      setSelectedProposalId(null);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["predictions", item.image_id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["annotations", item.image_id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["review_queue_items", item.review_queue_id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["images", item.project_id],
        }),
      ]);
      onReviewSaved?.();
    },
  });

  return createPortal(
    <div className="rv-quick-review-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="rv-quick-review-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rv-quick-review-heading"
      >
        <header className="rv-quick-review-header">
          <div>
            <p className="eyebrow">ReefVision 1.0.1 · Quick checks</p>
            <h3 id="rv-quick-review-heading">Confidence-based review</h3>
            <p>
              {showRankedPosition
                ? `Ranked image ${position} of ${total}`
                : "Current image"}{" "}
              · {item.review_state}
              {reviewBelowConfidence !== null
                ? ` · review at or below ${Math.round(reviewBelowConfidence * 100)}%`
                : " · all pending confidences"}
            </p>
          </div>
          <button
            type="button"
            className="secondary"
            aria-label="Close quick review"
            ref={closeButtonRef}
            onClick={onClose}
          >
            Close
          </button>
        </header>

        <div className="rv-quick-review-content">
          <div className="rv-quick-review-image-column">
            {imageQuery.isPending ? (
              <p>Loading image preview…</p>
            ) : imageQuery.error ? (
              <p role="alert">{imageQuery.error.message}</p>
            ) : image ? (
              <div className="rv-quick-review-image-stage">
                {previewSource === "failed" ? (
                  <div role="alert">
                    Image preview failed to load. Annotations are unchanged.
                    <button
                      type="button"
                      onClick={() => {
                        setPreviewLoaded(false);
                        setPreviewRetry((attempt) => attempt + 1);
                        setPreviewSource("full");
                      }}
                    >
                      Retry image preview
                    </button>
                  </div>
                ) : (
                  <>
                    {!previewLoaded && (
                      <p role="status">Loading image preview…</p>
                    )}
                    <img
                    key={`${item.image_id}-${previewSource}-${previewRetry}`}
                    src={
                      previewSource === "thumbnail"
                        ? imageThumbnailUrl(item.image_id)
                        : `${imageDisplayUrl(item.image_id)}${
                            previewRetry ? `?review_retry=${previewRetry}` : ""
                          }`
                    }
                    alt={image.original_filename}
                    onLoad={() => setPreviewLoaded(true)}
                    onError={() => {
                      setPreviewLoaded(false);
                      setPreviewSource(
                        previewSource === "full" && image.thumbnail_path
                          ? "thumbnail"
                          : "failed",
                      );
                    }}
                  />
                  </>
                )}
                {selectedProposal && previewLoaded && (
                  <svg
                    className="rv-quick-review-overlay"
                    viewBox={`0 0 ${image.width_px} ${image.height_px}`}
                    preserveAspectRatio="none"
                    aria-label="Selected prediction bounds"
                  >
                    <rect
                      x={selectedProposal.x_min}
                      y={selectedProposal.y_min}
                      width={Math.max(
                        0,
                        selectedProposal.x_max - selectedProposal.x_min,
                      )}
                      height={Math.max(
                        0,
                        selectedProposal.y_max - selectedProposal.y_min,
                      )}
                      fill="none"
                      stroke="#fbc02d"
                      strokeWidth={Math.max(2, image.width_px / 400)}
                    />
                    {selectedProposal.geometry_kind === "polygon_mask" &&
                      selectedProposal.polygon_json && (
                        <polygon
                          points={selectedProposal.polygon_json
                            .map(([x, y]) => `${x},${y}`)
                            .join(" ")}
                          fill="#fbc02d"
                          fillOpacity={0.15}
                          stroke="#fbc02d"
                          strokeWidth={Math.max(2, image.width_px / 500)}
                        />
                      )}
                  </svg>
                )}
              </div>
            ) : (
              <p>No image metadata available.</p>
            )}
            <p className="annotation-helper">
              The overlay previews prediction geometry. For detailed edits,
              overlapping objects, or raster masks, use the full annotation
              editor.
            </p>
            {onOpenFullEditor && (
              <button type="button" onClick={onOpenFullEditor}>
                Open full annotation editor
              </button>
            )}
          </div>
          <div className="rv-quick-review-decision-column">
            <h4>Pending predictions</h4>
            {predictionsQuery.isPending && <p>Loading predictions…</p>}
            {predictionsQuery.error && (
              <p role="alert">{predictionsQuery.error.message}</p>
            )}
            {!predictionsQuery.isPending && !predictionsQuery.error && (
              <p>
                <strong>{proposals.length}</strong> matching prediction
                {proposals.length === 1 ? "" : "s"} awaiting a decision
              </p>
            )}
            {selectedProposal ? (
              <>
                <div className="rv-quick-review-proposal-nav">
                  <button
                    type="button"
                    className="secondary"
                    disabled={currentIndex <= 0 || review.isPending}
                    onClick={() =>
                      setSelectedProposalId(proposals[currentIndex - 1].id)
                    }
                  >
                    Previous prediction
                  </button>
                  <span>
                    {currentIndex + 1} / {proposals.length}
                  </span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={
                      currentIndex >= proposals.length - 1 || review.isPending
                    }
                    onClick={() =>
                      setSelectedProposalId(proposals[currentIndex + 1].id)
                    }
                  >
                    Next prediction
                  </button>
                </div>
                <dl className="rv-quick-review-metadata">
                  <dt>Model label</dt>
                  <dd>{selectedProposal.predicted_label}</dd>
                  <dt>Raw model confidence</dt>
                  <dd>
                    <strong>
                      {(selectedProposal.confidence * 100).toFixed(1)}%
                    </strong>
                    <small> Not a calibrated correctness probability</small>
                  </dd>
                  <dt>Source model</dt>
                  <dd>{selectedProposal.model_display_name}</dd>
                </dl>
                <label>
                  Class for accepted annotation
                  <select
                    value={chosenClassId}
                    onChange={(event) =>
                      setClassOverrides((previous) => ({
                        ...previous,
                        [selectedProposal.id]: event.target.value,
                      }))
                    }
                  >
                    <option value="">Choose a class</option>
                    {classes
                      .filter((item) => item.is_active)
                      .map((labelClass) => (
                        <option key={labelClass.id} value={labelClass.id}>
                          {labelClass.name}
                        </option>
                      ))}
                  </select>
                </label>
                {canCreateMissingClass && (
                  <p className="annotation-helper">
                    Accepting will create the missing project class “
                    {selectedProposal.predicted_label}” from the model label.
                  </p>
                )}
                <div className="rv-quick-review-decision-actions">
                  <button
                    type="button"
                    disabled={
                      (!canCreateMissingClass &&
                        (!chosenClass || !chosenClass.is_active)) ||
                      review.isPending
                    }
                    onClick={() => review.mutate("accept")}
                  >
                    {canCreateMissingClass
                      ? "Accept and create class"
                      : "Accept prediction"}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={review.isPending}
                    onClick={() => review.mutate("reject")}
                  >
                    Reject prediction
                  </button>
                </div>
              </>
            ) : (
              !predictionsQuery.isPending &&
              !predictionsQuery.error && (
                <p className="rv-quick-review-empty">
                  No pending predictions meet this confidence rule for the
                  selected image.
                </p>
              )
            )}
            {review.error && (
              <p className="form-error" role="alert">
                {review.error.message}
              </p>
            )}
            <p className="annotation-helper">
              Accept and reject are explicit researcher decisions.
              High-confidence predictions excluded from this view remain
              unverified.
            </p>
          </div>
        </div>

        <footer className="rv-quick-review-footer">
          <div className="rv-quick-review-proposal-nav">
            <button
              type="button"
              className="secondary"
              disabled={
                !(hasPreviousImage ?? position > 1) || review.isPending
              }
              onClick={onPreviousImage}
            >
              Previous image
            </button>
            <button
              type="button"
              className="secondary"
              disabled={
                !(hasNextImage ?? position < total) || review.isPending
              }
              onClick={onNextImage}
            >
              Next image
            </button>
          </div>
          {onMarkComplete && (
            <button
              type="button"
              disabled={
                proposals.length > 0 ||
                predictionsQuery.isPending ||
                Boolean(predictionsQuery.error) ||
                markingComplete
              }
              onClick={onMarkComplete}
            >
              {markingComplete ? "Saving…" : "Mark image review complete"}
            </button>
          )}
        </footer>
      </section>
    </div>,
    document.body,
  );
}
