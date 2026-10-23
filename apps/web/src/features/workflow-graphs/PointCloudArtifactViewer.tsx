import { useMemo, useState } from "react";

type Vec3 = [number, number, number];
type RGB = [number, number, number];

interface PointCloudRenderArtifact {
  points: Vec3[];
  indices: number[];
  colors: RGB[] | null;
  target: Vec3;
  radius: number;
  totalCount: number;
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
  const min = data.axis_aligned_min_in_source_frame_m;
  const max = data.axis_aligned_max_in_source_frame_m;
  const totalCount = data.point_count;
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
    target,
    radius,
    totalCount: totalCount as number,
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
      <p className="annotation-helper">
        Display points: {cloud.points.length} / {cloud.totalCount} · Point
        coverage: {((cloud.points.length / cloud.totalCount) * 100).toFixed(1)}%
        {cloud.colors ? " · Uncalibrated RGB display" : " · No RGB"}
      </p>
    </section>
  );
}
