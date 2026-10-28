import { useMemo, useState } from "react";

type Vec3 = [number, number, number];
type Face = [number, number, number];

export interface MeshRenderArtifact {
  vertices: Vec3[];
  faces: Face[];
  sourceFaceIndices: number[];
  cameraTarget: Vec3;
  cameraRadius: number;
  decimated: boolean;
  faceFraction: number;
  areaFraction: number | null;
  relativeScaleUncertainty: number | null;
}

function isVec3(value: unknown): value is Vec3 {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every(
      (coordinate) =>
        typeof coordinate === "number" && Number.isFinite(coordinate),
    )
  );
}

function isFace(value: unknown, vertexCount: number): value is Face {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every(
      (index) =>
        typeof index === "number" &&
        Number.isInteger(index) &&
        index >= 0 &&
        index < vertexCount,
    )
  );
}

/** Validate persisted renderer data before drawing; never infer scientific verification. */
export function parseMeshRenderArtifact(
  value: unknown,
): MeshRenderArtifact | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const data = value as Record<string, unknown>;
  // This viewer is for provisional reconstructions. Do not display a saved
  // payload that contradicts its unverified scientific provenance.
  const provenance = data.provenance;
  const relativeScaleUncertainty =
    provenance !== null &&
    typeof provenance === "object" &&
    !Array.isArray(provenance)
      ? (provenance as Record<string, unknown>).relative_scale_uncertainty
      : undefined;
  if (
    (data.measurement_status !== undefined &&
      data.measurement_status !== "caller_supplied_unverified") ||
    data.preview_coordinate_registration_verified === true ||
    data.coordinate_registration_verified === true ||
    data.specimen_identity_verified === true ||
    data.observation_metadata_verified === true ||
    (provenance !== undefined &&
      (provenance === null ||
        typeof provenance !== "object" ||
        Array.isArray(provenance) ||
        (provenance as Record<string, unknown>).calibration_verified !==
          false)) ||
    (relativeScaleUncertainty !== undefined &&
      relativeScaleUncertainty !== null &&
      (typeof relativeScaleUncertainty !== "number" ||
        !Number.isFinite(relativeScaleUncertainty) ||
        relativeScaleUncertainty < 0 ||
        relativeScaleUncertainty > 1))
  ) {
    return null;
  }
  const vertices = data.preview_vertices_in_source_frame_m;
  const faces = data.preview_faces_local_indices;
  const sourceFaceIndices = data.preview_face_indices;
  const target = data.preview_camera_target_in_source_frame_m;
  const radius = data.preview_camera_radius_m;
  const fraction = data.preview_face_fraction;
  const areaFraction = data.preview_surface_area_fraction;
  if (
    !Array.isArray(vertices) ||
    vertices.length < 3 ||
    vertices.length > 1536 ||
    !vertices.every(isVec3) ||
    !Array.isArray(faces) ||
    faces.length < 1 ||
    faces.length > 512 ||
    !faces.every((face) => isFace(face, vertices.length)) ||
    !Array.isArray(sourceFaceIndices) ||
    sourceFaceIndices.length !== faces.length ||
    !sourceFaceIndices.every(
      (index) =>
        typeof index === "number" && Number.isInteger(index) && index >= 0,
    ) ||
    new Set(sourceFaceIndices).size !== sourceFaceIndices.length ||
    !isVec3(target) ||
    typeof radius !== "number" ||
    !Number.isFinite(radius) ||
    radius < 0 ||
    typeof fraction !== "number" ||
    !Number.isFinite(fraction) ||
    fraction <= 0 ||
    fraction > 1 ||
    (areaFraction !== null &&
      (typeof areaFraction !== "number" ||
        !Number.isFinite(areaFraction) ||
        areaFraction < 0 ||
        areaFraction > 1)) ||
    typeof data.preview_is_decimated !== "boolean"
  ) {
    return null;
  }
  return {
    vertices: vertices as Vec3[],
    faces: faces as Face[],
    sourceFaceIndices: sourceFaceIndices as number[],
    cameraTarget: target,
    cameraRadius: radius,
    decimated: data.preview_is_decimated,
    faceFraction: fraction,
    areaFraction: areaFraction as number | null,
    relativeScaleUncertainty:
      typeof relativeScaleUncertainty === "number"
        ? relativeScaleUncertainty
        : null,
  };
}

function project(
  point: Vec3,
  target: Vec3,
  radius: number,
  yawDegrees: number,
  pitchDegrees: number,
  zoom: number,
) {
  const yaw = (yawDegrees * Math.PI) / 180;
  const pitch = (pitchDegrees * Math.PI) / 180;
  const dx = point[0] - target[0];
  const dy = point[1] - target[1];
  const dz = point[2] - target[2];
  const rotatedX = Math.cos(yaw) * dx + Math.sin(yaw) * dz;
  const rotatedZ = -Math.sin(yaw) * dx + Math.cos(yaw) * dz;
  const rotatedY = Math.cos(pitch) * dy - Math.sin(pitch) * rotatedZ;
  const depth = Math.sin(pitch) * dy + Math.cos(pitch) * rotatedZ;
  const scale = (170 * zoom) / (radius || 1);
  return { x: 280 + rotatedX * scale, y: 200 - rotatedY * scale, depth };
}

function formatFaceVertices(vertices: Vec3[]): string {
  return vertices
    .map(
      (vertex, index) =>
        `vertex ${index + 1} (${vertex.map((coordinate) => coordinate.toPrecision(6)).join(", ")}) m`,
    )
    .join("; ");
}

/**
 * Compute a display-only triangle area from calibrated XYZ coordinates.
 * This is not a full-mesh, verified tissue-surface, or uncertainty estimate.
 */
function previewTriangleArea(vertices: Vec3[]): number | null {
  if (vertices.length !== 3) return null;
  const [a, b, c] = vertices;
  const ux = b[0] - a[0];
  const uy = b[1] - a[1];
  const uz = b[2] - a[2];
  const vx = c[0] - a[0];
  const vy = c[1] - a[1];
  const vz = c[2] - a[2];
  const crossX = uy * vz - uz * vy;
  const crossY = uz * vx - ux * vz;
  const crossZ = ux * vy - uy * vx;
  const area = Math.hypot(crossX, crossY, crossZ) / 2;
  return Number.isFinite(area) ? area : null;
}

function formatPreviewTriangleArea(vertices: Vec3[]): string {
  const area = previewTriangleArea(vertices);
  return area === null
    ? "unavailable (numeric overflow)"
    : `${area.toPrecision(6)} m²`;
}

/** Scale-only bounds, not reconstruction error or a statistical confidence interval. */
function formatPreviewTriangleScaleInterval(
  vertices: Vec3[],
  relativeUncertainty: number | null,
): string {
  if (relativeUncertainty === null)
    return "unknown (scale uncertainty not supplied)";
  const area = previewTriangleArea(vertices);
  if (area === null) return "unavailable (numeric overflow)";
  const lower = area * (1 - relativeUncertainty) ** 2;
  const upper = area * (1 + relativeUncertainty) ** 2;
  return Number.isFinite(lower) && Number.isFinite(upper)
    ? `[${lower.toPrecision(6)}, ${upper.toPrecision(6)}] m²`
    : "unavailable (numeric overflow)";
}

/** Display-only source-frame triangle edge lengths, not coral branch lengths. */
function previewTriangleEdgeLengths(vertices: Vec3[]): number[] | null {
  if (vertices.length !== 3) return null;
  const pairs: [number, number][] = [
    [0, 1],
    [1, 2],
    [2, 0],
  ];
  const lengths = pairs.map(([first, second]) => {
    const a = vertices[first];
    const b = vertices[second];
    return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  });
  return lengths.every(Number.isFinite) ? lengths : null;
}

function formatPreviewTriangleEdges(vertices: Vec3[]): string {
  const lengths = previewTriangleEdgeLengths(vertices);
  return lengths === null
    ? "unavailable (numeric overflow)"
    : `${lengths.map((length) => length.toPrecision(6)).join(", ")} m`;
}

/** Multiplicative scale bounds only; not reconstruction or endpoint uncertainty. */
function formatPreviewTriangleEdgeIntervals(
  vertices: Vec3[],
  relativeUncertainty: number | null,
): string {
  if (relativeUncertainty === null)
    return "unknown (scale uncertainty not supplied)";
  const lengths = previewTriangleEdgeLengths(vertices);
  if (lengths === null) return "unavailable (numeric overflow)";
  const bounds = lengths.map((length) => [
    length * (1 - relativeUncertainty),
    length * (1 + relativeUncertainty),
  ]);
  return bounds.every((pair) => pair.every(Number.isFinite))
    ? `${bounds
        .map(
          ([lower, upper]) =>
            `[${lower.toPrecision(6)}, ${upper.toPrecision(6)}]`,
        )
        .join(", ")} m`
    : "unavailable (numeric overflow)";
}

/**
 * Read-only, interactive orthographic view of the bounded mesh sample.
 * Scientific measurements and provenance remain in the original persisted artifact.
 */
export function MeshArtifactViewer({ artifact }: { artifact: unknown }) {
  const mesh = useMemo(() => parseMeshRenderArtifact(artifact), [artifact]);
  const [yaw, setYaw] = useState(30);
  const [pitch, setPitch] = useState(20);
  const [zoom, setZoom] = useState(1);
  // A source triangle number is scoped to the reconstruction, not the organism.
  const [selection, setSelection] = useState<{
    artifact: unknown;
    sourceFaceIndex: number;
  } | null>(null);
  const selectedSourceFaceIndex =
    selection !== null && selection.artifact === artifact
      ? selection.sourceFaceIndex
      : null;
  const selectedDisplayFaceIndex =
    mesh?.sourceFaceIndices.indexOf(selectedSourceFaceIndex ?? -1) ?? -1;
  const selectedVertices =
    mesh && selectedDisplayFaceIndex >= 0
      ? mesh.faces[selectedDisplayFaceIndex].map(
          (vertexIndex) => mesh.vertices[vertexIndex],
        )
      : null;

  const polygons = useMemo(() => {
    if (!mesh) return [];
    return mesh.faces
      .map((face, index) => {
        const points = face.map((vertexIndex) =>
          project(
            mesh.vertices[vertexIndex],
            mesh.cameraTarget,
            mesh.cameraRadius,
            yaw,
            pitch,
            zoom,
          ),
        );
        return {
          sourceFaceIndex: mesh.sourceFaceIndices[index],
          points: points.map((point) => `${point.x},${point.y}`).join(" "),
          depth: points.reduce((sum, point) => sum + point.depth, 0) / 3,
        };
      })
      .sort((a, b) => a.depth - b.depth);
  }, [mesh, yaw, pitch, zoom]);

  if (!mesh) {
    return (
      <p role="status">
        This saved mesh artifact has no valid bounded 3D display geometry.
      </p>
    );
  }

  return (
    <section
      aria-label="Interactive mesh preview"
      data-testid="mesh-artifact-viewer"
    >
      <p className="annotation-helper">
        Orthographic 3D visualization only. Calibration and coordinate
        registration remain unverified; sampled triangles must not replace
        full-mesh scientific measurements.
      </p>
      <svg
        viewBox="0 0 560 400"
        role="img"
        aria-label="Rotatable mesh surface preview"
        style={{
          width: "100%",
          maxHeight: 440,
          background: "#092333",
          borderRadius: 8,
        }}
      >
        {polygons.map((polygon, index) => (
          <polygon
            key={`${polygon.sourceFaceIndex}-${index}`}
            data-source-face-index={polygon.sourceFaceIndex}
            points={polygon.points}
            role="button"
            tabIndex={0}
            aria-label={`Inspect source triangle ${polygon.sourceFaceIndex}`}
            aria-pressed={selectedSourceFaceIndex === polygon.sourceFaceIndex}
            onClick={() =>
              setSelection({
                artifact,
                sourceFaceIndex: polygon.sourceFaceIndex,
              })
            }
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setSelection({
                  artifact,
                  sourceFaceIndex: polygon.sourceFaceIndex,
                });
              }
            }}
            fill={
              selectedSourceFaceIndex === polygon.sourceFaceIndex
                ? "#f3bf62"
                : "#48b7d0"
            }
            fillOpacity={0.45}
            stroke="#a8e9f2"
            strokeWidth={0.8}
            vectorEffect="non-scaling-stroke"
          >
            <title>Source triangle {polygon.sourceFaceIndex}</title>
          </polygon>
        ))}
      </svg>
      <p className="annotation-helper" aria-live="polite">
        {selectedVertices !== null && selectedSourceFaceIndex !== null
          ? `Source triangle ${selectedSourceFaceIndex} (unverified source frame): ${formatFaceVertices(selectedVertices)}. Selected preview triangle area: ${formatPreviewTriangleArea(selectedVertices)}. Scale-only triangle area interval: ${formatPreviewTriangleScaleInterval(selectedVertices, mesh.relativeScaleUncertainty)}. Selected preview triangle edge lengths (1–2, 2–3, 3–1): ${formatPreviewTriangleEdges(selectedVertices)}. Scale-only edge length intervals: ${formatPreviewTriangleEdgeIntervals(selectedVertices, mesh.relativeScaleUncertainty)} (caller-supplied scale uncertainty only; calibration and reconstruction uncertainty unverified). Preview vertices only; triangle edges are not anatomical branch lengths or verified surface measurements.`
          : "Select a displayed source triangle to inspect its original sampled vertices."}
      </p>
      <div className="feature-grid">
        <label>
          Yaw
          <input
            aria-label="Yaw"
            type="range"
            min={-180}
            max={180}
            value={yaw}
            onChange={(event) => setYaw(Number(event.target.value))}
          />
        </label>
        <label>
          Pitch
          <input
            aria-label="Pitch"
            type="range"
            min={-85}
            max={85}
            value={pitch}
            onChange={(event) => setPitch(Number(event.target.value))}
          />
        </label>
        <label>
          Zoom
          <input
            aria-label="Zoom"
            type="range"
            min={0.5}
            max={4}
            step={0.1}
            value={zoom}
            onChange={(event) => setZoom(Number(event.target.value))}
          />
        </label>
      </div>
      <button
        type="button"
        className="secondary"
        onClick={() => {
          setYaw(30);
          setPitch(20);
          setZoom(1);
        }}
      >
        Reset 3D view
      </button>
      <p className="annotation-helper">
        Display triangles: {mesh.faces.length} · Face coverage:{" "}
        {(mesh.faceFraction * 100).toFixed(1)}% · Surface-area coverage:{" "}
        {mesh.areaFraction === null
          ? "undefined (zero-area geometry)"
          : `${(mesh.areaFraction * 100).toFixed(1)}%`}
        {mesh.decimated ? " · Decimated preview" : " · Full face preview"}
      </p>
    </section>
  );
}
