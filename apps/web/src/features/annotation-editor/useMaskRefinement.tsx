import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  createMaskRefinement,
  intelligenceRequest,
  refinementMaskUrl,
  reviewMaskRefinement,
  type MaskRefinement,
} from "./annotationIntelligenceApi";
import type { EditorMaskAnnotation } from "./types";
import { PendingMaskEditor } from "./PendingMaskEditor";

interface Options {
  imageId: string;
  variant: string;
  device: string;
  selectedMasks: EditorMaskAnnotation[];
  boxSelectionCount: number;
  dirty: boolean;
  imageWidth: number;
  imageHeight: number;
  refresh: () => Promise<void>;
  message: (message: string) => void;
}

export function useMaskRefinement(options: Options) {
  const {
    imageId,
    variant,
    device,
    selectedMasks,
    boxSelectionCount,
    dirty,
    refresh,
    message,
  } = options;
  const [candidate, setCandidate] = useState<MaskRefinement | null>(null);
  const [revision, setRevision] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [opacity, setOpacity] = useState(0.55);
  const [contentVersion, setContentVersion] = useState(0);
  const currentImage = useRef(imageId);
  currentImage.current = imageId;
  const storageKey = `reefvision-refinement:${imageId}`;
  useEffect(() => {
    setCandidate(null);
    setRevision(0);
    setEditing(false);
    setConfirmed(false);
    let active = true;
    const id = localStorage.getItem(storageKey);
    if (id)
      void intelligenceRequest<MaskRefinement>(
        `/mask-refinements/${encodeURIComponent(id)}`,
        undefined,
        "GET",
      )
        .then((value) => {
          if (
            active &&
            value.image_id === imageId &&
            value.status === "pending"
          )
            setCandidate(value);
        })
        .catch(() => {
          /* A missing/expired preview does not change the saved annotation. */
        });
    return () => {
      active = false;
    };
  }, [imageId, storageKey]);
  const selected =
    selectedMasks.length === 1 && boxSelectionCount === 0
      ? selectedMasks[0]
      : null;
  const reason =
    !selected ||
    !selected.persisted ||
    !["polygon", "raster_mask"].includes(selected.geometry_kind)
      ? "Select exactly one saved polygon or raster mask to refine."
      : dirty
        ? "Save your annotation edits before refining this mask."
        : null;
  const preview = useMutation({
    mutationFn: async () => {
      if (reason || !selected)
        throw new Error(reason ?? "Select a saved mask.");
      return createMaskRefinement(
        selected.id,
        selected.revision ?? 1,
        variant,
        device,
      );
    },
    onSuccess: (value) => {
      localStorage.setItem(
        `reefvision-refinement:${value.image_id}`,
        value.candidate_id,
      );
      if (currentImage.current !== value.image_id) return;
      setCandidate(value);
      setRevision(value.expected_revision);
      setConfirmed(false);
      message(
        "Refined boundary is a pending alternative. Compare it before replacing the saved mask.",
      );
    },
    onError: (error: Error) => message(error.message),
  });
  const review = useMutation({
    mutationFn: (action: "accept" | "undo" | "redo") => {
      if (!candidate) throw new Error("No refinement preview is available.");
      if (dirty)
        throw new Error(
          "Save your annotation edits before changing the refinement.",
        );
      return reviewMaskRefinement(
        candidate,
        action,
        revision || candidate.expected_revision,
        confirmed,
      );
    },
    onSuccess: async (result, action) => {
      setRevision(result.mask_annotation.revision);
      setCandidate((value) =>
        value
          ? { ...value, status: action === "undo" ? "undone" : "accepted" }
          : null,
      );
      localStorage.removeItem(storageKey);
      await refresh();
    },
  });
  const discard = useMutation({
    mutationFn: () =>
      intelligenceRequest(
        `/mask-refinements/${encodeURIComponent(candidate!.candidate_id)}/discard`,
      ),
    onSuccess: () => {
      setCandidate(null);
      setEditing(false);
      localStorage.removeItem(storageKey);
    },
  });
  const busy = preview.isPending || review.isPending || discard.isPending;
  const start = () => {
    if (busy) {
      message("A mask refinement is already processing.");
      return;
    }
    if (candidate?.status === "pending") {
      message(
        "Accept or discard the pending refinement before starting another.",
      );
      return;
    }
    if (reason) {
      message(reason);
      return;
    }
    preview.mutate();
  };
  const pending = candidate?.status === "pending";
  const maskUrl = candidate
    ? `${refinementMaskUrl(candidate.candidate_id)}?edit=${contentVersion}`
    : "";
  const panel =
    candidate && candidate.image_id === imageId ? (
      <section
        className="sam-review-banner"
        aria-label="Mask refinement review"
      >
        <strong>
          {pending
            ? "Compare original and proposed mask — not saved"
            : "Mask refinement history"}
        </strong>
        <p>
          Original: {candidate.old_area_pixels.toFixed(0)} px² · Proposed:{" "}
          {candidate.proposed_area_pixels.toFixed(0)} px² · IoU:{" "}
          {(candidate.iou * 100).toFixed(1)}%
        </p>
        {candidate.warnings.map((warning, index) => (
          <p key={index}>{warning}</p>
        ))}
        {pending && (
          <>
            <p>
              Original boundary remains on the image. The proposed mask is
              magenta.
            </p>
            <label>
              Proposed overlay opacity{" "}
              <input
                aria-label="Proposed overlay opacity"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={opacity}
                onChange={(event) => setOpacity(Number(event.target.value))}
              />
            </label>
            {candidate.requires_confirmation && (
              <label>
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                I reviewed the substantial boundary change
              </label>
            )}
            <button
              type="button"
              disabled={
                busy || dirty || (candidate.requires_confirmation && !confirmed)
              }
              onClick={() => review.mutate("accept")}
            >
              Accept &amp; Replace
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(true)}
            >
              Edit proposed mask
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => discard.mutate()}
            >
              Discard refinement
            </button>
          </>
        )}
        {candidate.status === "accepted" && (
          <button
            type="button"
            disabled={busy || dirty}
            onClick={() => review.mutate("undo")}
          >
            Undo refinement
          </button>
        )}
        {candidate.status === "undone" && (
          <button
            type="button"
            disabled={busy || dirty}
            onClick={() => review.mutate("redo")}
          >
            Redo refinement
          </button>
        )}
        {(review.error || discard.error) && (
          <p role="alert">{(review.error || discard.error)?.message}</p>
        )}
        {pending && editing && (
          <PendingMaskEditor
            imageId={imageId}
            maskUrl={maskUrl}
            width={options.imageWidth}
            height={options.imageHeight}
            onCancel={() => setEditing(false)}
            onSave={async (png) => {
              const edited = await intelligenceRequest<MaskRefinement>(
                `/mask-refinements/${encodeURIComponent(candidate.candidate_id)}/geometry`,
                { mask_png_base64: png },
                "PUT",
              );
              setCandidate(edited);
              setContentVersion((value) => value + 1);
              setConfirmed(false);
              setEditing(false);
            }}
          />
        )}
      </section>
    ) : null;
  const overlay =
    pending && candidate.image_id === imageId ? (
      <>
        <defs>
          <filter id="refinement-magenta">
            <feColorMatrix
              type="matrix"
              values="0 0 0 0 1  0 0 0 0 0.2  0 0 0 0 0.8  1 0 0 0 0"
            />
          </filter>
        </defs>
        <image
          data-testid="refinement-proposal-overlay"
          href={maskUrl}
          x={0}
          y={0}
          width={options.imageWidth}
          height={options.imageHeight}
          opacity={opacity}
          filter="url(#refinement-magenta)"
          pointerEvents="none"
          preserveAspectRatio="none"
        />
      </>
    ) : null;
  return { start, panel, overlay, busy, reason, pending, error: preview.error };
}
