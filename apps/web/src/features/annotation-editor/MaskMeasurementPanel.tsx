import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { CalibrationAssistant } from "./CalibrationAssistant";
import {
  clearMeasurementCalibration,
  getMaskMeasurementProfile,
  getMaskMeasurements,
  getMeasurementCalibration,
  measurementExportUrl,
  updateMaskMeasurementProfile,
  updateMeasurementCalibration,
  type MeasurementCalibration,
  type SurfaceModelKind,
} from "./maskMeasurementsApi";
import type { EditorMaskAnnotation } from "./types";

export interface MeasurementLabelClass {
  id: string;
  name: string;
  scientific_name: string | null;
  state_name: string | null;
}

interface MaskMeasurementPanelProps {
  projectId: string;
  imageId: string;
  labelClasses: MeasurementLabelClass[];
  selectedMasks: EditorMaskAnnotation[];
  documentDirty: boolean;
  onRevisionCommitted: () => Promise<void>;
}

function formatCoordinate(value: number): string {
  return value.toFixed(2);
}

function optionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function MaskMeasurementPanel({
  projectId,
  imageId,
  labelClasses,
  selectedMasks,
  documentDirty,
  onRevisionCommitted,
}: MaskMeasurementPanelProps) {
  const queryClient = useQueryClient();
  const selectedMask = selectedMasks.length === 1 ? selectedMasks[0] : null;
  const [classFilter, setClassFilter] = useState("");
  const [speciesFilter, setSpeciesFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [distancePerPixel, setDistancePerPixel] = useState("");
  const [unit, setUnit] = useState("mm");
  const [defaultDepth, setDefaultDepth] = useState("");
  const [surfaceModel, setSurfaceModel] = useState<SurfaceModelKind>("none");
  const [depthValue, setDepthValue] = useState("");
  const [diameterValue, setDiameterValue] = useState("");
  const [profileNotes, setProfileNotes] = useState("");

  const calibrationQuery = useQuery({
    queryKey: ["measurement-calibration", imageId],
    queryFn: ({ signal }) => getMeasurementCalibration(imageId, signal),
    refetchOnWindowFocus: false,
    retry: false,
  });

  const profileQuery = useQuery({
    queryKey: ["mask-measurement-profile", selectedMask?.id ?? null],
    queryFn: ({ signal }) => {
      if (!selectedMask) throw new Error("No mask is selected");
      return getMaskMeasurementProfile(selectedMask.id, signal);
    },
    enabled: selectedMask !== null && selectedMask.persisted && !documentDirty,
    refetchOnWindowFocus: false,
    retry: false,
  });

  useEffect(() => {
    const calibration = calibrationQuery.data;
    setDistancePerPixel(
      calibration ? String(calibration.distance_per_pixel) : "",
    );
    setUnit(calibration?.unit ?? "mm");
    setDefaultDepth(
      calibration?.default_depth == null
        ? ""
        : String(calibration.default_depth),
    );
  }, [calibrationQuery.data]);

  useEffect(() => {
    const profile = profileQuery.data;
    setSurfaceModel(profile?.surface_model ?? "none");
    setDepthValue(
      profile?.depth_value == null ? "" : String(profile.depth_value),
    );
    setDiameterValue(
      profile?.diameter_value == null ? "" : String(profile.diameter_value),
    );
    setProfileNotes(profile?.notes ?? "");
  }, [profileQuery.data]);

  const filters = useMemo(
    () => ({
      label_class_ids: classFilter ? [classFilter] : [],
      scientific_names: speciesFilter ? [speciesFilter] : [],
      state_names: stateFilter ? [stateFilter] : [],
    }),
    [classFilter, speciesFilter, stateFilter],
  );

  const measurementsQuery = useQuery({
    queryKey: [
      "mask-measurements",
      selectedMask?.id ?? null,
      selectedMask?.revision ?? null,
      filters,
      calibrationQuery.dataUpdatedAt,
      profileQuery.dataUpdatedAt,
    ],
    queryFn: ({ signal }) => {
      if (!selectedMask) throw new Error("No mask is selected");
      return getMaskMeasurements(selectedMask.id, filters, signal);
    },
    enabled: selectedMask !== null && selectedMask.persisted && !documentDirty,
    refetchOnWindowFocus: false,
    retry: false,
  });

  async function acceptCalibration(calibration: MeasurementCalibration) {
    queryClient.setQueryData(
      ["measurement-calibration", imageId],
      calibration,
    );
    await queryClient.invalidateQueries({ queryKey: ["mask-measurements"] });
  }

  const calibrationMutation = useMutation({
    mutationFn: async () => {
      const scale = optionalNumber(distancePerPixel);
      if (scale === null || scale <= 0) {
        throw new Error("Distance per pixel must be greater than zero");
      }
      if (!unit.trim()) throw new Error("A physical unit is required");
      return updateMeasurementCalibration(imageId, {
        distance_per_pixel: scale,
        unit: unit.trim(),
        source: "manual",
        default_depth: optionalNumber(defaultDepth),
      });
    },
    onSuccess: acceptCalibration,
  });

  const clearCalibrationMutation = useMutation({
    mutationFn: () => clearMeasurementCalibration(imageId),
    onSuccess: async () => {
      queryClient.setQueryData(["measurement-calibration", imageId], null);
      await queryClient.invalidateQueries({ queryKey: ["mask-measurements"] });
    },
  });

  const profileMutation = useMutation({
    mutationFn: async () => {
      if (!selectedMask || !profileQuery.data) {
        throw new Error("Measurement profile is not ready");
      }
      return updateMaskMeasurementProfile(selectedMask.id, {
        base_revision: profileQuery.data.revision,
        centerline_points: profileQuery.data.centerline_points,
        surface_model: surfaceModel,
        depth_value: optionalNumber(depthValue),
        diameter_value: optionalNumber(diameterValue),
        notes: profileNotes.trim() || null,
      });
    },
    onSuccess: async (profile) => {
      queryClient.setQueryData(
        ["mask-measurement-profile", profile.mask_annotation_id],
        profile,
      );
      await queryClient.invalidateQueries({ queryKey: ["mask-measurements"] });
      await onRevisionCommitted();
    },
  });

  const speciesOptions = useMemo(
    () =>
      Array.from(
        new Set(
          labelClasses
            .map((labelClass) => labelClass.scientific_name)
            .filter((value): value is string => Boolean(value)),
        ),
      ).sort(),
    [labelClasses],
  );
  const stateOptions = useMemo(
    () =>
      Array.from(
        new Set(
          labelClasses
            .map((labelClass) => labelClass.state_name)
            .filter((value): value is string => Boolean(value)),
        ),
      ).sort(),
    [labelClasses],
  );
  const measurement = measurementsQuery.data;

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

      <details>
        <summary>Image calibration</summary>
        <details>
          <summary>Scale Assistant</summary>
          <CalibrationAssistant
            projectId={projectId}
            imageId={imageId}
            defaultUnit={unit}
            onApplied={acceptCalibration}
          />
        </details>
        <p className="annotation-helper">
          Manual calibration remains available as the fallback and for known
          image scales that do not use a visible reference.
        </p>
        <label>
          Distance per pixel
          <input
            type="number"
            min="0"
            step="any"
            value={distancePerPixel}
            onChange={(event) => setDistancePerPixel(event.target.value)}
            placeholder="0.01"
          />
        </label>
        <label>
          Unit
          <input
            value={unit}
            onChange={(event) => setUnit(event.target.value)}
            placeholder="mm"
          />
        </label>
        <label>
          Default depth or thickness
          <input
            type="number"
            min="0"
            step="any"
            value={defaultDepth}
            onChange={(event) => setDefaultDepth(event.target.value)}
          />
        </label>
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            className="secondary"
            onClick={() => calibrationMutation.mutate()}
            disabled={calibrationMutation.isPending}
          >
            {calibrationMutation.isPending ? "Saving..." : "Save calibration"}
          </button>
          <button
            type="button"
            className="danger-ghost"
            onClick={() => clearCalibrationMutation.mutate()}
            disabled={
              calibrationQuery.data == null ||
              clearCalibrationMutation.isPending
            }
          >
            Clear
          </button>
        </div>
        {(calibrationMutation.error ?? clearCalibrationMutation.error) instanceof
          Error && (
          <p className="form-error">
            {(calibrationMutation.error ?? clearCalibrationMutation.error)?.message}
          </p>
        )}
        {calibrationQuery.data && (
          <ul className="system-details">
            <li>Source: {calibrationQuery.data.source}</li>
            {calibrationQuery.data.confidence != null && (
              <li>
                Calibration confidence:{" "}
                {Math.round(calibrationQuery.data.confidence * 100)}%
              </li>
            )}
            {calibrationQuery.data.profile_name && (
              <li>Profile: {calibrationQuery.data.profile_name}</li>
            )}
            {calibrationQuery.data.perspective_homography && (
              <li>
                Perspective correction is available on the accepted reference
                plane.
              </li>
            )}
          </ul>
        )}
      </details>

      <details>
        <summary>Polyp density filters</summary>
        <label>
          Class
          <select
            value={classFilter}
            onChange={(event) => setClassFilter(event.target.value)}
          >
            <option value="">All classes</option>
            {labelClasses.map((labelClass) => (
              <option key={labelClass.id} value={labelClass.id}>
                {labelClass.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Species
          <select
            value={speciesFilter}
            onChange={(event) => setSpeciesFilter(event.target.value)}
          >
            <option value="">All species</option>
            {speciesOptions.map((species) => (
              <option key={species} value={species}>
                {species}
              </option>
            ))}
          </select>
        </label>
        <label>
          State
          <select
            value={stateFilter}
            onChange={(event) => setStateFilter(event.target.value)}
          >
            <option value="">All states</option>
            {stateOptions.map((state) => (
              <option key={state} value={state}>
                {state}
              </option>
            ))}
          </select>
        </label>
      </details>

      {profileQuery.data && (
        <details>
          <summary>Centerline and surface model</summary>
          <p className="annotation-helper">
            Use the Centerline tool above the image to add or drag
            source-coordinate points. Double-click a point to remove it.
          </p>
          <div className="annotation-selection-row">
            <strong>Centerline</strong>
            <span>
              {profileQuery.data.centerline_points.length} points |{" "}
              {profileQuery.data.centerline_length_pixels.toFixed(2)} px
            </span>
          </div>
          <label>
            Surface model
            <select
              value={surfaceModel}
              onChange={(event) =>
                setSurfaceModel(event.target.value as SurfaceModelKind)
              }
            >
              <option value="none">No 3D estimate</option>
              <option value="extruded">Closed planar extrusion</option>
              <option value="cylindrical_centerline">
                Equivalent centerline cylinder
              </option>
            </select>
          </label>
          <label>
            Depth override
            <input
              type="number"
              min="0"
              step="any"
              value={depthValue}
              onChange={(event) => setDepthValue(event.target.value)}
            />
          </label>
          <label>
            Diameter override
            <input
              type="number"
              min="0"
              step="any"
              value={diameterValue}
              onChange={(event) => setDiameterValue(event.target.value)}
            />
          </label>
          <label>
            Notes
            <textarea
              value={profileNotes}
              onChange={(event) => setProfileNotes(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="secondary"
            onClick={() => profileMutation.mutate()}
            disabled={profileMutation.isPending}
          >
            {profileMutation.isPending ? "Saving..." : "Save model settings"}
          </button>
          {profileMutation.error instanceof Error && (
            <p className="form-error">{profileMutation.error.message}</p>
          )}
        </details>
      )}

      {measurementsQuery.isPending && measurementsQuery.isFetching && (
        <p className="annotation-helper">Loading measurements...</p>
      )}
      {measurementsQuery.error instanceof Error && (
        <p className="form-error">{measurementsQuery.error.message}</p>
      )}
      {measurement && (
        <>
          <div className="annotation-selection-row">
            <strong>Area</strong>
            <span>
              {measurement.area_pixels.toLocaleString()} px²
              {measurement.area_physical != null && measurement.physical_unit
                ? ` | ${measurement.area_physical.toFixed(4)} ${measurement.physical_unit}²`
                : ""}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Perimeter</strong>
            <span>
              {measurement.perimeter_pixels.toFixed(2)} px
              {measurement.perimeter_physical != null && measurement.physical_unit
                ? ` | ${measurement.perimeter_physical.toFixed(4)} ${measurement.physical_unit}`
                : ""}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Centroid</strong>
            <span>
              ({formatCoordinate(measurement.centroid_x)},{" "}
              {formatCoordinate(measurement.centroid_y)}) px
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Bounds</strong>
            <span>
              x {formatCoordinate(measurement.x_min)}–
              {formatCoordinate(measurement.x_max)}, y{" "}
              {formatCoordinate(measurement.y_min)}–
              {formatCoordinate(measurement.y_max)} px
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Contained boxes</strong>
            <span>{measurement.contained_box_count}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Density</strong>
            <span>
              {measurement.contained_box_density_per_1000_pixels.toFixed(4)}{" "}
              boxes per 1,000 mask pixels
              {measurement.contained_box_density_per_square_unit != null &&
              measurement.physical_unit
                ? ` | ${measurement.contained_box_density_per_square_unit.toFixed(4)} per ${measurement.physical_unit}²`
                : ""}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Total linear extension</strong>
            <span>
              {measurement.total_linear_extension_pixels.toFixed(2)} px
              {measurement.total_linear_extension_physical != null &&
              measurement.physical_unit
                ? ` | ${measurement.total_linear_extension_physical.toFixed(4)} ${measurement.physical_unit}`
                : ""}
            </span>
          </div>
          {measurement.perspective_corrected && (
            <p className="annotation-helper">
              Physical polygon/centerline measurements are perspective-corrected
              on the accepted calibration plane.
            </p>
          )}
          {measurement.surface_area_model !== "none" && (
            <div className="annotation-selection-row">
              <strong>Surface-area estimate</strong>
              <span>
                {measurement.surface_area_physical != null && measurement.physical_unit
                  ? `${measurement.surface_area_physical.toFixed(4)} ${measurement.physical_unit}²`
                  : "Unavailable"}
              </span>
            </div>
          )}
          {measurement.surface_area_assumptions.length > 0 && (
            <ul className="system-details">
              {measurement.surface_area_assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          )}
        </>
      )}

      <details>
        <summary>Project exports</summary>
        <div className="annotation-editor-inline-actions">
          <a href={measurementExportUrl(projectId, "csv")}>Download CSV</a>
          <a href={measurementExportUrl(projectId, "numpy")}>
            Download NumPy bundle
          </a>
        </div>
      </details>
    </div>
  );
}
