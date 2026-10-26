import type { ScientificRecord } from "./environmentalContextApi";
export interface CurrentVector {
  id: string;
  latitude: number;
  longitude: number;
  speed: number;
  bearing: number | null;
  east: number;
  north: number;
  source: string;
  sourceKind: string;
  dataset: string;
  modelVersion: string | null;
  observedAt: string;
  depthM: number;
  recordIds: string[];
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
      row.depth_m == null ||
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
      row.location.latitude,
      row.location.longitude,
      row.observed_at,
      row.depth_m,
      row.depth_reference,
      row.source_kind,
      row.provenance.source,
      row.provenance.dataset_id,
      row.provenance.model_version,
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
    result.push({
      id: key,
      latitude: row.location!.latitude,
      longitude: row.location!.longitude,
      east,
      north,
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
