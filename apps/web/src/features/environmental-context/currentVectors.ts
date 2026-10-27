import type { ScientificRecord } from "./environmentalContextApi";
export interface CurrentComponentUncertainty {
  value: number;
  kind: NonNullable<ScientificRecord["uncertainty"]>["kind"];
}
export interface CurrentVector {
  id: string;
  latitude: number;
  longitude: number;
  speed: number;
  bearing: number | null;
  east: number;
  north: number;
  eastUncertainty: CurrentComponentUncertainty | null;
  northUncertainty: CurrentComponentUncertainty | null;
  source: string;
  sourceKind: string;
  dataset: string;
  modelVersion: string | null;
  observedAt: string;
  depthM: number;
  recordIds: string[];
}
function componentUncertainty(
  row: ScientificRecord,
): CurrentComponentUncertainty | null {
  const value = row.normalized_uncertainty;
  const kind = row.uncertainty?.kind;
  if (value == null || !Number.isFinite(value) || value < 0 || !kind)
    return null;
  return { value, kind };
}
export function currentComponentUncertaintyText(
  component: "East" | "North",
  uncertainty: CurrentComponentUncertainty | null,
): string {
  return uncertainty
    ? `${component} component uncertainty: ${uncertainty.value.toFixed(3)} m/s (${uncertainty.kind.replaceAll("_", " ")})`
    : `${component} component uncertainty: unknown`;
}
export function currentVectors(records: ScientificRecord[]): CurrentVector[] {
  const groups = new Map<
    string,
    { east: ScientificRecord[]; north: ScientificRecord[] }
  >();
  for (const row of records) {
    if (
      !row.location ||
      (row.location.crs ?? "EPSG:4326") !== "EPSG:4326" ||
      !Number.isFinite(row.location.latitude) ||
      Math.abs(row.location.latitude) > 90 ||
      !Number.isFinite(row.location.longitude) ||
      Math.abs(row.location.longitude) > 180 ||
      row.depth_m == null ||
      !Number.isFinite(row.depth_m) ||
      row.depth_m < 0 ||
      !row.depth_reference ||
      row.normalized_unit !== "m/s" ||
      !Number.isFinite(row.normalized_value) ||
      ["suspect", "rejected"].includes(row.qc ?? "unassessed") ||
      row.environmental_snapshot_current === false
    )
      continue;
    const direction =
      row.variable === "current_eastward_velocity"
        ? "east"
        : row.variable === "current_northward_velocity"
          ? "north"
          : null;
    if (!direction) continue;
    const key = JSON.stringify([
      row.project_id,
      // A current component belongs to its scientific subject; matching grid
      // coordinates alone must never combine separate tracked organisms.
      row.subject?.image_id ?? null,
      row.subject?.video_id ?? null,
      row.subject?.frame_index ?? null,
      row.subject?.track_id ?? null,
      row.subject?.annotation_id ?? null,
      row.subject?.mask_id ?? null,
      row.subject?.prediction_id ?? null,
      row.subject?.model_run_id ?? null,
      row.location.latitude,
      row.location.longitude,
      row.observed_at,
      row.depth_m,
      row.depth_reference,
      row.source_kind,
      row.provenance.source,
      row.provenance.dataset_id,
      row.provenance.model_version,
      // Do not combine components calculated using different scientific methods,
      // processing settings, resolutions or source endpoints, even if their
      // provider, dataset, coordinates and acquisition timestamp match.
      row.provenance.source_url ?? null,
      row.provenance.method ?? null,
      row.provenance.spatial_resolution_m ?? null,
      row.provenance.temporal_resolution_s ?? null,
      row.provenance.processing_parameters ?? null,
      // Components from separate acquisitions must not form a synthetic current.
      row.provenance.acquired_at,
      row.environmental_cache_key,
    ]);
    const group = groups.get(key) ?? { east: [], north: [] };
    group[direction].push(row);
    groups.set(key, group);
  }
  const result: CurrentVector[] = [];
  for (const [key, group] of groups) {
    if (group.east.length !== 1 || group.north.length !== 1) continue;
    const row = group.east[0];
    const east = row.normalized_value;
    const north = group.north[0].normalized_value;
    const speed = Math.hypot(east, north);
    // Finite components can still overflow a derived speed; never map Infinity.
    if (!Number.isFinite(speed)) continue;
    result.push({
      id: key,
      latitude: row.location!.latitude,
      longitude: row.location!.longitude,
      east,
      north,
      eastUncertainty: componentUncertainty(row),
      northUncertainty: componentUncertainty(group.north[0]),
      speed,
      bearing:
        speed === 0
          ? null
          : ((Math.atan2(east, north) * 180) / Math.PI + 360) % 360,
      source: row.provenance.source,
      sourceKind: row.source_kind,
      dataset: row.provenance.dataset_id ?? "unspecified",
      modelVersion: row.provenance.model_version ?? null,
      observedAt: row.observed_at,
      depthM: row.depth_m!,
      recordIds: [row.id, group.north[0].id],
    });
  }
  return result;
}
export function vectorColor(speed: number): string {
  return speed < 0.25
    ? "#2563eb"
    : speed < 0.5
      ? "#08916b"
      : speed < 1
        ? "#b66b0a"
        : "#ca2639";
}
