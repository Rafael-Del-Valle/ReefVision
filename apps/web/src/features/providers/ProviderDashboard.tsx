import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  compareProviderBenchmarks,
  getProviderCapabilities,
  type ProviderCapability,
  type ProviderHealth,
} from "./api";

function bytesLabel(value: number | null | undefined): string {
  if (value == null) return "Unknown";
  if (value >= 1_073_741_824) return `${(value / 1_073_741_824).toFixed(2)} GiB`;
  if (value >= 1_048_576) return `${(value / 1_048_576).toFixed(1)} MiB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${value} B`;
}

function healthLabel(health: ProviderHealth): string {
  if (health === "ready") return "Ready";
  if (health === "degraded") return "Needs attention";
  return "Unavailable";
}

function ProviderSummaryCard({
  provider,
  selected,
  onSelect,
}: {
  provider: ProviderCapability;
  selected: boolean;
  onSelect: () => void;
}) {
  const installedDependencies = provider.dependencies.filter(
    (dependency) => dependency.installed,
  ).length;
  return (
    <button
      type="button"
      className={`project-card ${selected ? "selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <strong>{provider.display_name}</strong>
      <span>{healthLabel(provider.health)}</span>
      <small>
        {installedDependencies}/{provider.dependencies.length} dependencies ·{" "}
        {provider.model_assets.length} registered assets
      </small>
    </button>
  );
}

export function ProviderDashboard() {
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [taskFilter, setTaskFilter] = useState("");

  const capabilities = useQuery({
    queryKey: ["provider-capabilities"],
    queryFn: ({ signal }) => getProviderCapabilities(signal),
    refetchInterval: 30_000,
  });

  const providers = capabilities.data?.providers ?? [];
  useEffect(() => {
    if (!selectedProviderId && providers.length > 0) {
      setSelectedProviderId(providers[0].provider_id);
    }
  }, [providers, selectedProviderId]);

  const selectedProvider = useMemo(
    () =>
      providers.find((provider) => provider.provider_id === selectedProviderId) ??
      null,
    [providers, selectedProviderId],
  );

  useEffect(() => {
    if (
      taskFilter &&
      selectedProvider &&
      !selectedProvider.supported_tasks.includes(taskFilter)
    ) {
      setTaskFilter("");
    }
  }, [selectedProvider, taskFilter]);

  const benchmarks = useQuery({
    queryKey: ["provider-benchmarks", selectedProviderId, taskFilter],
    queryFn: ({ signal }) =>
      compareProviderBenchmarks(
        selectedProviderId || undefined,
        taskFilter || undefined,
        signal,
      ),
    enabled: Boolean(selectedProviderId),
    refetchInterval: 30_000,
  });

  const healthCounts = useMemo(
    () =>
      providers.reduce<Record<ProviderHealth, number>>(
        (counts, provider) => {
          counts[provider.health] += 1;
          return counts;
        },
        { ready: 0, degraded: 0, unavailable: 0 },
      ),
    [providers],
  );

  if (capabilities.isPending) {
    return (
      <section className="dashboard-panel">
        <div className="empty-state">
          <h3>Inspecting provider health</h3>
          <p>Checking dependencies, devices, model files, and stored benchmarks.</p>
        </div>
      </section>
    );
  }

  if (capabilities.error) {
    return (
      <section className="dashboard-panel">
        <div className="empty-state">
          <h3>Provider health unavailable</h3>
          <p className="form-error">{capabilities.error.message}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="dashboard-panel" data-testid="provider-dashboard">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 8 runtime acceptance</p>
          <h3>Provider health and benchmarks</h3>
          <span>
            Inspect optional packages, execution devices, model integrity, prompt
            support, and real-hardware benchmark records.
          </span>
        </div>
        <button
          type="button"
          className="secondary"
          disabled={capabilities.isFetching}
          onClick={() => void capabilities.refetch()}
        >
          {capabilities.isFetching ? "Refreshing..." : "Refresh health"}
        </button>
      </div>

      <div className="version-preview-metrics">
        <span>{healthCounts.ready} ready</span>
        <span>{healthCounts.degraded} degraded</span>
        <span>{healthCounts.unavailable} unavailable</span>
        <span>ReefVision {capabilities.data?.reefvision_version}</span>
      </div>

      <div className="dashboard-layout">
        <div className="dashboard-sidebar">
          <article className="dashboard-card">
            <p className="eyebrow">Provider registry</p>
            <div className="project-list">
              {providers.map((provider) => (
                <ProviderSummaryCard
                  key={provider.provider_id}
                  provider={provider}
                  selected={provider.provider_id === selectedProviderId}
                  onSelect={() => setSelectedProviderId(provider.provider_id)}
                />
              ))}
            </div>
          </article>
        </div>

        <div className="dashboard-main">
          {selectedProvider && (
            <>
              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">{selectedProvider.provider_id}</p>
                    <h4>{selectedProvider.display_name}</h4>
                    <p>{selectedProvider.description}</p>
                  </div>
                  <span className="status-chip">
                    {healthLabel(selectedProvider.health)}
                  </span>
                </div>
                <div className="version-preview-metrics">
                  <span>
                    Tasks: {selectedProvider.supported_tasks.join(", ") || "None"}
                  </span>
                  <span>
                    Prompts:{" "}
                    {selectedProvider.supported_prompt_types.join(", ") || "None"}
                  </span>
                  <span>Training {selectedProvider.supports_training ? "yes" : "no"}</span>
                  <span>Video {selectedProvider.supports_video ? "yes" : "no"}</span>
                  <span>CUDA {selectedProvider.supports_cuda ? "yes" : "no"}</span>
                </div>
                {selectedProvider.warnings.map((warning) => (
                  <p key={warning} className="form-warning">
                    {warning}
                  </p>
                ))}
                {selectedProvider.remediation.map((item) => (
                  <p key={item} className="annotation-helper">
                    {item}
                  </p>
                ))}
              </article>

              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Runtime inventory</p>
                    <h4>Dependencies and devices</h4>
                  </div>
                </div>
                <div className="dashboard-list">
                  {selectedProvider.dependencies.map((dependency) => (
                    <div key={dependency.package} className="dashboard-row">
                      <div>
                        <strong>{dependency.package}</strong>
                        <p>{dependency.message ?? "Dependency is installed."}</p>
                      </div>
                      <span>
                        {dependency.installed
                          ? dependency.version ?? "Installed"
                          : dependency.required
                            ? "Missing"
                            : "Optional"}
                      </span>
                    </div>
                  ))}
                  {selectedProvider.dependencies.length === 0 && (
                    <p>No optional package dependencies are required.</p>
                  )}
                  {selectedProvider.devices.map((device) => (
                    <div key={device.device_id} className="dashboard-row">
                      <div>
                        <strong>{device.display_name}</strong>
                        <p>
                          {device.kind.toUpperCase()} · {device.device_id}
                          {device.compute_capability
                            ? ` · compute ${device.compute_capability}`
                            : ""}
                        </p>
                      </div>
                      <span>
                        {device.free_memory_bytes == null
                          ? bytesLabel(device.total_memory_bytes)
                          : `${bytesLabel(device.free_memory_bytes)} free`}
                      </span>
                    </div>
                  ))}
                </div>
              </article>

              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Registered checkpoints</p>
                    <h4>Model integrity</h4>
                  </div>
                  <span>{selectedProvider.model_assets.length} assets</span>
                </div>
                <div className="dashboard-list">
                  {selectedProvider.model_assets.map((asset) => (
                    <div key={asset.model_id} className="dashboard-row">
                      <div>
                        <strong>{asset.name}</strong>
                        <p>
                          {asset.task} · {asset.managed_path}
                        </p>
                        {asset.messages.map((message) => (
                          <small key={message}>{message}</small>
                        ))}
                      </div>
                      <span>
                        {!asset.exists
                          ? "Missing"
                          : asset.checksum_verified === false
                            ? "Checksum mismatch"
                            : asset.compatible
                              ? "Ready"
                              : "Task mismatch"}
                      </span>
                    </div>
                  ))}
                  {selectedProvider.model_assets.length === 0 && (
                    <p>No registered checkpoints use this provider.</p>
                  )}
                </div>
              </article>

              <article className="dashboard-card">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Persisted acceptance results</p>
                    <h4>Benchmark comparison</h4>
                  </div>
                  <label>
                    Task
                    <select
                      value={taskFilter}
                      onChange={(event) => setTaskFilter(event.target.value)}
                    >
                      <option value="">All tasks</option>
                      {selectedProvider.supported_tasks.map((task) => (
                        <option key={task} value={task}>
                          {task}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {benchmarks.error && (
                  <p className="form-error">{benchmarks.error.message}</p>
                )}
                {benchmarks.data?.warnings.map((warning) => (
                  <p key={warning} className="annotation-helper">
                    {warning}
                  </p>
                ))}
                <div className="dashboard-list">
                  {benchmarks.data?.records.map((record) => (
                    <div
                      key={`${record.recorded_at}-${record.device_id}-${record.task}`}
                      className="dashboard-row"
                    >
                      <div>
                        <strong>
                          {record.task} · {record.device_id}
                        </strong>
                        <p>
                          {record.input_width}×{record.input_height} · batch{" "}
                          {record.batch_size} · {record.sample_count} samples
                        </p>
                        <small>{new Date(record.recorded_at).toLocaleString()}</small>
                      </div>
                      <span>
                        {record.throughput_per_second.toFixed(2)}/s · p95{" "}
                        {record.p95_latency_ms.toFixed(2)} ms · VRAM{" "}
                        {bytesLabel(record.peak_vram_bytes)}
                      </span>
                    </div>
                  ))}
                </div>
              </article>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
