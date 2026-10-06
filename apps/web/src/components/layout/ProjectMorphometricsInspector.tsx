import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { CalibrationAssistant } from "../../features/annotation-editor/CalibrationAssistant";
import {
  getMeasurementCalibration,
  measurementExportUrl,
  type MeasurementCalibration,
} from "../../features/annotation-editor/maskMeasurementsApi";

export function ProjectMorphometricsInspector({
  projectId,
  imageId,
  onOpenMeasurements,
}: {
  projectId: string;
  imageId: string | null;
  onOpenMeasurements: (imageId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [showScaleAssistant, setShowScaleAssistant] = useState(false);

  const calibrationQuery = useQuery({
    queryKey: ["measurement-calibration", imageId],
    queryFn: ({ signal }) => {
      if (!imageId) {
        throw new Error("No focused image is available");
      }
      return getMeasurementCalibration(imageId, signal);
    },
    enabled: imageId !== null,
    retry: false,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    setShowScaleAssistant(false);
  }, [imageId]);

  async function acceptCalibration(
    calibration: MeasurementCalibration,
  ): Promise<void> {
    queryClient.setQueryData(
      ["measurement-calibration", calibration.image_id],
      calibration,
    );

    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["mask-measurements"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["skeleton-analyses"],
      }),
    ]);

    setShowScaleAssistant(false);
  }

  const calibration = calibrationQuery.data ?? null;

  return (
    <section
      className="rv-inspector-card rv-morphometrics-inspector"
      aria-label="Morphometrics and calibration controls"
    >
      <div className="rv-inspector-card-heading">
        <strong>Morphometrics</strong>
        <span>
          {imageId
            ? calibration
              ? "Calibrated"
              : "Image selected"
            : "No image focused"}
        </span>
      </div>

      {!imageId ? (
        <div className="rv-inspector-empty-control">
          <strong>Focus an image first</strong>
          <p>
            Select an image in the Gallery filmstrip before reviewing scale
            calibration or opening mask measurements.
          </p>
        </div>
      ) : (
        <>
          <div className="rv-morphometrics-status">
            <span>Focused image</span>
            <strong>{imageId}</strong>
          </div>

          {calibrationQuery.isPending && (
            <p className="annotation-helper">Checking image calibration…</p>
          )}

          {calibrationQuery.error && (
            <p className="form-error" role="alert">
              Calibration status could not be loaded:{" "}
              {calibrationQuery.error.message}
            </p>
          )}

          {!calibrationQuery.isPending &&
            !calibrationQuery.error &&
            !calibration && (
              <div className="rv-morphometrics-status uncalibrated">
                <span>Physical scale</span>
                <strong>Not calibrated</strong>
                <small>
                  Pixel measurements remain valid, but physical-unit results
                  require a reviewed calibration.
                </small>
              </div>
            )}

          {calibration && (
            <div
              className="rv-morphometrics-calibration"
              aria-label="Accepted image calibration"
            >
              <div>
                <span>Distance per pixel</span>
                <strong>
                  {calibration.distance_per_pixel} {calibration.unit}/px
                </strong>
              </div>

              <div>
                <span>Source</span>
                <strong>{calibration.source.replaceAll("_", " ")}</strong>
              </div>

              {calibration.confidence != null && (
                <div>
                  <span>Confidence</span>
                  <strong>{Math.round(calibration.confidence * 100)}%</strong>
                </div>
              )}

              {calibration.reference_length != null &&
                calibration.reference_pixel_length != null && (
                  <div>
                    <span>Reviewed reference</span>
                    <strong>
                      {calibration.reference_length} {calibration.unit} /{" "}
                      {calibration.reference_pixel_length.toFixed(2)} px
                    </strong>
                  </div>
                )}
            </div>
          )}

          <button
            type="button"
            className="secondary"
            aria-expanded={showScaleAssistant}
            onClick={() => setShowScaleAssistant((current) => !current)}
          >
            {showScaleAssistant
              ? "Close Scale Assistant"
              : "Open Scale Assistant"}
          </button>

          {showScaleAssistant && (
            <div className="rv-morphometrics-scale-assistant">
              <CalibrationAssistant
                projectId={projectId}
                imageId={imageId}
                defaultUnit={calibration?.unit ?? "mm"}
                onApplied={acceptCalibration}
              />
            </div>
          )}

          <button type="button" onClick={() => onOpenMeasurements(imageId)}>
            Open masks & measurements
          </button>
        </>
      )}

      <div className="rv-morphometrics-results">
        <strong>Project measurement results</strong>
        <p>
          Mask area, perimeter, density, centerline/TLE, surface models, and
          skeleton-derived measurements remain owned by the canonical annotation
          workflow.
        </p>

        <div className="rv-morphometrics-export-links">
          <a href={measurementExportUrl(projectId, "csv")}>
            Export measurements CSV
          </a>
          <a href={measurementExportUrl(projectId, "numpy")}>
            Export measurements NumPy
          </a>
        </div>
      </div>

      <div className="rv-inference-boundary">
        <strong>Researcher confirmation required</strong>
        <p>
          Scale-bar geometry and OCR are calibration evidence only. ReefVision
          does not silently infer physical units or apply an unreviewed scale.
        </p>
      </div>
    </section>
  );
}
