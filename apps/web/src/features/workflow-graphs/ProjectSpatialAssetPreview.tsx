import { useEffect, useRef, useState } from "react";

import { MeshArtifactViewer } from "./MeshArtifactViewer";
import { PointCloudArtifactViewer } from "./PointCloudArtifactViewer";
import { ProjectSpatialComparison } from "./ProjectSpatialComparison";
import {
  createSpatialAssetMetadataRevision,
  importProjectSpatialAsset,
  listSpatialAssetMetadataRevisions,
  listProjectSpatialAssets,
  previewProjectSpatialAsset,
} from "./workflowGraphApi";
import type {
  MeshPreviewCalibration,
  SpatialAssetMetadataRevision,
  SpatialCoordinateUnit,
  SpatialMetadataReviewState,
  SpatialSourceAsset,
} from "./workflowGraphApi";

interface ProjectSpatialAssetPreviewProps {
  projectId: string;
  onComparisonSaved?: () => void;
}

function displayParseStatus(
  status: SpatialSourceAsset["parse_status"],
): string {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function displayQcWarning(warning: string): string {
  return warning.replaceAll("_", " ");
}

/** Project changes must never reuse another project's asset selection or preview. */
export function ProjectSpatialAssetPreview({
  projectId,
  onComparisonSaved,
}: ProjectSpatialAssetPreviewProps) {
  return (
    <ProjectSpatialAssetPreviewSession
      key={projectId}
      projectId={projectId}
      onComparisonSaved={onComparisonSaved}
    />
  );
}

function ProjectSpatialAssetPreviewSession({
  projectId,
  onComparisonSaved,
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
  const [metadataRevisions, setMetadataRevisions] = useState<
    SpatialAssetMetadataRevision[]
  >([]);
  const [metadataUnit, setMetadataUnit] =
    useState<SpatialCoordinateUnit>("unknown");
  const [metadataFrame, setMetadataFrame] = useState("");
  const [metadataEvidence, setMetadataEvidence] = useState("");
  const [metadataTransform, setMetadataTransform] = useState("");
  const [metadataReviewState, setMetadataReviewState] =
    useState<SpatialMetadataReviewState>("unreviewed");
  const [metadataReviewer, setMetadataReviewer] = useState("");
  const [metadataReviewNote, setMetadataReviewNote] = useState("");
  const [metadataSavedRevision, setMetadataSavedRevision] = useState<
    number | null
  >(null);
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

  useEffect(() => {
    setMetadataRevisions([]);
    setMetadataSavedRevision(null);
    if (!selectedId) return;
    const controller = new AbortController();
    void listSpatialAssetMetadataRevisions(
      projectId,
      selectedId,
      controller.signal,
    )
      .then((records) => {
        if (!controller.signal.aborted) {
          setMetadataRevisions(
            records.filter(
              (record) =>
                record.project_id === projectId &&
                record.spatial_source_asset_id === selectedId,
            ),
          );
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Unable to list 3D metadata revisions.",
          );
        }
      });
    return () => controller.abort();
  }, [projectId, selectedId]);

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
      if (
        record.project_id !== projectId ||
        !record.id.trim() ||
        !/^[a-f0-9]{64}$/i.test(record.sha256) ||
        record.measurement_status !== "source_unreviewed" ||
        record.calibration_verified !== false ||
        record.specimen_identity_verified !== false
      ) {
        throw new Error(
          "Imported 3D original has invalid project ownership or unreviewed provenance.",
        );
      }
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

  async function saveMetadataRevision(): Promise<void> {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setMetadataSavedRevision(null);
    try {
      let transform: number[][] | null = null;
      if (metadataTransform.trim()) {
        const parsed = JSON.parse(metadataTransform) as unknown;
        if (!Array.isArray(parsed)) {
          throw new Error("Metadata transform must be a JSON matrix.");
        }
        transform = parsed as number[][];
      }
      const scales: Partial<Record<SpatialCoordinateUnit, number>> = {
        meter: 1,
        millimeter: 0.001,
        centimeter: 0.01,
        micrometer: 0.000001,
      };
      const attributed = metadataReviewState !== "unreviewed";
      const record = await createSpatialAssetMetadataRevision(
        projectId,
        selected.id,
        {
          coordinate_unit: metadataUnit,
          meters_per_unit: scales[metadataUnit] ?? null,
          coordinate_frame_id: metadataFrame.trim() || null,
          transform_to_project_frame: transform,
          calibration_evidence: metadataEvidence.trim() || null,
          review_state: metadataReviewState,
          reviewed_by_identity: attributed
            ? metadataReviewer.trim() || null
            : null,
          review_note: attributed ? metadataReviewNote.trim() || null : null,
          created_by_identity: "local_user",
        },
      );
      if (
        record.project_id !== projectId ||
        record.spatial_source_asset_id !== selected.id ||
        record.source_sha256 !== selected.sha256
      ) {
        throw new Error("Saved metadata revision has invalid source binding.");
      }
      setMetadataRevisions((previous) => [...previous, record]);
      setMetadataSavedRevision(record.revision);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to save 3D metadata revision.",
      );
    } finally {
      setBusy(false);
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
        <>
          <p className="muted-copy">
            Source SHA-256: <code>{selected.sha256}</code>. Source and
            calibration remain unreviewed; mesh edges and point chords are not
            anatomical branch lengths.
          </p>
          <section
            className="panel-card"
            aria-label="3D structural parse status"
          >
            <h5>
              Structural parse: {displayParseStatus(selected.parse_status)}
            </h5>
            {selected.parse_status === "succeeded" && selected.parse_summary ? (
              <>
                <p className="muted-copy">
                  Parsed as{" "}
                  {selected.parse_summary.source_kind_resolved.replaceAll(
                    "_",
                    " ",
                  )}
                  {selected.parse_summary.vertex_count !== null
                    ? ` with ${selected.parse_summary.vertex_count} vertices and ${selected.parse_summary.face_count ?? 0} faces`
                    : ` with ${selected.parse_summary.point_count ?? 0} points`}
                  . No physical calibration was applied; the parse is unreviewed
                  and does not establish specimen identity.
                </p>
                {selected.parse_summary.qc_warnings.length > 0 && (
                  <p className="muted-copy">
                    Parse QC:{" "}
                    {selected.parse_summary.qc_warnings
                      .map(displayQcWarning)
                      .join(", ")}
                    .
                  </p>
                )}
              </>
            ) : (
              <p className="muted-copy">
                Parsing runs in the local background. Reopen this workspace to
                refresh its status before scientific preview or review.
              </p>
            )}
          </section>
          <section
            className="panel-card"
            aria-label="3D asset metadata revisions"
          >
            <h5>Immutable unit and frame metadata</h5>
            <p className="muted-copy">
              Save append-only source-unit, coordinate-frame, transform, and
              review evidence. Attribution is local and does not authenticate a
              reviewer or verify calibration.
            </p>
            <div className="feature-grid">
              <label>
                Source coordinate unit
                <select
                  aria-label="Source coordinate unit"
                  value={metadataUnit}
                  onChange={(event) =>
                    setMetadataUnit(event.target.value as SpatialCoordinateUnit)
                  }
                >
                  <option value="unknown">Unknown</option>
                  <option value="unitless">Unitless</option>
                  <option value="meter">Meter</option>
                  <option value="centimeter">Centimeter</option>
                  <option value="millimeter">Millimeter</option>
                  <option value="micrometer">Micrometer</option>
                </select>
              </label>
              <label>
                Source coordinate frame
                <input
                  aria-label="Source coordinate frame"
                  value={metadataFrame}
                  onChange={(event) => setMetadataFrame(event.target.value)}
                  maxLength={128}
                />
              </label>
              <label>
                Metadata calibration evidence
                <input
                  aria-label="Metadata calibration evidence"
                  value={metadataEvidence}
                  onChange={(event) => setMetadataEvidence(event.target.value)}
                  maxLength={2000}
                />
              </label>
              <label>
                Transform to project frame (optional 4×4 JSON)
                <textarea
                  aria-label="Transform to project frame"
                  value={metadataTransform}
                  onChange={(event) => setMetadataTransform(event.target.value)}
                />
              </label>
              <label>
                Metadata review state
                <select
                  aria-label="Metadata review state"
                  value={metadataReviewState}
                  onChange={(event) =>
                    setMetadataReviewState(
                      event.target.value as SpatialMetadataReviewState,
                    )
                  }
                >
                  <option value="unreviewed">Unreviewed</option>
                  <option value="attributed_unverified">
                    Attributed, unverified
                  </option>
                  <option value="rejected">Rejected</option>
                </select>
              </label>
              {metadataReviewState !== "unreviewed" && (
                <>
                  <label>
                    Reviewer identity (self-declared)
                    <input
                      aria-label="Metadata reviewer identity"
                      value={metadataReviewer}
                      onChange={(event) =>
                        setMetadataReviewer(event.target.value)
                      }
                    />
                  </label>
                  <label>
                    Review note
                    <input
                      aria-label="Metadata review note"
                      value={metadataReviewNote}
                      onChange={(event) =>
                        setMetadataReviewNote(event.target.value)
                      }
                    />
                  </label>
                </>
              )}
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => void saveMetadataRevision()}
            >
              Save metadata revision
            </button>
            <p className="muted-copy">
              {metadataRevisions.length} immutable metadata revision
              {metadataRevisions.length === 1 ? "" : "s"} saved.
            </p>
            {metadataSavedRevision !== null && (
              <p role="status">
                Metadata revision {metadataSavedRevision} saved.
              </p>
            )}
          </section>
        </>
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
      {selected &&
        kind === "mesh" &&
        selected.parse_summary?.source_kind_resolved !== "point_cloud" && (
          <ProjectSpatialComparison
            key={selected.id}
            projectId={projectId}
            asset={selected}
            calibration={
              artifact
                ? {
                    meters_per_unit: Number(scale),
                    calibration_method: calibrationMethod,
                    calibration_evidence: evidence,
                    relative_scale_uncertainty:
                      uncertainty.trim() === "" ? null : Number(uncertainty),
                  }
                : undefined
            }
            onSaved={onComparisonSaved}
          />
        )}
    </section>
  );
}
