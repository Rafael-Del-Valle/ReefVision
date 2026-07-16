import { useQuery } from "@tanstack/react-query";

import { getMaskMeasurements } from "./maskMeasurementsApi";
import type { EditorMaskAnnotation } from "./types";

interface MaskMeasurementPanelProps {
  selectedMasks: EditorMaskAnnotation[];
  documentDirty: boolean;
}

function formatCoordinate(value: number): string {
  return value.toFixed(2);
}

export function MaskMeasurementPanel({
  selectedMasks,
  documentDirty,
}: MaskMeasurementPanelProps) {
  const selectedMask = selectedMasks.length === 1 ? selectedMasks[0] : null;
  const measurementsQuery = useQuery({
    queryKey: [
      "mask-measurements",
      selectedMask?.id ?? null,
      selectedMask?.revision ?? null,
    ],
    queryFn: ({ signal }) => {
      if (!selectedMask) {
        throw new Error("No mask is selected");
      }
      return getMaskMeasurements(selectedMask.id, signal);
    },
    enabled: selectedMask !== null && selectedMask.persisted && !documentDirty,
    refetchOnWindowFocus: false,
    retry: false,
  });

  return (
    <div
      className="annotation-selection-list"
      data-testid="mask-measurement-panel"
      aria-live="polite"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Measurements</p>
          <h3>Selected mask</h3>
        </div>
      </div>

      {selectedMasks.length === 0 && (
        <p className="annotation-helper">
          Select one persisted polygon or raster mask to view measurements.
        </p>
      )}
      {selectedMasks.length > 1 && (
        <p className="annotation-helper">
          Select a single mask to view its measurements.
        </p>
      )}
      {selectedMask && !selectedMask.persisted && (
        <p className="annotation-helper">
          Save this mask before calculating measurements.
        </p>
      )}
      {selectedMask && selectedMask.persisted && documentDirty && (
        <p className="annotation-helper">
          Waiting for the current mask edits to save before refreshing
          measurements.
        </p>
      )}
      {measurementsQuery.isPending && measurementsQuery.isFetching && (
        <p className="annotation-helper">Loading measurements...</p>
      )}
      {measurementsQuery.error instanceof Error && (
        <p className="form-error">{measurementsQuery.error.message}</p>
      )}
      {measurementsQuery.data && (
        <>
          <div className="annotation-selection-row">
            <strong>Area</strong>
            <span>
              {measurementsQuery.data.area_pixels.toLocaleString()} px²
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Perimeter</strong>
            <span>{measurementsQuery.data.perimeter_pixels.toFixed(2)} px</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Centroid</strong>
            <span>
              ({formatCoordinate(measurementsQuery.data.centroid_x)},{" "}
              {formatCoordinate(measurementsQuery.data.centroid_y)}) px
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Bounds</strong>
            <span>
              x {formatCoordinate(measurementsQuery.data.x_min)}–
              {formatCoordinate(measurementsQuery.data.x_max)}, y{" "}
              {formatCoordinate(measurementsQuery.data.y_min)}–
              {formatCoordinate(measurementsQuery.data.y_max)} px
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Contained boxes</strong>
            <span>{measurementsQuery.data.contained_box_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Density</strong>
            <span>
              {measurementsQuery.data.contained_box_density_per_1000_pixels.toFixed(
                4,
              )}{" "}
              boxes per 1,000 mask pixels
            </span>
          </div>
        </>
      )}
    </div>
  );
}
