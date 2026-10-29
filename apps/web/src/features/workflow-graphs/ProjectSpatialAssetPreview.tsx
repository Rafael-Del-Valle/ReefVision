import { useEffect, useRef, useState } from "react";

import { MeshArtifactViewer } from "./MeshArtifactViewer";
import { PointCloudArtifactViewer } from "./PointCloudArtifactViewer";
import {
  importProjectSpatialAsset,
  listProjectSpatialAssets,
  previewProjectSpatialAsset,
} from "./workflowGraphApi";
import type {
  MeshPreviewCalibration,
  SpatialSourceAsset,
} from "./workflowGraphApi";

interface ProjectSpatialAssetPreviewProps {
  projectId: string;
}

/** Project changes must never reuse another project's asset selection or preview. */
export function ProjectSpatialAssetPreview({
  projectId,
}: ProjectSpatialAssetPreviewProps) {
  return (
    <ProjectSpatialAssetPreviewSession key={projectId} projectId={projectId} />
  );
}

function ProjectSpatialAssetPreviewSession({
  projectId,
}: ProjectSpatialAssetPreviewProps) {
  const [assets, setAssets] = useState<SpatialSourceAsset[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [kind, setKind] = useState<"mesh" | "point_cloud">("mesh");
  const [calibrationMethod, setCalibrationMethod] =
    useState<MeshPreviewCalibration["calibration_method"]>("other");
  const [file, setFile] = useState<File | null>(null);
  const [scale, setScale] = useState("0.01");
  const [uncertainty, setUncertainty] = useState("");
  const [evidence, setEvidence] = useState("");
  const [artifact, setArtifact] = useState<Record<string, unknown> | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [busy, setBusy] = useState(false);
  const [imported, setImported] = useState(false);
  const requestVersion = useRef(0);
  const listVersion = useRef(0);
  const selected = assets.find((asset) => asset.id === selectedId);

  useEffect(() => {
    const controller = new AbortController();
    const version = ++listVersion.current;
    void listProjectSpatialAssets(projectId, controller.signal)
      .then((records) => {
        if (version === listVersion.current && !controller.signal.aborted) {
          setAssets((previous) => {
            const existingIds = new Set(previous.map((item) => item.id));
            return [
              ...previous,
              ...records.filter(
                (record) =>
                  record.project_id === projectId &&
                  !existingIds.has(record.id),
              ),
            ];
          });
        }
      })
      .catch((reason: unknown) => {
        if (version === listVersion.current && !controller.signal.aborted) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Unable to list 3D assets.",
          );
        }
      })
      .finally(() => {
        if (version === listVersion.current && !controller.signal.aborted) {
          setLoadingList(false);
        }
      });
    return () => {
      controller.abort();
      listVersion.current += 1;
    };
  }, [projectId]);

  function invalidatePreview(): void {
    requestVersion.current += 1;
    setArtifact(null);
    setError(null);
    setBusy(false);
  }

  async function importFile(): Promise<void> {
    if (!file) return;
    const version = ++requestVersion.current;
    setBusy(true);
    setError(null);
    setArtifact(null);
    try {
      const record = await importProjectSpatialAsset(projectId, file);
      if (version !== requestVersion.current) return;
      setAssets((previous) =>
        previous.some((item) => item.id === record.id)
          ? previous
          : [...previous, record],
      );
      setSelectedId(record.id);
      setKind("mesh");
      setFile(null);
      setImported(true);
    } catch (reason) {
      if (version === requestVersion.current) {
        setError(
          reason instanceof Error ? reason.message : "3D import failed.",
        );
      }
    } finally {
      if (version === requestVersion.current) setBusy(false);
    }
  }

  async function preview(): Promise<void> {
    if (!selected) return;
    const version = ++requestVersion.current;
    setBusy(true);
    setError(null);
    setArtifact(null);
    try {
      const result = await previewProjectSpatialAsset(
        projectId,
        selected,
        kind,
        {
          meters_per_unit: Number(scale),
          calibration_method: calibrationMethod,
          calibration_evidence: evidence,
          relative_scale_uncertainty:
            uncertainty.trim() === "" ? null : Number(uncertainty),
        },
      );
      if (version === requestVersion.current) setArtifact(result);
    } catch (reason) {
      if (version === requestVersion.current) {
        setError(
          reason instanceof Error ? reason.message : "3D preview failed.",
        );
      }
    } finally {
      if (version === requestVersion.current) setBusy(false);
    }
  }

  return (
    <section className="panel-card" aria-label="Project 3D source assets">
      <h4>Project-owned 3D originals</h4>
      <p className="muted-copy">
        Import immutable OBJ, PLY, or GLB source bytes (8 MiB maximum) or select
        an existing project original. Previews are provisional: matching SHA-256
        verifies source integrity, not calibration, biological identity, or
        review. Save an executable mesh or point-cloud workflow with the asset
        ID and digest to persist scientific artifacts.
      </p>
      <div className="feature-grid">
        <label>
          Import 3D original
          <input
            aria-label="Import 3D original"
            type="file"
            accept=".obj,.ply,.glb"
            onChange={(event) =>
              setFile(event.currentTarget.files?.[0] ?? null)
            }
          />
        </label>
        <button
          type="button"
          disabled={!file || busy}
          onClick={() => void importFile()}
        >
          {busy ? "Working..." : "Import original"}
        </button>
        <label>
          Project 3D source
          <select
            aria-label="Project 3D source"
            value={selectedId}
            onChange={(event) => {
              const id = event.target.value;
              setSelectedId(id);
              setKind("mesh");
              invalidatePreview();
            }}
          >
            <option value="">Select imported source</option>
            {assets.map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.original_filename} ({asset.source_format.toUpperCase()};{" "}
                {asset.id.slice(0, 8)})
              </option>
            ))}
          </select>
        </label>
        <label>
          Preview geometry
          <select
            aria-label="Preview geometry"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as "mesh" | "point_cloud");
              invalidatePreview();
            }}
          >
            <option value="mesh">Triangle mesh</option>
            {selected?.source_format === "ply" && (
              <option value="point_cloud">PLY point cloud</option>
            )}
          </select>
        </label>
        <label>
          Calibration method (unverified)
          <select
            aria-label="Calibration method (unverified)"
            value={calibrationMethod}
            onChange={(event) => {
              setCalibrationMethod(
                event.target
                  .value as MeshPreviewCalibration["calibration_method"],
              );
              invalidatePreview();
            }}
          >
            <option value="other">Other / unknown</option>
            <option value="ruler">Ruler</option>
            <option value="photogrammetry_control">
              Photogrammetry control
            </option>
            <option value="instrument">Instrument</option>
          </select>
        </label>
        <label>
          Meters per source unit (unverified)
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
          Relative scale uncertainty (0–1, optional)
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
          Calibration evidence (unverified)
          <input
            type="text"
            maxLength={2000}
            value={evidence}
            onChange={(event) => {
              setEvidence(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
      </div>
      {loadingList && <p role="status">Loading project originals...</p>}
      {imported && (
        <p role="status">
          Source imported; human scientific review remains required.
        </p>
      )}
      {selected && (
        <p className="muted-copy">
          Source SHA-256: <code>{selected.sha256}</code>. Source and calibration
          remain unreviewed; mesh edges and point chords are not anatomical
          branch lengths.
        </p>
      )}
      <button
        type="button"
        disabled={!selected || busy}
        onClick={() => void preview()}
      >
        {busy ? "Working..." : "Preview imported source"}
      </button>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {artifact && kind === "mesh" && (
        <MeshArtifactViewer artifact={artifact} />
      )}
      {artifact && kind === "point_cloud" && (
        <PointCloudArtifactViewer artifact={artifact} />
      )}
    </section>
  );
}
