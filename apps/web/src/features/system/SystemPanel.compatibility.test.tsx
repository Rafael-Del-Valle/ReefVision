import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { SystemPanel } from "./SystemPanel";

function renderStatus(failRuntime = false) {
  const sources: Record<string, unknown> = {
    "/system/version": {
      application_version: "2.0.0",
      backup_format_version: "1.0",
      environment: "production",
      current_schema_revision: "current",
      expected_schema_revision: "current",
    },
    "/system/compatibility": {
      schema_status: "up_to_date",
      compatible_for_read_write: true,
      pending_revisions: [],
      details: [],
    },
    "/system/compatibility/machine": {
      operating_system: "Windows",
      os_release: "11",
      os_version: "10.0.26300",
      architecture: "AMD64",
      packaged_backend: true,
    },
    "/system/logs/location": { files: [] },
    "/system/command-shortcuts": { notes: [] },
    "/backups": [],
    "/runtime-providers/status": [
      {
        runtime_id: "pytorch",
        display_name: "PyTorch",
        package_name: "torch",
        package_version: "2.5.1+cu121",
        available: true,
        supports_cpu: true,
        supports_cuda: true,
        cuda_available: false,
        notes: [],
      },
      {
        runtime_id: "onnxruntime",
        display_name: "ONNX Runtime",
        available: true,
        package_version: "1.20.1",
        supports_cpu: true,
        supports_cuda: false,
        notes: ["ONNX model execution is not enabled in this build."],
      },
    ],
    "/model-providers": [
      {
        provider_id: "sleap_nn",
        display_name: "SLEAP",
        availability_status: "retired_license_audit",
        availability_reason: "Archived registrations remain readable.",
        supported_tasks: [],
      },
    ],
    "/pose-interoperability/runtime": {
      available: false,
      required_version: "0.9.2",
      installed_version: null,
      reason: "NWB requires the optional codec.",
    },
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input).split("/api/v1").at(-1)!;
    const refused = failRuntime && path === "/runtime-providers/status";
    return new Response(JSON.stringify(refused ? {} : sources[path]), {
      status: refused ? 503 : 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <SystemPanel />
    </QueryClientProvider>,
  );
  return () => {
    view.unmount();
    client.clear();
  };
}

afterEach(() => vi.restoreAllMocks());

it("reports detected compatibility and separates prior exact qualification from live capabilities", async () => {
  const unmount = renderStatus();
  const section = await screen.findByRole("region", {
    name: "Diagnostics and compatibility",
  });
  expect(
    await within(section).findByText("Windows 11 · 10.0.26300"),
  ).toBeVisible();
  expect(await within(section).findByText(/CUDA unavailable/)).toBeVisible();
  expect(within(section).getByText(/Select CPU/)).toBeVisible();
  expect(
    within(section).getByText(/ONNX model execution is not enabled/),
  ).toBeVisible();
  expect(
    await within(section).findByText(/NWB requires the optional codec/),
  ).toBeVisible();
  expect(within(section).getByText(/Use COCO or DeepLabCut CSV/)).toBeVisible();

  fireEvent.click(
    within(section).getByText("Model provider status", { exact: true }),
  );
  expect(await within(section).findByText("Retired")).toBeVisible();
  expect(
    within(section).getByText("Archived registrations remain readable."),
  ).toBeVisible();
  fireEvent.click(
    within(section).getByText("Previously tested Windows configurations", {
      exact: true,
    }),
  );
  expect(
    within(section).getByText("ReefVision 1.8.0 original MSI"),
  ).toBeVisible();
  expect(within(section).getByText(/RTX 3090/)).toBeVisible();
  unmount();
});

it("retains on-machine and format answers when the runtime probe fails", async () => {
  const unmount = renderStatus(true);
  const section = await screen.findByRole("region", {
    name: "Diagnostics and compatibility",
  });
  expect(
    await within(section).findByText(/Could not check execution runtimes/),
  ).toBeVisible();
  expect(
    await within(section).findByText("Windows 11 · 10.0.26300"),
  ).toBeVisible();
  expect(
    await within(section).findByText(/Use COCO or DeepLabCut CSV/),
  ).toBeVisible();
  unmount();
});
