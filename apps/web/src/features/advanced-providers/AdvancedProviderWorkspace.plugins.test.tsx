import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import {
  scientificConfigurationIssue,
  ScientificNodeControls,
} from "../workflow-graphs/ScientificNodeControls";
import { AdvancedProviderWorkspace } from "./AdvancedProviderWorkspace";

const project = {
  id: "b9a93927-84eb-4d22-bc12-8774aa29ef34",
  name: "Plugin study",
} as Project;
const pluginId = "9f2bd840-9009-4898-bddb-af192ae50dc5";
const imageId = "3a4fce54-2631-4fdb-baa3-b4d7a53b088f";
const secondImage = "dd66e84c-9983-405a-bd83-e25835ac14c5";
const packageSha = "a".repeat(64);
const imageSha = "b".repeat(64);
const pluginPackage = {
  manifest: {
    manifest_version: 2,
    abi: "reefvision.rgb-summary/1",
    plugin_id: "reefvision.green-fraction",
    version: "1.0.0",
    display_name: "Green fraction",
    description: "Measure the mean green channel as a fraction",
    license: "MIT",
    permissions: ["read_image_rgb_summary"],
    quantity: "green_fraction",
    unit: "1",
    module_sha256: "c".repeat(64),
  },
  module_base64: "AGFzbQEAAAA=",
};

const pins = {
  plugin_record_id: pluginId,
  package_sha256: packageSha,
  image_id: imageId,
  image_sha256: imageSha,
};

const receipt = {
  id: "13137df4-973a-44d3-9b46-23708989e380",
  variable: "green_fraction",
  value: 0.25,
  unit: "1",
  qc: "unassessed",
  subject: { image_id: imageId },
  content_sha256: "e".repeat(64),
  provenance: {
    processing_parameters: {
      ...pins,
      plugin_id: "reefvision.green-fraction",
      plugin_version: "1.0.0",
      module_sha256: pluginPackage.manifest.module_sha256,
    },
  },
};

let installed: boolean;
let enabled: boolean;
let available: boolean;
let installError: string | undefined;
let measurements: object[];
const writes: Array<{ path: string; body: unknown }> = [];

const response = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const open = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AdvancedProviderWorkspace
        project={project}
        onOpenPluginWorkflow={open}
      />
    </QueryClientProvider>,
  );
  return open;
}

beforeEach(() => {
  writes.length = 0;
  installed = false;
  enabled = false;
  available = true;
  installError = undefined;
  measurements = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      const path = new URL(input).pathname.replace(/^\/api\/v1/, "");
      const method = options?.method ?? "GET";
      const record = () => ({
        id: pluginId,
        manifest: pluginPackage.manifest,
        package_sha256: packageSha,
        enabled,
        available,
        reason: available
          ? null
          : "Worker runtime unavailable. Install a supported ReefVision distribution.",
      });
      if (method !== "GET")
        writes.push({ path, body: JSON.parse(String(options?.body)) });
      if (path === "/advanced-providers/manifests") return response([]);
      if (path.endsWith("/model-catalog")) return response({ models: [] });
      if (path === "/plugins" && method === "GET")
        return response({
          items: installed ? [record()] : [],
          total: Number(installed),
        });
      if (path === "/plugins" && method === "POST") {
        if (installError) return response({ detail: installError }, 400);
        installed = true;
        return response(record(), 201);
      }
      if (path === `/plugins/${pluginId}` && method === "PATCH") {
        enabled = Boolean(JSON.parse(String(options?.body)).enabled);
        return response(record());
      }
      if (path === `/projects/${project.id}/images`)
        return response({
          items: [
            { id: imageId, original_filename: "reef-first.png" },
            { id: secondImage, original_filename: "reef-second.png" },
          ],
          total: 2,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      if (path === `/images/${imageId}`)
        return response({
          id: imageId,
          project_id: project.id,
          original_filename: "reef-first.png",
          sha256: imageSha,
        });
      if (path === `/images/${secondImage}`)
        return new Response("{}", { status: 404 });
      if (path === `/projects/${project.id}/plugin-measurements`) {
        if (method === "GET")
          return response({ items: measurements, total: measurements.length });
        measurements.push(receipt);
        return response(receipt, 201);
      }
      if (path.endsWith("/workflow-graphs"))
        return response({ id: "saved-graph" }, 201);
      throw new Error(`Unexpected request ${method} ${path}`);
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("Local plugins in Providers", () => {
  it("installs and explicitly enables a package, then pins only the selected managed image and plugin bytes", async () => {
    const open = renderWorkspace();
    expect(screen.getByRole("heading", { name: "Providers" })).toBeVisible();
    const panel = screen.getByRole("region", { name: "Local plugins" });
    expect(
      within(panel).getByRole("link", { name: "Download sample plugin" }),
    ).toHaveAttribute("download", "green-fraction.rvplugin.json");
    expect(writes).toEqual([]);
    const chooser = within(panel).getByLabelText("Plugin package (JSON)");
    fireEvent.change(chooser, {
      target: {
        files: [
          new File(
            [JSON.stringify(pluginPackage)],
            "green-fraction.rvplugin.json",
            { type: "application/json" },
          ),
        ],
      },
    });
    fireEvent.click(
      within(panel).getByRole("button", {
        name: "Install plugin",
      }),
    );
    const enable = await within(panel).findByRole("button", {
      name: "Enable Green fraction 1.0.0",
    });
    expect(writes[0]).toEqual({ path: "/plugins", body: pluginPackage });
    await within(panel).findByRole("option", {
      name: "Green fraction 1.0.0 · Disabled",
    });
    fireEvent.click(enable);
    expect(
      await within(panel).findByRole("button", {
        name: "Disable Green fraction 1.0.0",
      }),
    ).toBeVisible();
    expect(writes[1]).toEqual({
      path: `/plugins/${pluginId}`,
      body: { package_sha256: packageSha, enabled: true },
    });

    fireEvent.change(within(panel).getByLabelText("Plugin version"), {
      target: { value: pluginId },
    });
    fireEvent.change(within(panel).getByLabelText("Source image"), {
      target: { value: imageId },
    });
    const run = within(panel).getByRole("button", { name: "Run measurement" });
    await waitFor(() => expect(run).toBeEnabled());
    fireEvent.click(run);
    expect(
      await within(panel).findByText("0.25 1", { exact: true }),
    ).toBeVisible();
    expect(writes[2]).toEqual({
      path: `/projects/${project.id}/plugin-measurements`,
      body: pins,
    });

    fireEvent.click(
      within(panel).getByRole("button", { name: "Open in Workflow Builder" }),
    );
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith({ id: "saved-graph" }),
    );
    expect(writes[3]).toMatchObject({
      body: {
        graph: {
          nodes: expect.arrayContaining([
            expect.objectContaining({
              node_type: "plugin_image_measurement",
              parameters: pins,
            }),
            expect.objectContaining({ node_type: "measurement_review_gate" }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source_node_id: "measure-image",
              source_port_id: "measurement",
              target_node_id: "review-measurement",
              target_port_id: "measurement",
            }),
          ]),
        },
      },
    });
    const pause = within(panel).getByRole("checkbox", {
      name: "Pause for measurement review",
    });
    expect(pause).toBeChecked();
    fireEvent.click(pause);
    fireEvent.click(
      within(panel).getByRole("button", { name: "Open in Workflow Builder" }),
    );
    await waitFor(() => expect(open).toHaveBeenCalledTimes(2));
    expect(writes[4]).toMatchObject({
      body: {
        graph: {
          nodes: expect.not.arrayContaining([
            expect.objectContaining({ node_type: "measurement_review_gate" }),
          ]),
        },
      },
    });

    fireEvent.change(within(panel).getByLabelText("Source image"), {
      target: { value: secondImage },
    });
    expect(run).toBeDisabled();
    fireEvent.click(run);
    expect(writes).toHaveLength(5);
  });

  it("keeps unavailable versions and saved observations visible and explains a rejected install", async () => {
    installed = true;
    enabled = true;
    available = false;
    measurements = [receipt];
    installError = "Unsupported plugin manifest version";
    renderWorkspace();
    const panel = screen.getByRole("region", { name: "Local plugins" });
    expect(
      await within(panel).findByText(/Worker runtime unavailable/),
    ).toBeVisible();
    expect(
      await within(panel).findByText("0.25 1", { exact: true }),
    ).toBeVisible();
    expect(
      within(panel).getByRole("option", {
        name: "Green fraction 1.0.0 · Unavailable",
      }),
    ).toBeDisabled();
    expect(
      within(panel).getByRole("button", { name: "Run measurement" }),
    ).toBeDisabled();
    fireEvent.change(within(panel).getByLabelText("Plugin package (JSON)"), {
      target: {
        files: [
          new File(
            [JSON.stringify(pluginPackage)],
            "unsupported.rvplugin.json",
          ),
        ],
      },
    });
    fireEvent.click(
      within(panel).getByRole("button", {
        name: "Install plugin",
      }),
    );
    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      installError,
    );
    expect(within(panel).getByText("0.25 1", { exact: true })).toBeVisible();
  });

  it("keeps a guided graph's original content pins when current bytes differ", async () => {
    installed = true;
    enabled = true;
    const update = vi.fn();
    const stale = {
      ...pins,
      package_sha256: "d".repeat(64),
      image_sha256: "e".repeat(64),
    };
    expect(
      scientificConfigurationIssue("plugin_image_measurement", {
        image_id: imageId,
      }),
    ).toMatch(/source image/i);
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ScientificNodeControls
          nodeType="plugin_image_measurement"
          projectId={project.id}
          parameters={stale}
          onChange={update}
        />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText(/original image digest differs/),
    ).toBeVisible();
    expect(
      await screen.findByText(/selected plugin version changed/),
    ).toBeVisible();
    expect(screen.getByText(stale.package_sha256)).toBeVisible();
    expect(screen.getByText(stale.image_sha256)).toBeVisible();
    expect(update).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Plugin version"), {
      target: { value: pluginId },
    });
    expect(update).toHaveBeenCalledWith({
      ...stale,
      package_sha256: packageSha,
    });
  });
});
