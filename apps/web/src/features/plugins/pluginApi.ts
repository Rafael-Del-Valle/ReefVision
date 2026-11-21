import { request, type ProjectImage } from "../../api/client";
import type {
  ScientificRecord,
  ScientificRecordPage,
} from "../environmental-context/environmentalContextApi";

export interface PluginManifest {
  manifest_version: 2;
  abi: "reefvision.rgb-summary/1";
  plugin_id: string;
  version: string;
  display_name: string;
  description: string;
  license: string;
  permissions: ["read_image_rgb_summary"];
  quantity: string;
  unit: "1" | "%";
  module_sha256: string;
}

export interface PluginRecord {
  id: string;
  manifest: PluginManifest;
  package_sha256: string;
  enabled: boolean;
  available: boolean;
  reason: string | null;
}

export interface PluginMeasurementInput {
  plugin_record_id: string;
  package_sha256: string;
  image_id: string;
  image_sha256: string;
}

export const pluginCatalogKey = ["local-plugins"] as const;
export const pluginPageSize = 24;

export function listPlugins(offset: number, signal?: AbortSignal) {
  return request<{ items: PluginRecord[]; total: number }>(
    `/plugins?limit=${pluginPageSize}&offset=${offset}`,
    { signal },
  );
}

export function installPlugin(bundle: unknown) {
  return request<PluginRecord>("/plugins", {
    method: "POST",
    body: JSON.stringify(bundle),
  });
}

export function setPluginEnabled(record: PluginRecord, enabled: boolean) {
  return request<PluginRecord>(`/plugins/${encodeURIComponent(record.id)}`, {
    method: "PATCH",
    body: JSON.stringify({ package_sha256: record.package_sha256, enabled }),
  });
}

export function readPluginSourceImage(imageId: string, signal?: AbortSignal) {
  return request<
    Pick<ProjectImage, "id" | "project_id" | "sha256" | "original_filename">
  >(`/images/${encodeURIComponent(imageId)}`, { signal });
}

export const pluginMeasurementsKey = (projectId: string) =>
  ["plugin-measurements", projectId] as const;

export function listPluginMeasurements(
  projectId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return request<ScientificRecordPage>(
    `/projects/${encodeURIComponent(projectId)}/plugin-measurements?limit=${pluginPageSize}&offset=${offset}`,
    { signal },
  );
}

export function measurePluginImage(
  projectId: string,
  input: PluginMeasurementInput,
) {
  return request<ScientificRecord>(
    `/projects/${encodeURIComponent(projectId)}/plugin-measurements`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export const pluginLabel = (record: PluginRecord) =>
  `${record.manifest.display_name} ${record.manifest.version}`;

export const pluginAvailability = (record: PluginRecord) =>
  !record.available ? "Unavailable" : record.enabled ? "Enabled" : "Disabled";

export function pluginMeasurementPins(
  parameters: Record<string, unknown>,
): Partial<PluginMeasurementInput> {
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  return {
    plugin_record_id: text(parameters.plugin_record_id),
    package_sha256: text(parameters.package_sha256),
    image_id: text(parameters.image_id),
    image_sha256: text(parameters.image_sha256),
  };
}

export function completePluginMeasurementPins(
  value: Partial<PluginMeasurementInput>,
): value is PluginMeasurementInput {
  const digest = /^[0-9a-f]{64}$/;
  const id = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  return (
    id.test(value.plugin_record_id ?? "") &&
    id.test(value.image_id ?? "") &&
    digest.test(value.package_sha256 ?? "") &&
    digest.test(value.image_sha256 ?? "")
  );
}
