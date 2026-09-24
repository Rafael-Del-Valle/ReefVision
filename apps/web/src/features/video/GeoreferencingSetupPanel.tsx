import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Project } from "../../api/client";
import {
  getVideoGeoreferencingReadiness,
  type VideoAssetRecord,
} from "./videoApi";
import {
  getVideoGeoreferencingCalibration,
  setProjectGeoreferencingSurface,
  setVideoGeoreferencingCalibration,
  startVideoGeoreferencing,
  type VideoGeoreferencingCalibrationPayload,
  type VideoGeoreferencingRunResult,
} from "./videoGeoreferencingSetupApi";

interface Props {
  project: Project;
  video: VideoAssetRecord;
}

type Obj = Record<string, unknown>;

function objectValue(value: unknown, label: string): Obj {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  return value as Obj;
}

function numberValue(value: unknown, label: string): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} must be numeric.`);
  return parsed;
}

function integerValue(value: unknown, label: string): number {
  const parsed = numberValue(value, label);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer.`);
  }
  return parsed;
}

function numbers(value: unknown, label: string): number[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array.`);
  return value.map((item, index) => numberValue(item, `${label}[${index}]`));
}

function textValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function parseCalibration(
  rawValue: unknown,
  fileName: string,
  video: VideoAssetRecord,
): VideoGeoreferencingCalibrationPayload {
  const raw = objectValue(rawValue, "Calibration");

  let width: number;
  let height: number;
  let fx: number;
  let fy: number;
  let cx: number;
  let cy: number;
  let distortion: number[];

  if ("image_resolution" in raw && "camera_matrix" in raw) {
    const resolution = objectValue(raw.image_resolution, "image_resolution");
    const matrix = objectValue(raw.camera_matrix, "camera_matrix");
    const d = objectValue(raw.distortion_coefficients, "distortion_coefficients");
    width = integerValue(resolution.width_px, "image_resolution.width_px");
    height = integerValue(resolution.height_px, "image_resolution.height_px");
    fx = numberValue(matrix.fx, "camera_matrix.fx");
    fy = numberValue(matrix.fy, "camera_matrix.fy");
    cx = numberValue(matrix.cx, "camera_matrix.cx");
    cy = numberValue(matrix.cy, "camera_matrix.cy");
    distortion = numbers(
      d.vector_opencv_order,
      "distortion_coefficients.vector_opencv_order",
    );
  } else {
    width = integerValue(raw.width_px, "width_px");
    height = integerValue(raw.height_px, "height_px");
    fx = numberValue(raw.fx_px, "fx_px");
    fy = numberValue(raw.fy_px, "fy_px");
    cx = numberValue(raw.cx_px, "cx_px");
    cy = numberValue(raw.cy_px, "cy_px");
    distortion =
      raw.distortion_coefficients === undefined
        ? []
        : numbers(raw.distortion_coefficients, "distortion_coefficients");
  }

  if (width !== video.width_px || height !== video.height_px) {
    throw new Error(
      `Calibration ${width} x ${height} does not match video ${video.width_px} x ${video.height_px}.`,
    );
  }
  if (![0, 4, 5, 8, 12, 14].includes(distortion.length)) {
    throw new Error("Distortion must contain 0, 4, 5, 8, 12, or 14 OpenCV coefficients.");
  }

  const stem = fileName.replace(/\.[^.]+$/, "") || "camera-calibration";
  return {
    width_px: width,
    height_px: height,
    fx_px: fx,
    fy_px: fy,
    cx_px: cx,
    cy_px: cy,
    distortion_coefficients: distortion,
    digital_zoom_ratio:
      raw.digital_zoom_ratio === undefined
        ? 1
        : numberValue(raw.digital_zoom_ratio, "digital_zoom_ratio"),
    camera_mode: textValue(raw.camera_mode, stem),
    source: fileName,
    evidence: textValue(
      raw.evidence,
      `Imported from ${fileName} for ${video.original_filename}.`,
    ),
  };
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Operation failed.";
}

export function GeoreferencingSetupPanel({ project, video }: Props) {
  const queryClient = useQueryClient();
  const [parsed, setParsed] =
    useState<VideoGeoreferencingCalibrationPayload | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [cameraMode, setCameraMode] = useState("");
  const [calibrationEvidence, setCalibrationEvidence] = useState("");
  const [height, setHeight] = useState(
    String(project.georeference_height_offset_m ?? 0),
  );
  const [heightEvidence, setHeightEvidence] = useState(
    project.georeference_height_evidence ?? "",
  );
  const [result, setResult] = useState<VideoGeoreferencingRunResult | null>(null);

  useEffect(() => {
    setParsed(null);
    setParseError(null);
    setCameraMode("");
    setCalibrationEvidence("");
    setResult(null);
  }, [video.id]);

  const readiness = useQuery({
    queryKey: ["video-georeferencing-readiness", video.id],
    queryFn: ({ signal }) => getVideoGeoreferencingReadiness(video.id, signal),
    refetchInterval: 3000,
  });

  const calibration = useQuery({
    queryKey: ["video-georeferencing-calibration", video.id],
    queryFn: ({ signal }) => getVideoGeoreferencingCalibration(video.id, signal),
  });

  const saveCalibration = useMutation({
    mutationFn: (payload: VideoGeoreferencingCalibrationPayload) =>
      setVideoGeoreferencingCalibration(video.id, payload),
    onSuccess: async () => {
      setResult(null);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["video-georeferencing-calibration", video.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["video-georeferencing-readiness", video.id],
        }),
      ]);
    },
  });

  const saveSurface = useMutation({
    mutationFn: () =>
      setProjectGeoreferencingSurface(
        project.id,
        Number(height),
        heightEvidence.trim(),
      ),
    onSuccess: async () => {
      setResult(null);
      await queryClient.invalidateQueries({
        queryKey: ["video-georeferencing-readiness", video.id],
      });
    },
  });

  const start = useMutation({
    mutationFn: () => startVideoGeoreferencing(video.id),
    onSuccess: setResult,
  });

  const calibrationSummary = useMemo(() => {
    if (!calibration.data) return "No georeferencing calibration saved.";
    return `${calibration.data.camera_mode} · ${calibration.data.width_px} x ${calibration.data.height_px} · revision ${calibration.data.calibration_revision}`;
  }, [calibration.data]);

  async function selectFile(file: File | null) {
    setParsed(null);
    setParseError(null);
    setResult(null);
    if (!file) return;
    try {
      const value = parseCalibration(
        JSON.parse(await file.text()) as unknown,
        file.name,
        video,
      );
      setParsed(value);
      setCameraMode(value.camera_mode);
      setCalibrationEvidence(value.evidence);
    } catch (error) {
      setParseError(message(error));
    }
  }

  return (
    <section className="management-card" data-testid="georeferencing-setup-panel">
      <p className="eyebrow">Georeferencing</p>
      <h3>Calibration & geographic tracking</h3>

      <label>
        Camera calibration JSON
        <input
          type="file"
          accept=".json,application/json"
          onChange={(event) => void selectFile(event.target.files?.[0] ?? null)}
        />
      </label>

      <p className="annotation-helper">
        {calibration.isLoading ? "Checking saved calibration..." : calibrationSummary}
      </p>

      {parseError && <p className="error-copy">{parseError}</p>}

      {parsed && (
        <div className="workspace-guide compact">
          <div>
            <strong>
              Parsed {parsed.width_px} x {parsed.height_px}
            </strong>
            <p className="annotation-helper">
              fx {parsed.fx_px.toFixed(2)} · fy {parsed.fy_px.toFixed(2)}
            </p>
            <label>
              Camera mode
              <input
                value={cameraMode}
                onChange={(event) => setCameraMode(event.target.value)}
              />
            </label>
            <label>
              Calibration evidence / notes
              <textarea
                value={calibrationEvidence}
                onChange={(event) => setCalibrationEvidence(event.target.value)}
              />
            </label>
            <button
              type="button"
              onClick={() =>
                saveCalibration.mutate({
                  ...parsed,
                  camera_mode: cameraMode.trim() || parsed.camera_mode,
                  evidence: calibrationEvidence.trim() || parsed.evidence,
                })
              }
              disabled={saveCalibration.isPending}
            >
              {saveCalibration.isPending ? "Saving..." : "Save calibration"}
            </button>
          </div>
        </div>
      )}

      {saveCalibration.error && (
        <p className="error-copy">{message(saveCalibration.error)}</p>
      )}

      <div className="workspace-guide compact">
        <div>
          <strong>Surface reference</strong>
          <label>
            Height offset above water (m)
            <input
              type="number"
              step="0.001"
              value={height}
              onChange={(event) => setHeight(event.target.value)}
            />
          </label>
          <label>
            Datum evidence
            <textarea
              value={heightEvidence}
              onChange={(event) => setHeightEvidence(event.target.value)}
              placeholder="Example: measured takeoff point 4.945 m above water"
            />
          </label>
          <button
            type="button"
            className="secondary"
            onClick={() => saveSurface.mutate()}
            disabled={
              saveSurface.isPending ||
              !Number.isFinite(Number(height)) ||
              !heightEvidence.trim()
            }
          >
            {saveSurface.isPending ? "Saving..." : "Save surface reference"}
          </button>
        </div>
      </div>

      {saveSurface.error && (
        <p className="error-copy">{message(saveSurface.error)}</p>
      )}

      <div className="workspace-guide compact">
        <div>
          <strong>
            Readiness:{" "}
            {readiness.isLoading
              ? "Checking..."
              : readiness.data?.ready
                ? "Ready"
                : "Not ready"}
          </strong>

          {!readiness.data?.ready && !readiness.isLoading && (
            <p className="annotation-helper">
              Resolve the readiness blockers shown in the managed-video
              georeferencing status above, then start geographic projection.
            </p>
          )}

          <button
            type="button"
            data-testid="start-georeferencing-button"
            onClick={() => start.mutate()}
            disabled={!readiness.data?.ready || start.isPending}
          >
            {start.isPending ? "Georeferencing..." : "Start georeferencing"}
          </button>

          {!readiness.data?.ready && !readiness.isLoading && (
            <p className="annotation-helper">
              The button stays visible and unlocks when the readiness blockers are resolved.
            </p>
          )}

          {start.error && <p className="error-copy">{message(start.error)}</p>}

          {result && (
            <p className="annotation-helper" role="status">
              Georeferenced {result.georeferenced_observation_count} of{" "}
              {result.attempted_count} observations across {result.track_count} tracks.
              {result.failure_count
                ? ` ${result.failure_count} projections failed.`
                : " All projections succeeded."}{" "}
              Use Refresh map below to load the new positions.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
