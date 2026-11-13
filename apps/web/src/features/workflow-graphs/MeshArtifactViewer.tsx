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
  pathPolylines: Vec3[][];
  routeInspections: MeshRouteInspection[];
}

interface MeshRouteInspection {
  sourceIndex: number;
  pathVertices: Vec3[];
  vertexIndices: number[];
  cumulativeLengthsM: number[] | null;
  cumulativeScaleIntervalsM: [number, number][] | null;
  edgeLengthsM: number[] | null;
  edgeScaleIntervalsM: [number, number][] | null;
  edgeLengthsProvided: boolean;
  edgeIntervalsProvided: boolean;
  startVertexIndex: number;
  endVertexIndex: number;
  lengthM: number | null;
  lengthScaleIntervalM: [number, number] | null;
  qcWarnings: string[] | null;
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

/**
 * Keep complete selected edge paths visible when the triangle preview is
 * decimated. Invalid or legacy path evidence is never drawn as a route.
 */
function parsePathInspections(
  value: unknown,
  relativeScaleUncertainty: number | null,
): MeshRouteInspection[] {
  if (!Array.isArray(value) || value.length > 16) return [];
  return value.flatMap((entry, sourceIndex) => {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      return [];
    }
    const route = entry as Record<string, unknown>;
    if (route.status !== "connected") return [];
    const indices = route.path_vertex_indices;
    const coordinates = route.path_vertices_in_source_frame_m;
    if (
      !Array.isArray(indices) ||
      indices.length < 2 ||
      indices.length > 2000 ||
      !indices.every(
        (index) =>
          typeof index === "number" && Number.isInteger(index) && index >= 0,
      ) ||
      new Set(indices).size !== indices.length ||
      !Array.isArray(coordinates) ||
      coordinates.length !== indices.length ||
      !coordinates.every(isVec3)
    ) {
      return [];
    }

    // A saved route is provisional evidence. Invalid or missing numerical
    // metadata must remain unknown rather than being displayed as a result.
    const nominal = route.length_m;
    const lengthM =
      typeof nominal === "number" && Number.isFinite(nominal) && nominal >= 0
        ? nominal
        : null;
    const interval = route.length_scale_interval_m;
    const lengthScaleIntervalM: [number, number] | null =
      lengthM !== null &&
      Array.isArray(interval) &&
      interval.length === 2 &&
      interval.every(
        (bound) =>
          typeof bound === "number" && Number.isFinite(bound) && bound >= 0,
      ) &&
      interval[0] <= lengthM &&
      interval[1] >= lengthM
        ? [interval[0], interval[1]]
        : null;
    // Persisted cumulative distances are scientific artifacts, not values
    // reconstructed from the decimated display triangles. Reject malformed
    // or inconsistent arrays rather than presenting invented measurements.
    const rawCumulative = route.path_cumulative_lengths_m;
    const cumulativeLengthsM =
      lengthM !== null &&
      Array.isArray(rawCumulative) &&
      rawCumulative.length === indices.length &&
      rawCumulative.every(
        (distance) =>
          typeof distance === "number" &&
          Number.isFinite(distance) &&
          distance >= 0,
      ) &&
      rawCumulative[0] === 0 &&
      rawCumulative.every(
        (distance, index) =>
          index === 0 || distance >= rawCumulative[index - 1],
      ) &&
      Math.abs(rawCumulative[rawCumulative.length - 1] - lengthM) <=
        Math.max(1e-12, lengthM * 1e-8)
        ? (rawCumulative as number[])
        : null;
    const rawCumulativeIntervals =
      route.path_cumulative_length_scale_intervals_m;
    const cumulativeScaleIntervalsM: [number, number][] | null =
      cumulativeLengthsM !== null &&
      Array.isArray(rawCumulativeIntervals) &&
      rawCumulativeIntervals.length === indices.length &&
      rawCumulativeIntervals.every(
        (pair, index) =>
          Array.isArray(pair) &&
          pair.length === 2 &&
          pair.every(
            (bound) =>
              typeof bound === "number" && Number.isFinite(bound) && bound >= 0,
          ) &&
          pair[0] <= cumulativeLengthsM[index] &&
          pair[1] >= cumulativeLengthsM[index] &&
          (index === 0 ||
            (pair[0] >= rawCumulativeIntervals[index - 1][0] &&
              pair[1] >= rawCumulativeIntervals[index - 1][1])),
      )
        ? (rawCumulativeIntervals as [number, number][])
        : null;
    // Prefer persisted per-edge measurements over differences of large
    // cumulative distances, which can lose precision. Reject contradictory
    // saved evidence instead of reconstructing an apparently valid segment.
    const rawEdges = route.path_edge_lengths_m;
    const edgeLengthsProvided = rawEdges !== undefined && rawEdges !== null;
    const edgeLengthsM: number[] | null =
      lengthM !== null &&
      Array.isArray(rawEdges) &&
      rawEdges.length === indices.length - 1 &&
      rawEdges.every(
        (distance) =>
          typeof distance === "number" &&
          Number.isFinite(distance) &&
          distance >= 0,
      ) &&
      Math.abs(rawEdges.reduce((sum, distance) => sum + distance, 0) - lengthM) <=
        Math.max(1e-12, lengthM * 1e-8) &&
      (cumulativeLengthsM === null ||
        rawEdges.every(
          (distance, index) =>
            Math.abs(
              cumulativeLengthsM[index + 1] -
                cumulativeLengthsM[index] -
                distance,
            ) <=
            Math.max(
              1e-12,
              distance * 1e-8,
              cumulativeLengthsM[index + 1] * 1e-12,
            ),
        ))
        ? (rawEdges as number[])
        : null;
    const rawEdgeIntervals = route.path_edge_length_scale_intervals_m;
    const edgeIntervalsProvided =
      rawEdgeIntervals !== undefined && rawEdgeIntervals !== null;
    const edgeScaleIntervalsM: [number, number][] | null =
      edgeLengthsM !== null &&
      relativeScaleUncertainty !== null &&
      Array.isArray(rawEdgeIntervals) &&
      rawEdgeIntervals.length === edgeLengthsM.length &&
      rawEdgeIntervals.every(
        (pair, index) =>
          Array.isArray(pair) &&
          pair.length === 2 &&
          pair.every(
            (bound) =>
              typeof bound === "number" &&
              Number.isFinite(bound) &&
              bound >= 0,
          ) &&
          Math.abs(
            pair[0] - edgeLengthsM[index] * (1 - relativeScaleUncertainty),
          ) <= Math.max(1e-12, edgeLengthsM[index] * 1e-8) &&
          Math.abs(
            pair[1] - edgeLengthsM[index] * (1 + relativeScaleUncertainty),
          ) <= Math.max(1e-12, edgeLengthsM[index] * 1e-8),
      )
        ? (rawEdgeIntervals as [number, number][])
        : null;
    const warnings = route.path_qc_warnings;
    const qcWarnings =
      Array.isArray(warnings) &&
      warnings.length <= 20 &&
      warnings.every(
        (code) => typeof code === "string" && /^[a-z0-9_]{1,80}$/.test(code),
      )
        ? (warnings as string[])
        : null;

    return [
      {
        sourceIndex,
        pathVertices: coordinates as Vec3[],
        vertexIndices: indices as number[],
        cumulativeLengthsM,
        cumulativeScaleIntervalsM,
        edgeLengthsM,
        edgeScaleIntervalsM,
        edgeLengthsProvided,
        edgeIntervalsProvided,
        startVertexIndex: indices[0] as number,
        endVertexIndex: indices[indices.length - 1] as number,
        lengthM,
        lengthScaleIntervalM,
        qcWarnings,
      },
    ];
  });
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
  const routeInspections = parsePathInspections(
    data.surface_edge_paths,
    typeof relativeScaleUncertainty === "number"
      ? relativeScaleUncertainty
      : null,
  );
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
    pathPolylines: routeInspections.map((route) => route.pathVertices),
    routeInspections,
  };
}

/** Report persisted provisional evidence without deriving anatomical claims. */
function formatRouteInspection(route: MeshRouteInspection): string {
  const length =
    route.lengthM === null ? "unknown" : `${route.lengthM.toPrecision(6)} m`;
  const interval =
    route.lengthScaleIntervalM === null
      ? "unknown"
      : `[${route.lengthScaleIntervalM[0].toPrecision(6)}, ${route.lengthScaleIntervalM[1].toPrecision(6)}] m`;
  const qc =
    route.qcWarnings === null
      ? "unknown (missing or invalid saved QC)"
      : route.qcWarnings.length === 0
        ? "no route-specific flags"
        : route.qcWarnings.join(", ");
  return `Route ${route.sourceIndex + 1}, mesh vertices ${route.startVertexIndex} to ${route.endVertexIndex}. Saved geometric route length: ${length}. Scale-only length interval: ${interval}. Path QC: ${qc}. Provisional mesh geometry, not a verified biological branch length.`;
}

/** Inspect a persisted segment increment, not an anatomical branch or independently reviewed measure. */
function formatRouteSegmentInspection(
  route: MeshRouteInspection,
  waypointIndex: number,
  relativeScaleUncertainty: number | null,
): string {
  if (waypointIndex === 0) {
    return "Starting waypoint has no preceding route segment.";
  }
  const length =
    route.edgeLengthsM?.[waypointIndex - 1] ??
    (route.edgeLengthsProvided || route.cumulativeLengthsM === null
      ? null
      : route.cumulativeLengthsM[waypointIndex] -
        route.cumulativeLengthsM[waypointIndex - 1]);
  if (length === null) {
    return "Saved preceding mesh-edge segment length: unknown. Scale-only segment interval: unknown (invalid or missing saved segment evidence).";
  }
  const savedInterval = route.edgeScaleIntervalsM?.[waypointIndex - 1];
  const lower =
    savedInterval?.[0] ??
    (route.edgeIntervalsProvided || relativeScaleUncertainty === null
      ? null
      : length * (1 - relativeScaleUncertainty));
  const upper =
    savedInterval?.[1] ??
    (route.edgeIntervalsProvided || relativeScaleUncertainty === null
      ? null
      : length * (1 + relativeScaleUncertainty));
  const interval =
    lower === null ||
    upper === null ||
    !Number.isFinite(lower) ||
    !Number.isFinite(upper)
      ? "unknown"
      : `[${lower.toPrecision(6)}, ${upper.toPrecision(6)}] m`;
  return `Saved preceding mesh-edge segment length: ${length.toPrecision(6)} m. Scale-only segment interval: ${interval} (shared caller-supplied scale; excludes reconstruction and endpoint uncertainty). Not a verified anatomical segment.`;
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
  const [selectedRoute, setSelectedRoute] = useState<{
    artifact: unknown;
    sourceIndex: number;
  } | null>(null);
  const selectedRouteIndex =
    selectedRoute !== null && selectedRoute.artifact === artifact
      ? selectedRoute.sourceIndex
      : null;
  const selectedRouteInspection =
    mesh?.routeInspections.find(
      (route) => route.sourceIndex === selectedRouteIndex,
    ) ?? null;
  const [selectedWaypoint, setSelectedWaypoint] = useState<{
    artifact: unknown;
    routeIndex: number;
    vertexIndex: number;
  } | null>(null);
  const selectedWaypointIndex =
    selectedRouteInspection !== null &&
    selectedWaypoint !== null &&
    selectedWaypoint.artifact === artifact &&
    selectedWaypoint.routeIndex === selectedRouteInspection.sourceIndex
      ? Math.min(
          selectedWaypoint.vertexIndex,
          selectedRouteInspection.pathVertices.length - 1,
        )
      : 0;
  const selectedWaypointPosition =
    mesh !== null && selectedRouteInspection !== null
      ? project(
          selectedRouteInspection.pathVertices[selectedWaypointIndex],
          mesh.cameraTarget,
          mesh.cameraRadius,
          yaw,
          pitch,
          zoom,
        )
      : null;
  const selectedSegmentStartPosition =
    mesh !== null &&
    selectedRouteInspection !== null &&
    selectedWaypointIndex > 0
      ? project(
          selectedRouteInspection.pathVertices[selectedWaypointIndex - 1],
          mesh.cameraTarget,
          mesh.cameraRadius,
          yaw,
          pitch,
          zoom,
        )
      : null;
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

  const routePolylines = useMemo(() => {
    if (!mesh) return [];
    return mesh.pathPolylines.map((vertices) =>
      vertices
        .map((vertex) =>
          project(
            vertex,
            mesh.cameraTarget,
            mesh.cameraRadius,
            yaw,
            pitch,
            zoom,
          ),
        )
        .map((point) => `${point.x},${point.y}`)
        .join(" "),
    );
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
        {routePolylines.map((points, index) => (
          <polyline
            key={index}
            data-testid="mesh-route-polyline"
            points={points}
            fill="none"
            stroke={
              selectedRouteIndex === mesh.routeInspections[index].sourceIndex
                ? "#fb7185"
                : "#fbbf24"
            }
            strokeWidth={
              selectedRouteIndex === mesh.routeInspections[index].sourceIndex
                ? 4
                : 2.5
            }
            vectorEffect="non-scaling-stroke"
            aria-label={`Provisional mesh edge route ${index + 1}`}
          >
            <title>Unverified source-frame mesh edge route {index + 1}</title>
          </polyline>
        ))}
        {selectedSegmentStartPosition !== null &&
          selectedWaypointPosition !== null && (
            <line
              data-testid="mesh-route-selected-segment"
              x1={selectedSegmentStartPosition.x}
              y1={selectedSegmentStartPosition.y}
              x2={selectedWaypointPosition.x}
              y2={selectedWaypointPosition.y}
              stroke="#fef08a"
              strokeWidth={4}
              vectorEffect="non-scaling-stroke"
              pointerEvents="none"
            />
          )}
        {selectedWaypointPosition !== null && (
          <circle
            data-testid="mesh-route-waypoint-marker"
            cx={selectedWaypointPosition.x}
            cy={selectedWaypointPosition.y}
            r={6}
            fill="#fef08a"
            stroke="#172554"
            strokeWidth={2}
            pointerEvents="none"
          />
        )}
      </svg>
      {routePolylines.length > 0 && (
        <p className="annotation-helper">
          Displaying {routePolylines.length} complete provisional mesh-edge
          route(s), including vertices omitted from sampled triangles. Routes
          are not verified coral branch centerlines or registered positions.
        </p>
      )}
      {mesh.routeInspections.length > 0 && (
        <div aria-label="Provisional mesh route inspector">
          <p className="annotation-helper">
            Select a connected route to inspect its saved geometric length,
            scale-only uncertainty, and scientific QC. No route establishes
            anatomical branch length or verified calibration.
          </p>
          {mesh.routeInspections.map((route) => (
            <button
              type="button"
              className="secondary"
              key={route.sourceIndex}
              aria-label={`Inspect provisional route ${route.sourceIndex + 1}`}
              aria-pressed={selectedRouteIndex === route.sourceIndex}
              onClick={() =>
                setSelectedRoute({ artifact, sourceIndex: route.sourceIndex })
              }
            >
              Route {route.sourceIndex + 1}
            </button>
          ))}
          <p className="annotation-helper" aria-live="polite">
            {selectedRouteInspection === null
              ? "Select a connected route for provisional measurement details."
              : formatRouteInspection(selectedRouteInspection)}
          </p>
          {selectedRouteInspection !== null && (
            <div aria-label="Provisional route vertex inspector">
              <label>
                Route vertex
                <input
                  aria-label="Route vertex"
                  type="range"
                  min={0}
                  max={selectedRouteInspection.pathVertices.length - 1}
                  step={1}
                  value={selectedWaypointIndex}
                  onChange={(event) =>
                    setSelectedWaypoint({
                      artifact,
                      routeIndex: selectedRouteInspection.sourceIndex,
                      vertexIndex: Number(event.target.value),
                    })
                  }
                />
              </label>
              <p className="annotation-helper" aria-live="polite">
                {`Route waypoint ${selectedWaypointIndex + 1} of ${selectedRouteInspection.pathVertices.length}, source vertex ${selectedRouteInspection.vertexIndices[selectedWaypointIndex]}. Saved cumulative mesh-edge distance: ${selectedRouteInspection.cumulativeLengthsM === null ? "unknown" : `${selectedRouteInspection.cumulativeLengthsM[selectedWaypointIndex].toPrecision(6)} m`}. Scale-only cumulative interval: ${selectedRouteInspection.cumulativeScaleIntervalsM === null ? "unknown" : `[${selectedRouteInspection.cumulativeScaleIntervalsM[selectedWaypointIndex][0].toPrecision(6)}, ${selectedRouteInspection.cumulativeScaleIntervalsM[selectedWaypointIndex][1].toPrecision(6)}] m`}. Coordinates in unregistered source frame: (${selectedRouteInspection.pathVertices[selectedWaypointIndex].map((coordinate) => coordinate.toPrecision(6)).join(", ")}) m. Provisional geometric waypoint, not a verified coral anatomical landmark. ${formatRouteSegmentInspection(selectedRouteInspection, selectedWaypointIndex, mesh.relativeScaleUncertainty)}`}
              </p>
            </div>
          )}
        </div>
      )}
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
