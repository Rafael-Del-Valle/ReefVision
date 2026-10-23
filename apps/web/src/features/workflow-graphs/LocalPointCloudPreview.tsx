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
  const [uncertainty, setUncertainty] = useState("");
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
      const result = await previewLocalPointCloudFile(projectId, file, {
        meters_per_unit: Number(scale),
        calibration_method: "ruler",
        calibration_evidence: evidence,
        relative_scale_uncertainty:
          uncertainty.trim() === "" ? null : Number(uncertainty),
      });
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
        Inspect vertex-only ASCII PLY 1.0 XYZ points (optional raw RGB).
        This is a temporary, unverified preview, not a saved asset or
        biological surface, branch-length, or condition measurement.
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
      </div>
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
