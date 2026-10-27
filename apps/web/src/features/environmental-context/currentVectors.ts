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
// Processing parameters are JSON objects: property insertion order has no
// scientific meaning. Canonicalize nested keys so equivalent acquisitions
// pair even when imported/exported JSON orders the same fields differently.
// Array order remains significant; do not silently rewrite provider settings.
function canonicalJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJsonValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
        .map(([key, item]) => [key, canonicalJsonValue(item)]),
    );
  }
  return value;
}
// Copernicus records use different variable names/units for uo and vo, but
// all shared grid/run metadata must agree before constructing one vector.
// Otherwise two ensemble members or revised grids could form a false current.
const COMPONENT_METADATA_FIELDS = new Set([
  "provider_variable",
  "provider_unit",
  "standard_name",
]);
function sharedSourceMetadata(row: ScientificRecord): unknown {
  const metadata = row.provenance.source_metadata;
  if (!metadata) return null;
  const sharedEntries = Object.entries(metadata).filter(
    ([key]) => !COMPONENT_METADATA_FIELDS.has(key),
  );
  return canonicalJsonValue(Object.fromEntries(sharedEntries));
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
      canonicalJsonValue(row.provenance.processing_parameters ?? null),
      sharedSourceMetadata(row),
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

/**
 * Export only the selected, QC-compatible vector summaries. This is not a
 * substitute for the immutable component records, whose IDs are included for
 * reproducibility. Missing uncertainty is blank, never interpreted as zero.
 */
export interface CurrentVectorCsvContext {
  cacheKey: string;
  cacheStatus: string;
  fetchedAt: string;
  expiresAt: string;
}
const CURRENT_CSV_COLUMNS = [
  "east_record_id",
  "north_record_id",
  "observed_at_utc",
  "latitude_deg",
  "longitude_deg",
  "depth_m",
  "east_velocity_m_per_s",
  "north_velocity_m_per_s",
  "speed_m_per_s",
  "bearing_deg_true_north",
  "east_uncertainty_m_per_s",
  "east_uncertainty_kind",
  "north_uncertainty_m_per_s",
  "north_uncertainty_kind",
  "source_kind",
  "source",
  "dataset_id",
  "model_version",
  "cache_key",
  "cache_status",
  "cache_fetched_at_utc",
  "cache_expires_at_utc",
  "derived_uncertainty_status",
] as const;

function currentCsvCell(value: string | number | null | undefined): string {
  if (value == null) return "";
  // Provenance text can originate from external datasets. Quote CSV control
  // characters and neutralize spreadsheet formula injection without changing
  // numeric measurements (including negative coordinates and velocities).
  const raw = String(value);
  const safe =
    typeof value === "string" && /^\s*[=+@-]/.test(raw) ? "'" + raw : raw;
  return '"' + safe.replaceAll('"', '""') + '"';
}

export function currentVectorsCsv(
  vectors: CurrentVector[],
  context: CurrentVectorCsvContext,
): string {
  const lines = [...vectors]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((vector) =>
      [
        vector.recordIds[0],
        vector.recordIds[1],
        vector.observedAt,
        vector.latitude,
        vector.longitude,
        vector.depthM,
        vector.east,
        vector.north,
        vector.speed,
        vector.bearing,
        vector.eastUncertainty?.value,
        vector.eastUncertainty?.kind,
        vector.northUncertainty?.value,
        vector.northUncertainty?.kind,
        vector.sourceKind,
        vector.source,
        vector.dataset,
        vector.modelVersion,
        context.cacheKey,
        context.cacheStatus,
        context.fetchedAt,
        context.expiresAt,
        "not_estimated",
      ]
        .map(currentCsvCell)
        .join(","),
    );
  return [CURRENT_CSV_COLUMNS.join(","), ...lines].join("\r\n") + "\r\n";
}
