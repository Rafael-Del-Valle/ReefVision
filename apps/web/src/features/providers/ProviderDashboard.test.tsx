import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  compareProviderBenchmarks,
  getProviderCapabilities,
  type ProviderCapability,
} from "./api";
import { ProviderDashboard } from "./ProviderDashboard";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getProviderCapabilities: vi.fn(),
    compareProviderBenchmarks: vi.fn(),
  };
});

function provider(
  overrides: Partial<ProviderCapability> &
    Pick<ProviderCapability, "provider_id" | "display_name">,
): ProviderCapability {
  return {
    provider_id: overrides.provider_id,
    display_name: overrides.display_name,
    description: "Provider acceptance fixture",
    health: "ready",
    supported_tasks: ["segment"],
    supported_prompt_types: ["positive_point", "negative_point"],
    supports_training: false,
    supports_inference: true,
    supports_video: false,
    supports_batching: true,
    supports_cpu: true,
    supports_cuda: false,
    supports_mixed_precision: false,
    supports_offline_import: true,
    provider_version: "1.0",
    dependencies: [],
    devices: [
      {
        device_id: "cpu",
        kind: "cpu",
        display_name: "Test CPU",
        available: true,
        total_memory_bytes: null,
        free_memory_bytes: null,
        compute_capability: null,
        supports_mixed_precision: false,
        warnings: [],
      },
    ],
    model_assets: [],
    estimated_vram_bytes: {},
    recent_benchmarks: [],
    warnings: [],
    remediation: [],
    ...overrides,
  };
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProviderDashboard />
    </QueryClientProvider>,
  );
}

describe("ProviderDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getProviderCapabilities).mockResolvedValue({
      generated_at: "2026-07-19T12:00:00Z",
      reefvision_version: "1.6.0",
      providers: [
        provider({ provider_id: "mock", display_name: "Mock provider" }),
        provider({
          provider_id: "sam2",
          display_name: "SAM 2",
          health: "unavailable",
          supports_cpu: false,
          supports_cuda: true,
          supports_video: true,
          dependencies: [
            {
              package: "sam2",
              import_name: "sam2",
              installed: false,
              version: null,
              required: true,
              minimum_version: null,
              message: "Install the optional sam2 provider dependency.",
            },
          ],
          warnings: ["Required optional packages are not installed: sam2"],
          remediation: ["Install the provider from the Model Catalog."],
        }),
      ],
    });
    vi.mocked(compareProviderBenchmarks).mockResolvedValue({
      records: [
        {
          provider_id: "mock",
          model_id: null,
          device_id: "cpu",
          task: "segment",
          input_width: 640,
          input_height: 640,
          batch_size: 1,
          sample_count: 3,
          warmup_count: 1,
          mean_latency_ms: 12,
          median_latency_ms: 12,
          p95_latency_ms: 13.8,
          throughput_per_second: 83.33,
          peak_ram_bytes: 1_048_576,
          peak_vram_bytes: null,
          quality_metrics: { mean_iou: 0.75 },
          parameters: {},
          recorded_at: "2026-07-19T12:05:00Z",
        },
      ],
      fastest_record: null,
      lowest_vram_record: null,
      warnings: [],
    });
  });

  it("renders provider health, benchmark history, and provider remediation", async () => {
    const user = userEvent.setup();
    renderDashboard();

    expect(await screen.findByText("1 ready")).toBeInTheDocument();
    expect(screen.getByText("1 unavailable")).toBeInTheDocument();
    expect(screen.getByText(/83.33\/s/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /SAM 2/i }));

    expect(
      await screen.findByText(/Required optional packages are not installed: sam2/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Install the provider from the Model Catalog/i),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(compareProviderBenchmarks).toHaveBeenCalledWith(
        "sam2",
        undefined,
        expect.anything(),
      ),
    );
  });
});
