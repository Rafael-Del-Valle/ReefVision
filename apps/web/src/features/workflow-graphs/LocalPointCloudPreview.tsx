import { useRef, useState } from "react";

import { PointCloudArtifactViewer } from "./PointCloudArtifactViewer";
import { previewLocalPointCloudFile } from "./workflowGraphApi";

interface LocalPointCloudPreviewProps {
  projectId: string;
}

/** Isolate unverified geometry and in-flight requests when the project changes. */
export function LocalPointCloudPreview({
  projectId,
}: LocalPointCloudPreviewProps) {
  return (
    <LocalPointCloudPreviewSession key={projectId} projectId={projectId} />
  );
}

function LocalPointCloudPreviewSession({
  projectId,
}: LocalPointCloudPreviewProps) {
  const [file, setFile] = useState<File | null>(null);
  const [scale, setScale] = useState("0.01");
  const [evidence, setEvidence] = useState("");
  const [coordinateFrame, setCoordinateFrame] = useState("");
  const [uncertainty, setUncertainty] = useState("");
  const [firstPointIndex, setFirstPointIndex] = useState("");
  const [secondPointIndex, setSecondPointIndex] = useState("");
  const [pinChordEndpoints, setPinChordEndpoints] = useState(false);
  const [artifact, setArtifact] = useState<Record<string, unknown> | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestVersion = useRef(0);

  function invalidatePreview(): void {
    requestVersion.current += 1;
    setArtifact(null);
    setError(null);
    setLoading(false);
  }

  async function preview(): Promise<void> {
    if (!file) return;
    const version = ++requestVersion.current;
    setLoading(true);
    setError(null);
    setArtifact(null);
    try {
      const hasFirst = firstPointIndex.trim() !== "";
      const hasSecond = secondPointIndex.trim() !== "";
      if (hasFirst !== hasSecond) {
        throw new Error("Provide both source point indices for a chord.");
      }
      const pointIndexPairs: Array<[number, number]> | undefined = hasFirst
        ? [[Number(firstPointIndex), Number(secondPointIndex)]]
        : undefined;
      const calibration = {
        meters_per_unit: Number(scale),
        calibration_method: "ruler" as const,
        calibration_evidence: evidence,
        coordinate_frame_id: coordinateFrame || undefined,
        relative_scale_uncertainty:
          uncertainty.trim() === "" ? null : Number(uncertainty),
      };
      const result = pinChordEndpoints
        ? await previewLocalPointCloudFile(
            projectId,
            file,
            calibration,
            pointIndexPairs,
            true,
          )
        : await previewLocalPointCloudFile(
            projectId,
            file,
            calibration,
            pointIndexPairs,
          );
      if (version === requestVersion.current) setArtifact(result);
    } catch (reason) {
      if (version === requestVersion.current) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Point-cloud preview failed.",
        );
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }

  return (
    <section className="panel-card" aria-label="Local 3D point-cloud preview">
      <h4>Local ASCII PLY point-cloud preview</h4>
      <p className="muted-copy">
        Inspect vertex-only ASCII PLY 1.0 XYZ points (optional raw RGB). This is
        a temporary, unverified preview, not a saved asset or biological
        surface, branch-length, or condition measurement.
      </p>
      <div className="feature-grid">
        <label>
          Point-cloud file
          <input
            type="file"
            accept=".ply"
            aria-label="Point-cloud file"
            onChange={(event) => {
              setFile(event.currentTarget.files?.[0] ?? null);
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Meters per point-cloud unit
          <input
            type="number"
            min="0.000000001"
            step="any"
            value={scale}
            onChange={(event) => {
              setScale(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Point-cloud relative scale uncertainty (0–1, optional)
          <input
            type="number"
            min="0"
            max="1"
            step="any"
            value={uncertainty}
            onChange={(event) => {
              setUncertainty(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Point-cloud calibration evidence (unverified)
          <input
            type="text"
            value={evidence}
            maxLength={2000}
            onChange={(event) => {
              setEvidence(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Point-cloud source coordinate frame ID (unverified, optional)
          <input
            type="text"
            maxLength={128}
            value={coordinateFrame}
            onChange={(event) => {
              setCoordinateFrame(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Chord start source point index (optional)
          <input
            aria-label="Chord start source point index"
            type="number"
            min="0"
            max="1999"
            step="1"
            value={firstPointIndex}
            onChange={(event) => {
              setFirstPointIndex(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Chord end source point index (optional)
          <input
            aria-label="Chord end source point index"
            type="number"
            min="0"
            max="1999"
            step="1"
            value={secondPointIndex}
            onChange={(event) => {
              setSecondPointIndex(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={pinChordEndpoints}
            onChange={(event) => {
              setPinChordEndpoints(event.target.checked);
              invalidatePreview();
            }}
          />
          Keep selected chord endpoints visible in the sampled point preview
        </label>
      </div>
      <p className="muted-copy">
        Optional point-pair chord is straight-line distance between original
        zero-based source indices, not anatomical branch length. The backend
        checks indices against the full imported cloud. Endpoint preservation
        changes display sampling only, not biological measurement or review.
        A source-frame label does not establish verified spatial registration.
      </p>
      <button
        type="button"
        disabled={!file || loading}
        onClick={() => void preview()}
      >
        {loading ? "Reading points..." : "Preview point cloud"}
      </button>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {artifact && (
        <>
          <p role="status">
            Standalone preview only. Save and execute a typed point-cloud
            workflow to persist measurement artifacts and provenance.
          </p>
          <PointCloudArtifactViewer artifact={artifact} />
        </>
      )}
    </section>
  );
}
