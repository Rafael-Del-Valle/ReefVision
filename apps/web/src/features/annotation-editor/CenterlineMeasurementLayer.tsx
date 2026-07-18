import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useMemo,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  getMaskMeasurementProfile,
  updateMaskMeasurementProfile,
  type MeasurementPoint,
} from "./maskMeasurementsApi";
import type { EditorMaskAnnotation } from "./types";

interface CenterlineMeasurementLayerProps {
  width: number;
  height: number;
  selectedMask: EditorMaskAnnotation | null;
  documentDirty: boolean;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  onRevisionCommitted: () => Promise<void>;
}

function sourcePoint(
  event: ReactPointerEvent<SVGSVGElement>,
  width: number,
  height: number,
): MeasurementPoint {
  const bounds = event.currentTarget.getBoundingClientRect();
  return {
    x: Math.max(
      0,
      Math.min(width, ((event.clientX - bounds.left) / bounds.width) * width),
    ),
    y: Math.max(
      0,
      Math.min(height, ((event.clientY - bounds.top) / bounds.height) * height),
    ),
  };
}

export function CenterlineMeasurementLayer({
  width,
  height,
  selectedMask,
  documentDirty,
  editing,
  onEditingChange,
  onRevisionCommitted,
}: CenterlineMeasurementLayerProps) {
  const queryClient = useQueryClient();
  const [draftPoints, setDraftPoints] = useState<MeasurementPoint[]>([]);
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const maskId = selectedMask?.id ?? null;
  const profileQuery = useQuery({
    queryKey: ["mask-measurement-profile", maskId],
    queryFn: ({ signal }) => {
      if (!maskId) throw new Error("No mask selected");
      return getMaskMeasurementProfile(maskId, signal);
    },
    enabled:
      maskId !== null &&
      Boolean(selectedMask?.persisted) &&
      !documentDirty,
    refetchOnWindowFocus: false,
    retry: false,
  });

  useEffect(() => {
    setDraftPoints(profileQuery.data?.centerline_points ?? []);
  }, [maskId, profileQuery.data?.centerline_points]);

  useEffect(() => {
    if (!selectedMask || documentDirty || !selectedMask.persisted) {
      onEditingChange(false);
    }
  }, [documentDirty, onEditingChange, selectedMask]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!maskId || !profileQuery.data) {
        throw new Error("Measurement profile is not ready");
      }
      return updateMaskMeasurementProfile(maskId, {
        base_revision: profileQuery.data.revision,
        centerline_points: draftPoints,
        surface_model: profileQuery.data.surface_model,
        depth_value: profileQuery.data.depth_value,
        diameter_value: profileQuery.data.diameter_value,
        notes: profileQuery.data.notes,
      });
    },
    onSuccess: async (profile) => {
      queryClient.setQueryData(
        ["mask-measurement-profile", profile.mask_annotation_id],
        profile,
      );
      await queryClient.invalidateQueries({ queryKey: ["mask-measurements"] });
      onEditingChange(false);
      await onRevisionCommitted();
    },
  });

  const polylinePoints = useMemo(
    () => draftPoints.map((point) => `${point.x},${point.y}`).join(" "),
    [draftPoints],
  );
  const canEdit =
    selectedMask?.persisted === true &&
    !documentDirty &&
    profileQuery.data !== undefined;

  function updateDraggedPoint(event: ReactPointerEvent<SVGSVGElement>) {
    if (!editing || draggedIndex === null) return;
    const point = sourcePoint(event, width, height);
    setDraftPoints((current) =>
      current.map((existing, index) =>
        index === draggedIndex ? point : existing,
      ),
    );
  }

  return (
    <>
      <svg
        data-testid="centerline-measurement-layer"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          pointerEvents: editing ? "auto" : "none",
          cursor: editing ? "crosshair" : "default",
          zIndex: 6,
        }}
        onPointerMove={updateDraggedPoint}
        onPointerUp={() => setDraggedIndex(null)}
        onPointerCancel={() => setDraggedIndex(null)}
        onClick={(event) => {
          if (!editing || event.target !== event.currentTarget) return;
          setDraftPoints((current) => [
            ...current,
            sourcePoint(event, width, height),
          ]);
        }}
      >
        {draftPoints.length > 1 && (
          <polyline
            points={polylinePoints}
            fill="none"
            stroke="#ffd43b"
            strokeWidth={Math.max(width, height) / 350}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            pointerEvents="none"
          />
        )}
        {draftPoints.map((point, index) => (
          <circle
            key={`${index}-${point.x}-${point.y}`}
            cx={point.x}
            cy={point.y}
            r={Math.max(width, height) / 120}
            fill="#ffd43b"
            stroke="#1f2937"
            strokeWidth={Math.max(width, height) / 700}
            vectorEffect="non-scaling-stroke"
            pointerEvents={editing ? "all" : "none"}
            onPointerDown={(event) => {
              if (!editing) return;
              event.stopPropagation();
              event.currentTarget.setPointerCapture(event.pointerId);
              setDraggedIndex(index);
            }}
            onDoubleClick={(event) => {
              if (!editing) return;
              event.stopPropagation();
              setDraftPoints((current) =>
                current.filter((_point, pointIndex) => pointIndex !== index),
              );
            }}
          />
        ))}
      </svg>

      {editing && canEdit && (
        <div
          style={{
            position: "absolute",
            top: "0.75rem",
            left: "0.75rem",
            zIndex: 7,
            display: "flex",
            gap: "0.4rem",
            padding: "0.5rem",
            borderRadius: "0.5rem",
            background: "rgba(15, 23, 42, 0.88)",
          }}
        >
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={
              saveMutation.isPending ||
              (draftPoints.length > 0 && draftPoints.length < 2)
            }
          >
            {saveMutation.isPending ? "Saving..." : "Save centerline"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => setDraftPoints([])}
          >
            Clear
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setDraftPoints(profileQuery.data?.centerline_points ?? []);
              onEditingChange(false);
            }}
          >
            Cancel
          </button>
          {saveMutation.error instanceof Error && (
            <span className="form-error">{saveMutation.error.message}</span>
          )}
        </div>
      )}
    </>
  );
}
