import { useMemo, useState } from "react";

type Vec3 = [number, number, number];
type RGB = [number, number, number];
type PointScaleIntervals = [[number, number], [number, number], [number, number]];

interface PointChord {
  point_indices: [number, number];
  chord_distance_m: number;
  scale_uncertainty_m?: number | null;
  endpoint_coordinates_in_source_frame_m?: [Vec3, Vec3] | null;
}

interface PointCloudRenderArtifact {
  points: Vec3[];
  indices: number[];
  colors: RGB[] | null;
  pointScaleIntervals: PointScaleIntervals[] | null;
  target: Vec3;
  radius: number;
  totalCount: number;
  chords: PointChord[];
  omittedExtrema: string[] | null;
  omittedChordEndpoints: number[] | null;
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

function isRGB(value: unknown): value is RGB {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every(
      (channel) =>
        typeof channel === "number" &&
        Number.isInteger(channel) &&
        channel >= 0 &&
        channel <= 255,
    )
  );
}

function isPointScaleIntervals(value: unknown): value is PointScaleIntervals {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every(
      (bounds) =>
        Array.isArray(bounds) &&
        bounds.length === 2 &&
        bounds.every(
          (coordinate) =>
            typeof coordinate === "number" && Number.isFinite(coordinate),
        ) &&
        bounds[0] <= bounds[1],
    )
  );
}

function isPointChord(value: unknown, totalCount: number): value is PointChord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const chord = value as Record<string, unknown>;
  const pair = chord.point_indices;
  const distance = chord.chord_distance_m;
  const uncertainty = chord.scale_uncertainty_m;
  const endpoints = chord.endpoint_coordinates_in_source_frame_m;
  return (
    Array.isArray(pair) &&
    pair.length === 2 &&
    pair.every(
      (index) =>
        typeof index === "number" &&
        Number.isInteger(index) &&
        index >= 0 &&
        index < totalCount,
    ) &&
    pair[0] !== pair[1] &&
    typeof distance === "number" &&
    Number.isFinite(distance) &&
    distance >= 0 &&
    (uncertainty == null ||
      (typeof uncertainty === "number" &&
        Number.isFinite(uncertainty) &&
        uncertainty >= 0)) &&
    (endpoints == null ||
      (Array.isArray(endpoints) &&
        endpoints.length === 2 &&
        endpoints.every(isVec3)))
  );
}

/** Fail closed on malformed persisted display data; never infer coral surface or condition. */
export function parsePointCloudRenderArtifact(
  value: unknown,
): PointCloudRenderArtifact | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const data = value as Record<string, unknown>;
  const points = data.preview_points_in_source_frame_m;
  const indices = data.preview_point_indices;
  const colors = data.preview_point_colors_rgb_uint8;
  const rawPointScaleIntervals = data.preview_point_scale_intervals_m;
  const min = data.axis_aligned_min_in_source_frame_m;
  const max = data.axis_aligned_max_in_source_frame_m;
  const totalCount = data.point_count;
  const rawChords = data.selected_point_chords;
  const omittedExtrema = data.preview_omitted_axis_extrema;
  const omittedChordEndpoints =
    data.preview_omitted_selected_chord_endpoint_indices;
  const chordEndpointsCovered = data.preview_selected_chord_endpoints_covered;
  const provenance = data.provenance;
  // A point-cloud preview is provisional geometry, never verified biology.
  // Reject contradictory saved metadata instead of displaying a misleading artifact.
  if (
    provenance === null ||
    typeof provenance !== "object" ||
    Array.isArray(provenance) ||
    (provenance as Record<string, unknown>).calibration_verified !== false ||
    (provenance as Record<string, unknown>).coordinate_registration_verified ===
      true ||
    data.measurement_status !== "caller_supplied_unverified" ||
    data.surface_area_m2 != null ||
    data.branch_length_m != null
  ) {
    return null;
  }
  if (
    !Array.isArray(points) ||
    points.length < 1 ||
    points.length > 512 ||
    !points.every(isVec3) ||
    !Array.isArray(indices) ||
    indices.length !== points.length ||
    typeof totalCount !== "number" ||
    !Number.isInteger(totalCount) ||
    (totalCount as number) < points.length ||
    (totalCount as number) > 2000 ||
    !indices.every(
      (index, position) =>
        typeof index === "number" &&
        Number.isInteger(index) &&
        index >= 0 &&
        index < (totalCount as number) &&
        (position === 0 || index > indices[position - 1]),
    ) ||
    (colors !== null &&
      (!Array.isArray(colors) ||
        colors.length !== points.length ||
        !colors.every(isRGB))) ||
    !isVec3(min) ||
    !isVec3(max) ||
    min.some((coordinate, axis) => coordinate > max[axis]) ||
    points.some((point) =>
      point.some(
        (coordinate, axis) => coordinate < min[axis] || coordinate > max[axis],
      ),
    )
  ) {
    return null;
  }
  // Scale-only intervals belong to the original sampled point order, never
  // to sorted render order. Fail closed on malformed or stale saved intervals.
  // Historical artifacts without this optional field remain displayable.
  if (rawPointScaleIntervals != null) {
    const uncertainty = (provenance as Record<string, unknown>)
      .relative_scale_uncertainty;
    if (
      typeof uncertainty !== "number" ||
      !Number.isFinite(uncertainty) ||
      uncertainty < 0 ||
      uncertainty > 1 ||
      !Array.isArray(rawPointScaleIntervals) ||
      rawPointScaleIntervals.length !== points.length ||
      !rawPointScaleIntervals.every(isPointScaleIntervals)
    ) {
      return null;
    }
    for (let index = 0; index < points.length; index += 1) {
      for (let axis = 0; axis < 3; axis += 1) {
        const coordinate = (points as Vec3[])[index][axis];
        const expected = [
          coordinate * (1 - uncertainty),
          coordinate * (1 + uncertainty),
        ].sort((a, b) => a - b);
        const actual = (rawPointScaleIntervals as PointScaleIntervals[])[index][
          axis
        ];
        if (
          actual.some(
            (value, bound) =>
              Math.abs(value - expected[bound]) >
              16 *
                Number.EPSILON *
                Math.max(1, Math.abs(value), Math.abs(expected[bound])),
          )
        ) {
          return null;
        }
      }
    }
  }
  // A coverage verdict without its omitted-extrema list is not auditable.
  // Older artifacts omit both fields and remain explicitly unassessed.
  if (
    (omittedExtrema === undefined) !==
    (data.preview_axis_extrema_covered === undefined)
  ) {
    return null;
  }
  // Newer artifacts carry source-axis coverage QC; legacy artifacts are unassessed.
  if (
    omittedExtrema !== undefined &&
    (!Array.isArray(omittedExtrema) ||
      !omittedExtrema.every(
        (value) =>
          typeof value === "string" &&
          ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"].includes(
            value,
          ),
      ) ||
      new Set(omittedExtrema).size !== omittedExtrema.length ||
      data.preview_axis_extrema_covered !== (omittedExtrema.length === 0))
  ) {
    return null;
  }
  // Verify omissions that remain visible after scaling to display units.
  // Scaling large offsets can round a genuinely missing source extreme onto
  // the displayed bound; extra warnings are conservative, not contradictions.
  if (Array.isArray(omittedExtrema)) {
    const actualOmissions: string[] = [];
    for (let axis = 0; axis < 3; axis += 1) {
      const sampledValues = (points as Vec3[]).map((point) => point[axis]);
      const axisName = ["x", "y", "z"][axis];
      if (Math.min(...sampledValues) !== min[axis]) {
        actualOmissions.push(`${axisName}_min`);
      }
      if (Math.max(...sampledValues) !== max[axis]) {
        actualOmissions.push(`${axisName}_max`);
      }
    }
    if (actualOmissions.some((label) => !omittedExtrema.includes(label))) {
      return null;
    }
  }
  if (
    rawChords != null &&
    (!Array.isArray(rawChords) ||
      rawChords.length > 32 ||
      !rawChords.every((chord) => isPointChord(chord, totalCount as number)))
  ) {
    return null;
  }
  const chords: PointChord[] = Array.isArray(rawChords) ? rawChords : [];
  // New artifacts must describe exactly which measured source endpoints were
  // lost to display sampling. Legacy artifacts have unassessed coverage.
  if (
    (omittedChordEndpoints === undefined) !==
    (chordEndpointsCovered === undefined)
  ) {
    return null;
  }
  if (omittedChordEndpoints !== undefined) {
    const expectedOmissions = [
      ...new Set(chords.flatMap((chord) => chord.point_indices)),
    ]
      .filter((index) => !(indices as number[]).includes(index))
      .sort((a, b) => a - b);
    if (
      !Array.isArray(omittedChordEndpoints) ||
      omittedChordEndpoints.length !== expectedOmissions.length ||
      !omittedChordEndpoints.every(
        (index, position) => index === expectedOmissions[position],
      ) ||
      chordEndpointsCovered !== (expectedOmissions.length === 0)
    ) {
      return null;
    }
  }
  // When both original endpoints survive display sampling, cross-check the
  // reported chord against their calibrated coordinates. Never infer an
  // unsampled endpoint from a visualization-only point subset.
  if (
    chords.some((chord) => {
      const firstIndex = (indices as number[]).indexOf(chord.point_indices[0]);
      const secondIndex = (indices as number[]).indexOf(chord.point_indices[1]);
      const embedded = chord.endpoint_coordinates_in_source_frame_m;
      // New backend artifacts persist both original endpoints even when one
      // is omitted by display decimation. Check their internal chord distance
      // without treating the embedded coordinates as verified field evidence.
      if (embedded) {
        for (const [position, displayIndex] of [
          firstIndex,
          secondIndex,
        ].entries()) {
          if (displayIndex < 0) continue;
          const shown = (points as Vec3[])[displayIndex];
          const endpoint = embedded[position];
          const magnitude = Math.max(
            1,
            ...shown.map(Math.abs),
            ...endpoint.map(Math.abs),
          );
          if (
            endpoint.some(
              (coordinate, axis) =>
                Math.abs(coordinate - shown[axis]) >
                16 * Number.EPSILON * magnitude,
            )
          ) {
            return true;
          }
        }
      }
      if (!embedded && (firstIndex < 0 || secondIndex < 0)) return false;
      const first = embedded?.[0] ?? (points as Vec3[])[firstIndex];
      const second = embedded?.[1] ?? (points as Vec3[])[secondIndex];
      const expected = Math.hypot(
        first[0] - second[0],
        first[1] - second[1],
        first[2] - second[2],
      );
      // Scaling a large source-frame offset can erase small differences
      // through floating-point cancellation. Do not reject a valid full-cloud
      // measurement when the display coordinates lack that precision.
      const coordinateMagnitude = Math.max(
        1,
        ...first.map(Math.abs),
        ...second.map(Math.abs),
      );
      const tolerance = Math.max(
        1e-9 * Math.max(1, expected, chord.chord_distance_m),
        16 * Number.EPSILON * coordinateMagnitude,
      );
      return (
        !Number.isFinite(expected) ||
        Math.abs(expected - chord.chord_distance_m) > tolerance
      );
    })
  ) {
    return null;
  }
  const target: Vec3 = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ];
  const radius =
    Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2;
  if (!isVec3(target) || !Number.isFinite(radius)) return null;
  return {
    points: points as Vec3[],
    indices: indices as number[],
    colors: colors as RGB[] | null,
    pointScaleIntervals:
      rawPointScaleIntervals == null
        ? null
        : (rawPointScaleIntervals as PointScaleIntervals[]),
    target,
    radius,
    totalCount: totalCount as number,
    chords,
    omittedExtrema:
      omittedExtrema === undefined ? null : (omittedExtrema as string[]),
    omittedChordEndpoints:
      omittedChordEndpoints === undefined
        ? null
        : (omittedChordEndpoints as number[]),
  };
}

function projectPoint(
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

/** Read-only orthographic preview of sampled points in unregistered source coordinates. */
export function PointCloudArtifactViewer({ artifact }: { artifact: unknown }) {
  const cloud = useMemo(
    () => parsePointCloudRenderArtifact(artifact),
    [artifact],
  );
  const [yaw, setYaw] = useState(30);
  const [pitch, setPitch] = useState(20);
  const [zoom, setZoom] = useState(1);
  const [selectedSourceIndex, setSelectedSourceIndex] = useState<number | null>(
    null,
  );
  const selectedDisplayIndex =
    cloud?.indices.indexOf(selectedSourceIndex ?? -1) ?? -1;
  const selectedPoint =
    cloud && selectedDisplayIndex >= 0
      ? cloud.points[selectedDisplayIndex]
      : null;
  const selectedIntervals =
    cloud && selectedDisplayIndex >= 0
      ? cloud.pointScaleIntervals?.[selectedDisplayIndex]
      : null;
  const displayPoints = useMemo(() => {
    if (!cloud) return [];
    return cloud.points
      .map((point, index) => ({
        ...projectPoint(point, cloud.target, cloud.radius, yaw, pitch, zoom),
        sourceIndex: cloud.indices[index],
        color: cloud.colors?.[index] ?? null,
      }))
      .sort((a, b) => a.depth - b.depth);
  }, [cloud, yaw, pitch, zoom]);

  if (!cloud) {
    return (
      <p role="status">
        This point-cloud artifact has no valid bounded 3D display data.
      </p>
    );
  }

  return (
    <section
      aria-label="Interactive point-cloud preview"
      data-testid="point-cloud-artifact-viewer"
    >
      <p className="annotation-helper">
        Read-only point visualization in unregistered source axes. Calibration
        remains unverified. RGB is display metadata, not biological condition;
        point clouds do not establish coral surface area or branch length.
      </p>
      <svg
        viewBox="0 0 560 400"
        role="img"
        aria-label="Rotatable point-cloud preview"
        style={{
          width: "100%",
          maxHeight: 440,
          background: "#092333",
          borderRadius: 8,
        }}
      >
        {displayPoints.map((point) => (
          <circle
            key={point.sourceIndex}
            data-source-point-index={point.sourceIndex}
            role="button"
            tabIndex={0}
            aria-label={`Inspect source point ${point.sourceIndex}`}
            aria-pressed={selectedSourceIndex === point.sourceIndex}
            onClick={() => setSelectedSourceIndex(point.sourceIndex)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setSelectedSourceIndex(point.sourceIndex);
              }
            }}
            cx={point.x}
            cy={point.y}
            r={3}
            fill={
              point.color
                ? `rgb(${point.color[0]}, ${point.color[1]}, ${point.color[2]})`
                : "#48b7d0"
            }
            stroke="#a8e9f2"
            strokeWidth={0.4}
          >
            <title>Source point {point.sourceIndex}</title>
          </circle>
        ))}
      </svg>
      <p className="annotation-helper" aria-live="polite">
        {selectedPoint && selectedSourceIndex !== null
          ? `Source point ${selectedSourceIndex} (unverified source frame): ${selectedPoint
              .map((coordinate, axis) => `${["x", "y", "z"][axis]}=${coordinate.toPrecision(6)} m`)
              .join(", ")}. ${selectedIntervals
              ? `Scale-only coordinate intervals: ${selectedIntervals
                  .map(
                    (bounds, axis) =>
                      `${["x", "y", "z"][axis]} [${bounds[0].toPrecision(6)}, ${bounds[1].toPrecision(6)}] m`,
                  )
                  .join("; ")}.`
              : "Scale uncertainty unavailable."} Not registration or anatomical verification.
          `
          : "Select a displayed source point to inspect calibrated coordinates and scale-only uncertainty."}
      </p>
      <div className="feature-grid">
        <label>
          Point yaw
          <input
            aria-label="Point yaw"
            type="range"
            min={-180}
            max={180}
            value={yaw}
            onChange={(event) => setYaw(Number(event.target.value))}
          />
        </label>
        <label>
          Point pitch
          <input
            aria-label="Point pitch"
            type="range"
            min={-85}
            max={85}
            value={pitch}
            onChange={(event) => setPitch(Number(event.target.value))}
          />
        </label>
        <label>
          Point zoom
          <input
            aria-label="Point zoom"
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
        Reset point view
      </button>
      {cloud.chords.map((chord, index) => (
        <p className="annotation-helper" key={index}>
          Source-point chord {chord.point_indices[0]}–{chord.point_indices[1]}:{" "}
          {chord.chord_distance_m.toFixed(4)} m
          {chord.scale_uncertainty_m != null
            ? ` (scale-only ±${chord.scale_uncertainty_m.toFixed(4)} m)`
            : " (scale uncertainty unknown)"}
          {" — provisional straight line, not anatomical branch length."}
        </p>
      ))}
      <p className="annotation-helper">
        Display points: {cloud.points.length} / {cloud.totalCount} · Point
        coverage: {((cloud.points.length / cloud.totalCount) * 100).toFixed(1)}%
        {cloud.colors ? " · Uncalibrated RGB display" : " · No RGB"}
        {cloud.omittedExtrema === null
          ? " · Source-axis extrema coverage unassessed"
          : cloud.omittedExtrema.length > 0
            ? ` · Display omits source-axis extrema: ${cloud.omittedExtrema.join(", ")}`
            : " · Source-axis extrema represented"}
        {cloud.chords.length > 0
          ? cloud.omittedChordEndpoints === null
            ? " · Chord endpoint display coverage unassessed"
            : cloud.omittedChordEndpoints.length > 0
              ? ` · Display omits selected chord endpoints: ${cloud.omittedChordEndpoints.join(", ")}`
              : " · Selected chord endpoints visible"
          : ""}
      </p>
    </section>
  );
}
