import { useState } from "react";

import { MeshArtifactViewer } from "./MeshArtifactViewer";
import { previewLocalMeshFile } from "./workflowGraphApi";

interface LocalMeshPreviewProps {
  projectId: string;
}

/** Standalone local-file preview; saved scientific graphs remain the persistent path. */
export function LocalMeshPreview({ projectId }: LocalMeshPreviewProps) {
  const [file, setFile] = useState<File | null>(null);
  const [scale, setScale] = useState("0.01");
  const [evidence, setEvidence] = useState("");
  const [uncertainty, setUncertainty] = useState("");
  const [artifact, setArtifact] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function preview(): Promise<void> {
    if (!file) return;
    setLoading(true);
    setError(null);
    setArtifact(null);
    try {
      const result = await previewLocalMeshFile(projectId, file, {
        meters_per_unit: Number(scale),
        calibration_method: "ruler",
        calibration_evidence: evidence,
        relative_scale_uncertainty:
          uncertainty.trim() === "" ? null : Number(uncertainty),
      });
      setArtifact(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Mesh preview failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel-card" aria-label="Local 3D mesh preview">
      <h4>Local OBJ / PLY / GLB preview</h4>
      <p className="muted-copy">
        Inspect a bounded mesh before adding it to a saved workflow. This
        preview is not an imported persistent asset, and ruler calibration
        evidence remains unverified until scientist review.
      </p>
      <div className="feature-grid">
        <label>
          Mesh file
          <input
            type="file"
            accept=".obj,.ply,.glb"
            aria-label="Mesh file"
            onChange={(event) => {
              setFile(event.currentTarget.files?.[0] ?? null);
              setArtifact(null);
              setError(null);
            }}
          />
        </label>
        <label>
          Meters per source unit
          <input
            type="number"
            min="0.000000001"
            step="any"
            value={scale}
            onChange={(event) => setScale(event.target.value)}
          />
        </label>
        <label>
          Relative scale uncertainty (0–1, optional)
          <input
            type="number"
            min="0"
            max="1"
            step="any"
            value={uncertainty}
            onChange={(event) => setUncertainty(event.target.value)}
          />
        </label>
        <label>
          Calibration evidence (unverified)
          <input
            type="text"
            value={evidence}
            maxLength={2000}
            onChange={(event) => setEvidence(event.target.value)}
          />
        </label>
      </div>
      <button type="button" disabled={!file || loading} onClick={() => void preview()}>
        {loading ? "Reading mesh..." : "Preview mesh"}
      </button>
      {error && <p role="alert" className="form-error">{error}</p>}
      {artifact && (
        <>
          <p role="status">
            Standalone preview only. Save an executable mesh workflow to persist
            measurement artifacts and provenance.
          </p>
          <MeshArtifactViewer artifact={artifact} />
        </>
      )}
    </section>
  );
}
