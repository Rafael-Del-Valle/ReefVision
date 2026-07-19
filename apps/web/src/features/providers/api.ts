import { getApiBaseUrl } from "../../runtime";

export class ProviderApiError extends Error {}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, { signal });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the status fallback when the response is not JSON.
    }
    throw new ProviderApiError(message);
  }
  return (await response.json()) as T;
}

export type ProviderHealth = "ready" | "degraded" | "unavailable";

export interface ProviderDependencyStatus {
  package: string;
  import_name: string;
  installed: boolean;
  version: string | null;
  required: boolean;
  minimum_version: string | null;
  message: string | null;
}

export interface ProviderDeviceStatus {
  device_id: string;
  kind: "cpu" | "cuda" | "mps" | "directml" | "unknown";
  display_name: string;
  available: boolean;
  total_memory_bytes: number | null;
  free_memory_bytes: number | null;
  compute_capability: string | null;
  supports_mixed_precision: boolean;
  warnings: string[];
}

export interface ProviderModelAssetStatus {
  model_id: string;
  name: string;
  task: string;
  managed_path: string;
  expected_sha256: string | null;
  observed_sha256: string | null;
  checksum_verified: boolean | null;
  exists: boolean;
  size_bytes: number | null;
  compatible: boolean;
  messages: string[];
}

export interface ProviderBenchmarkRecord {
  provider_id: string;
  model_id: string | null;
  device_id: string;
  task: string;
  input_width: number;
  input_height: number;
  batch_size: number;
  sample_count: number;
  warmup_count: number;
  mean_latency_ms: number;
  median_latency_ms: number;
  p95_latency_ms: number;
  throughput_per_second: number;
  peak_ram_bytes: number | null;
  peak_vram_bytes: number | null;
  quality_metrics: Record<string, number>;
  parameters: Record<string, unknown>;
  recorded_at: string;
}

export interface ProviderCapability {
  provider_id: string;
  display_name: string;
  description: string;
  health: ProviderHealth;
  supported_tasks: string[];
  supported_prompt_types: string[];
  supports_training: boolean;
  supports_inference: boolean;
  supports_video: boolean;
  supports_batching: boolean;
  supports_cpu: boolean;
  supports_cuda: boolean;
  supports_mixed_precision: boolean;
  supports_offline_import: boolean;
  provider_version: string | null;
  dependencies: ProviderDependencyStatus[];
  devices: ProviderDeviceStatus[];
  model_assets: ProviderModelAssetStatus[];
  estimated_vram_bytes: Record<string, number>;
  recent_benchmarks: ProviderBenchmarkRecord[];
  warnings: string[];
  remediation: string[];
}

export interface ProviderCapabilityList {
  generated_at: string;
  reefvision_version: string;
  providers: ProviderCapability[];
}

export interface ProviderBenchmarkComparison {
  records: ProviderBenchmarkRecord[];
  fastest_record: ProviderBenchmarkRecord | null;
  lowest_vram_record: ProviderBenchmarkRecord | null;
  warnings: string[];
}

export function getProviderCapabilities(signal?: AbortSignal) {
  return request<ProviderCapabilityList>("/provider-capabilities", signal);
}

export function compareProviderBenchmarks(
  providerId?: string,
  task?: string,
  signal?: AbortSignal,
) {
  const search = new URLSearchParams();
  if (providerId) search.set("provider_id", providerId);
  if (task) search.set("task", task);
  const suffix = search.size > 0 ? `?${search}` : "";
  return request<ProviderBenchmarkComparison>(
    `/provider-benchmarks/compare${suffix}`,
    signal,
  );
}
