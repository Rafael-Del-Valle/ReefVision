import { getApiBaseUrl } from "../../runtime";

export class ProviderApiError extends Error {}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, { signal });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as {
        detail?: string | { message?: string; reason?: string };
      };
      if (typeof payload.detail === "string") message = payload.detail;
      if (payload.detail && typeof payload.detail === "object") {
        message = payload.detail.message ?? payload.detail.reason ?? message;
      }
    } catch {
      // Keep the status fallback when the response is not JSON.
    }
    throw new ProviderApiError(message);
  }
  return (await response.json()) as T;
}

async function mutate<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as {
        detail?: string | { message?: string; reason?: string };
      };
      if (typeof payload.detail === "string") message = payload.detail;
      if (payload.detail && typeof payload.detail === "object") {
        message = payload.detail.message ?? payload.detail.reason ?? message;
      }
    } catch {
      // Keep the HTTP fallback.
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

export type ProviderLifecycleState =
  | "ready"
  | "unavailable"
  | "degraded"
  | "loading"
  | "loaded"
  | "failed"
  | "unloaded";

export interface ProviderModelAsset {
  id: string;
  provider_id: string;
  provider_version: string;
  model_id: string;
  architecture: string;
  task: string;
  capabilities: Record<string, boolean>;
  checkpoint_path: string;
  checkpoint_path_kind: "managed" | "trusted_external";
  checkpoint_sha256: string | null;
  checkpoint_size_bytes: number | null;
  checkpoint_format: string;
  source: string;
  revision: string | null;
  required_packages: string[];
  optional_packages: string[];
  supported_devices: string[];
  preferred_device: "auto" | "cpu" | "cuda";
  estimated_vram_bytes: number | null;
  input_types: string[];
  output_types: string[];
  prompt_types: string[];
  supports_training: boolean;
  supports_inference: boolean;
  supports_video: boolean;
  state: ProviderLifecycleState;
  failure_reason: string | null;
  verification: Record<string, unknown>;
  last_health_check: Record<string, unknown>;
  last_health_check_at: string | null;
  last_successful_load_at: string | null;
  last_successful_inference_at: string | null;
  metadata: Record<string, unknown>;
  latest_acceptance_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderModelAssetList {
  items: ProviderModelAsset[];
  total: number;
  limit: number;
  offset: number;
  duplicate_checksum_groups: string[][];
}

export interface ProviderLifecycleAction {
  asset: ProviderModelAsset;
  action: string;
  state: ProviderLifecycleState;
  resolved_device: string | null;
  details: Record<string, unknown>;
  warnings: string[];
}

export interface ProviderAcceptanceRecord {
  id: string;
  run_id: string;
  provider_asset_id: string | null;
  provider_id: string;
  model_id: string;
  checkpoint_sha256: string | null;
  device: string;
  runtime_versions: Record<string, string>;
  load_result: string;
  inference_result: string;
  unload_result: string;
  peak_memory_bytes: number | null;
  execution_time_ms: number;
  warnings: string[];
  failure_reason: string | null;
  test_input_identifier: string;
  validation_kind: "software_acceptance";
  recorded_at: string;
}

export interface ProviderAcceptanceList {
  items: ProviderAcceptanceRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProviderInferenceResult {
  request_id: string;
  provider_id: string;
  model_id: string;
  task: string;
  resolved_device: string;
  outputs: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  warnings: string[];
}

export function discoverProviderModels() {
  return mutate<{ discovered_count: number; warnings: string[] }>(
    "/provider-models/discover",
  );
}

export function listProviderModels(signal?: AbortSignal) {
  return request<ProviderModelAssetList>("/provider-models?limit=200", signal);
}

export function verifyProviderModel(assetId: string) {
  return mutate<ProviderLifecycleAction>(`/provider-models/${assetId}/verify`);
}

export function diagnoseProviderModel(
  assetId: string,
  device: "auto" | "cpu" | "cuda",
) {
  return mutate<ProviderLifecycleAction>(
    `/provider-models/${assetId}/diagnose`,
    { device },
  );
}

export function loadProviderModel(
  assetId: string,
  device: "auto" | "cpu" | "cuda",
) {
  return mutate<ProviderLifecycleAction>(`/provider-models/${assetId}/load`, {
    device,
  });
}

export function healthCheckProviderModel(
  assetId: string,
  payload: {
    device: "auto" | "cpu" | "cuda";
    kind: "metadata" | "load";
    keep_loaded: boolean;
  },
) {
  return mutate<ProviderLifecycleAction>(
    `/provider-models/${assetId}/health-check`,
    payload,
  );
}

export function unloadProviderModel(assetId: string) {
  return mutate<ProviderLifecycleAction>(`/provider-models/${assetId}/unload`);
}

export function listProviderAcceptance(assetId: string, signal?: AbortSignal) {
  const search = new URLSearchParams({ asset_id: assetId, limit: "50" });
  return request<ProviderAcceptanceList>(
    `/provider-acceptance-records?${search}`,
    signal,
  );
}

export function inferProviderModel(
  assetId: string,
  payload: {
    request_id: string;
    image_id: string;
    device: "auto" | "cpu" | "cuda";
    parameters: Record<string, unknown>;
  },
) {
  return mutate<ProviderInferenceResult>(
    `/provider-models/${assetId}/infer`,
    payload,
  );
}

export function cancelProviderRequest(requestId: string) {
  return mutate<{ request_id: string; cancellation_requested: boolean }>(
    `/provider-requests/${requestId}/cancel`,
  );
}
