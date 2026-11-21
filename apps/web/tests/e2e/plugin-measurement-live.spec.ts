import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";

import type { ProjectImage } from "../../src/api/client";
import type {
  ScientificRecord,
  ScientificRecordPage,
} from "../../src/features/environmental-context/environmentalContextApi";
import type { PluginRecord } from "../../src/features/plugins/pluginApi";
import type {
  WorkflowGraphRecord,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

// A generated 3×2 RGB original with green values 0, 51, 102, 153, 204, and 255.
const original = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAIAAAASFvFNAAAAHElEQVR4nGPkZmBlM2ZiM2ZlEZnJy2XMzmbMAgAPggHKzuzZ0gAAAABJRU5ErkJggg==",
  "base64",
);
const sourceFilename = "Generated RGB original.png";
const packageFilename = "green-fraction.rvplugin.json";
const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");

async function decode<T>(
  response: Response | APIResponse,
  status: number,
): Promise<T> {
  expect(response.status(), await response.text()).toBe(status);
  return response.json() as Promise<T>;
}

function responseFor(
  page: Page,
  url: string,
  method: "POST" | "PATCH" = "POST",
) {
  return page.waitForResponse(
    (response) =>
      response.url() === url && response.request().method() === method,
  );
}

test("installs a local plugin and replays the pinned image measurement twice", async ({
  desktop,
}, info) => {
  test.setTimeout(160_000);
  const { page, api, web, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  const packagePath =
    process.env.REEFVISION_PLUGIN_TEST_PACKAGE ??
    resolve(process.cwd(), "../../examples/plugins", packageFilename);
  const bundle = await readFile(packagePath);
  const manifest = JSON.parse(bundle.toString()).manifest;
  const unsupported = Buffer.from(
    JSON.stringify({
      ...JSON.parse(bundle.toString()),
      manifest: { ...manifest, manifest_version: 3 },
    }),
  );
  const imageSha = sha256(original);
  expect(imageSha).toBe(
    "1f5a78f96eab21377ff77e71ac971e3c73e9fa843223bebb62c67c15d64546c5",
  );

  const webVersion = JSON.parse(await readFile("package.json", "utf8")).version;
  await page.addInitScript(
    (versions) => {
      for (const version of versions) {
        localStorage.setItem(
          `reefvision.onboarding.dismissed.${version}`,
          "true",
        );
      }
    },
    [runtime.application_version, webVersion],
  );
  const title = `Plugin measurement witness ${randomUUID().slice(0, 8)}`;
  const project = await decode<{ id: string }>(
    await page.request.post(`${api}/projects`, {
      data: { name: title, template: "blank" },
    }),
    201,
  );
  const base = `${api}/projects/${project.id}`;
  const imported = await decode<{ successful: [{ image_id: string }] }>(
    await page.request.post(`${base}/imports/images`, {
      multipart: {
        files: {
          name: sourceFilename,
          mimeType: "image/png",
          buffer: original,
        },
      },
    }),
    200,
  );
  const image = await decode<ProjectImage>(
    await page.request.get(`${api}/images/${imported.successful[0].image_id}`),
    200,
  );
  expect(image).toMatchObject({
    project_id: project.id,
    sha256: imageSha,
    width_px: 3,
    height_px: 2,
  });

  async function openProject() {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${title}`, exact: true })
      .click();
  }
  async function openPlugins() {
    await openProject();
    await page.getByRole("tab", { name: "Models & AI", exact: true }).click();
    await page
      .getByRole("tab", { name: "Plugins and providers", exact: true })
      .click();
  }
  async function openBuilder() {
    await openProject();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
  }

  await openPlugins();
  const panel = page.getByRole("region", {
    name: "Local plugins",
    exact: true,
  });
  await expect(
    page.getByRole("heading", { name: "Providers", exact: true }),
  ).toBeVisible();
  const chooser = panel.getByLabel("Plugin package (JSON)");
  const installButton = panel.getByRole("button", {
    name: "Install plugin",
    exact: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await panel.getByRole("link", { name: "Download sample plugin" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(packageFilename);
  const downloadedPath = info.outputPath(packageFilename);
  await download.saveAs(downloadedPath);
  expect(await readFile(downloadedPath)).toEqual(bundle);
  await expect(installButton).toBeDisabled();
  const beforeInstall = await decode<{ total: number }>(
    await page.request.get(`${api}/plugins`),
    200,
  );
  expect(beforeInstall.total).toBe(0);
  await chooser.setInputFiles({
    name: "unsupported.rvplugin.json",
    mimeType: "application/json",
    buffer: unsupported,
  });
  const badInstall = responseFor(page, `${api}/plugins`);
  await installButton.click();
  expect((await badInstall).status()).toBe(422);
  await expect(panel.getByRole("alert")).toBeVisible();

  await chooser.setInputFiles(downloadedPath);
  const installed = responseFor(page, `${api}/plugins`);
  await installButton.click();
  const plugin = await decode<PluginRecord>(await installed, 201);
  expect(plugin).toMatchObject({ manifest, available: true, enabled: false });
  expect(plugin.package_sha256).toMatch(/^[0-9a-f]{64}$/);
  const versionLabel = `${manifest.display_name} ${manifest.version}`;
  const version = panel.getByLabel("Plugin version", { exact: true });
  await expect(
    version.getByRole("option", {
      name: `${versionLabel} · Disabled`,
      exact: true,
    }),
  ).toBeDisabled();
  const enabled = responseFor(page, `${api}/plugins/${plugin.id}`, "PATCH");
  await panel
    .getByRole("button", { name: `Enable ${versionLabel}`, exact: true })
    .click();
  expect(await decode<PluginRecord>(await enabled, 200)).toMatchObject({
    enabled: true,
    package_sha256: plugin.package_sha256,
  });

  await version.selectOption(plugin.id);
  await panel
    .getByLabel("Source image", { exact: true })
    .selectOption(image.id);
  const pins = {
    plugin_record_id: plugin.id,
    package_sha256: plugin.package_sha256,
    image_id: image.id,
    image_sha256: imageSha,
  };
  const standalone = responseFor(page, `${base}/plugin-measurements`);
  await panel
    .getByRole("button", { name: "Run measurement", exact: true })
    .click();
  const measuredResponse = await standalone;
  expect(measuredResponse.request().postDataJSON()).toEqual(pins);
  const record = await decode<ScientificRecord>(measuredResponse, 200);
  expect(record).toMatchObject({
    variable: "green_fraction",
    value: 0.5,
    unit: "1",
    qc: "unassessed",
    subject: { image_id: image.id },
    provenance: {
      processing_parameters: {
        plugin_id: manifest.plugin_id,
        plugin_version: manifest.version,
        plugin_record_id: plugin.id,
        package_sha256: pins.package_sha256,
        module_sha256: manifest.module_sha256,
        image_sha256: imageSha,
        rgb_summary: { green_mean: 127.5, pixel_count: 6 },
      },
    },
  });
  await expect(panel.getByText("0.5 1", { exact: true })).toBeVisible();

  await expect(
    panel.getByRole("checkbox", {
      name: "Pause for measurement review",
      exact: true,
    }),
  ).toBeChecked();
  const saved = responseFor(page, `${base}/workflow-graphs`);
  await panel
    .getByRole("button", { name: "Open in Workflow Builder", exact: true })
    .click();
  const graph = await decode<WorkflowGraphRecord>(await saved, 201);
  expect(graph.graph_json.nodes).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        node_type: "plugin_image_measurement",
        parameters: pins,
      }),
      expect.objectContaining({ node_type: "measurement_review_gate" }),
    ]),
  );
  const measureNode = page.locator('[data-node-id="measure-image"]');
  await measureNode
    .getByRole("button", { name: "Configure", exact: true })
    .click();
  const guided = page.getByRole("group", {
    name: "Image measurement inputs",
    exact: true,
  });
  await expect(
    guided.getByLabel("Plugin version", { exact: true }),
  ).toHaveValue(plugin.id);
  await expect(guided.getByLabel("Source image", { exact: true })).toHaveValue(
    image.id,
  );
  await expect(guided.getByText(imageSha, { exact: true })).toBeVisible();

  const graphRow = page.getByRole("listitem").filter({
    has: page.getByText(graph.name, { exact: true }),
    hasText: graph.graph_sha256.slice(0, 12),
  });
  const runButton = graphRow.getByRole("button", {
    name: "Run saved revision",
    exact: true,
  });
  const replays: Array<{
    run_id: string;
    graph_sha256: string;
    payload_sha256: string;
    reviewed_payload_sha256: string;
    record_id: string;
  }> = [];
  for (const _ of [1, 2]) {
    await openBuilder();
    const requested = responseFor(page, `${base}/workflow-runs`);
    await runButton.click();
    const run = await decode<{ id: string }>(await requested, 202);
    let detail!: WorkflowRunDetail;
    const readRun = async () => {
      detail = await decode<WorkflowRunDetail>(
        await page.request.get(`${api}/workflow-runs/${run.id}`),
        200,
      );
      return detail.run.status;
    };
    await expect.poll(readRun, { timeout: 45_000 }).toBe("waiting_for_review");
    const waiting = detail.nodes.find(
      (node) => node.node_type === "measurement_review_gate",
    );
    expect(waiting?.status).toBe("waiting_for_review");
    const measured = detail.artifacts.find(
      (item) => item.producer_port_id === "measurement",
    );
    expect(waiting?.input_artifact_ids_json).toEqual([measured?.id]);
    expect(
      detail.artifacts.some((item) => item.producer_port_id === "reviewed"),
    ).toBe(false);
    const summary = page.getByRole("region", {
      name: "Measurement to review",
      exact: true,
    });
    await expect(
      summary.getByText("green_fraction", { exact: true }),
    ).toBeVisible();
    await expect(summary.getByText("0.5 1", { exact: true })).toBeVisible();
    await expect(summary.getByText(imageSha, { exact: true })).toBeVisible();
    await expect(
      summary.getByText(plugin.package_sha256, { exact: true }),
    ).toBeVisible();
    await expect(
      summary.getByText(/scientific QC remains unassessed/i),
    ).toBeVisible();
    const resumed = responseFor(
      page,
      `${api}/workflow-node-runs/${waiting!.id}/resume-review`,
    );
    await page
      .getByRole("button", { name: "Resume after review", exact: true })
      .click();
    const acknowledgement = await resumed;
    expect(acknowledgement.request().postDataJSON()).toMatchObject({
      reviewed_by: "local_user",
      note: expect.any(String),
    });
    await decode(acknowledgement, 202);
    await expect.poll(readRun, { timeout: 45_000 }).toBe("succeeded");
    expect(detail.run.status, detail.run.error_message ?? "").toBe("succeeded");
    const result = detail.artifacts.find(
      (item) => item.producer_port_id === "measurement",
    );
    expect(result).toEqual(measured);
    expect(result?.data_type).toBe("scientific_record_collection");
    expect(result?.payload_json).toMatchObject({
      record_ids: [record.id],
      content_sha256: { [record.id]: record.content_sha256 },
      value: 0.5,
      plugin: { package_sha256: plugin.package_sha256, image_sha256: imageSha },
    });
    const reviewed = detail.artifacts.find(
      (item) => item.producer_port_id === "reviewed",
    );
    expect(reviewed?.payload_json).toMatchObject({
      record_ids: [record.id],
      qc: "unassessed",
      review_approval: {
        reviewed_by: "local_user",
        input_artifact_ids: [result?.id],
      },
    });
    replays.push({
      run_id: run.id,
      graph_sha256: detail.run.graph_sha256,
      payload_sha256: result!.payload_sha256,
      reviewed_payload_sha256: reviewed!.payload_sha256,
      record_id: record.id,
    });
  }
  expect(replays[1].run_id).not.toBe(replays[0].run_id);
  expect(replays.map((result) => result.graph_sha256)).toEqual([
    graph.graph_sha256,
    graph.graph_sha256,
  ]);
  expect(replays[1].payload_sha256).toBe(replays[0].payload_sha256);
  expect(replays[1].reviewed_payload_sha256).not.toBe(
    replays[0].reviewed_payload_sha256,
  );

  await openPlugins();
  await expect(panel.getByText("0.5 1", { exact: true })).toBeVisible();
  const disabled = responseFor(page, `${api}/plugins/${plugin.id}`, "PATCH");
  await panel
    .getByRole("button", { name: `Disable ${versionLabel}`, exact: true })
    .click();
  expect(await decode<PluginRecord>(await disabled, 200)).toMatchObject({
    enabled: false,
    package_sha256: plugin.package_sha256,
  });
  await expect(
    version.getByRole("option", {
      name: `${versionLabel} · Disabled`,
      exact: true,
    }),
  ).toBeDisabled();
  await openBuilder();
  const blocked = responseFor(page, `${base}/workflow-runs`);
  await runButton.click();
  const denial = await decode<{ detail: string }>(await blocked, 400);
  expect(denial.detail).toMatch(/enable|disabled/i);
  await expect(page.getByText(denial.detail, { exact: true })).toBeVisible();

  const history = await decode<ScientificRecordPage>(
    await page.request.get(`${base}/plugin-measurements`),
    200,
  );
  expect(history.total).toBe(1);
  expect(history.items[0]).toEqual(record);
  const retained = await page.request.get(`${api}/images/${image.id}/content`);
  expect(retained.status()).toBe(200);
  expect(sha256(await retained.body())).toBe(imageSha);
  await writeFile(
    info.outputPath("local-plugin-measurement-evidence.json"),
    JSON.stringify(
      {
        surface,
        application_version: runtime.application_version,
        schema: runtime.schema_revision,
        project_id: project.id,
        image_id: image.id,
        image_sha256: imageSha,
        package_file_sha256: sha256(bundle),
        plugin_record_id: plugin.id,
        package_sha256: plugin.package_sha256,
        module_sha256: manifest.module_sha256,
        record_id: record.id,
        record_sha256: record.content_sha256,
        value: record.value,
        unit: record.unit,
        qc: record.qc,
        graph_id: graph.id,
        graph_sha256: graph.graph_sha256,
        disabled_refusal: denial.detail,
        replays,
      },
      null,
      2,
    ),
  );
});
