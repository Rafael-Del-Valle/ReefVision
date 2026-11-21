import { createHash, randomUUID } from "node:crypto";
import { readFile, rename, stat, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { expect } from "@playwright/test";

import type { PluginRecord } from "../../src/features/plugins/pluginApi";
import type { WorkflowGraphRecord } from "../../src/features/workflow-graphs/workflowGraphApi";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

const digest = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");

test("restores a contextual panel layout and an unavailable plugin without losing the open draft", async ({
  desktop,
}, info) => {
  test.setTimeout(120_000);
  const { page, api, web, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  const viewport = {
    width: 960,
    height: 640,
    deviceScaleFactor: 1.5,
    mobile: false,
  };
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setDeviceMetricsOverride", viewport);
  let displaced: { original: string; holding: string } | undefined;
  try {
    const offlineExample = JSON.parse(
      await readFile(
        resolve(
          process.cwd(),
          "../../examples/plugins/green-fraction.rvplugin.json",
        ),
        "utf8",
      ),
    );
    const caseId = randomUUID().slice(0, 8);
    const packageFixture = {
      ...offlineExample,
      manifest: {
        ...offlineExample.manifest,
        plugin_id: `layout_fixture_${caseId}`,
        display_name: "Layout fixture green summary",
      },
    };
    const bytes = Buffer.from(JSON.stringify(packageFixture));
    const installed = await page.request.post(`${api}/plugins`, {
      data: packageFixture,
    });
    expect(installed.status(), await installed.text()).toBe(201);
    const plugin = (await installed.json()) as PluginRecord;
    expect(plugin).toMatchObject({ enabled: false, available: true });
    const pluginLabel = `${plugin.manifest.display_name} ${plugin.manifest.version}`;
    const title = `Contextual layout witness ${caseId}`;
    const created = await page.request.post(`${api}/projects`, {
      data: { name: title, template: "blank" },
    });
    expect(created.status(), await created.text()).toBe(201);
    const project = (await created.json()) as { id: string };
    await page.addInitScript(
      (version) =>
        localStorage.setItem(
          `reefvision.onboarding.dismissed.${version}`,
          "true",
        ),
      runtime.application_version,
    );

    async function reopenWorkflow() {
      await page.goto(web);
      await page
        .getByRole("button", { name: `Open ${title}`, exact: true })
        .click();
      await page
        .getByRole("tab", { name: "Video & automation", exact: true })
        .click();
      await page
        .getByRole("tab", { name: "Workflow builder", exact: true })
        .click();
    }

    const panelButton = page.getByRole("button", {
      name: "Panels",
      exact: true,
    });
    const manager = page.getByRole("region", { name: "Panels", exact: true });
    const inspector = page.getByRole("complementary", {
      name: "Workspace inspector",
    });
    const pluginPanel = inspector.getByRole("region", {
      name: `${pluginLabel} plugin panel`,
      exact: true,
    });
    const visibleOrder = () =>
      inspector
        .locator("[data-contextual-panel]")
        .evaluateAll((panels) =>
          panels.map((panel) => panel.getAttribute("data-contextual-panel")),
        );

    await reopenWorkflow();
    await expect
      .poll(visibleOrder)
      .toEqual([
        "workflow-context",
        "truth-boundary",
        "preset-guidance",
        "related-workspaces",
        "project-context",
      ]);
    const initialOrder = await visibleOrder();
    expect(
      await page.evaluate(() => ({
        width: innerWidth,
        height: innerHeight,
        dpr: devicePixelRatio,
      })),
    ).toEqual({ width: 960, height: 640, dpr: 1.5 });
    await panelButton.press("Enter");
    await expect(manager).toBeVisible();
    await manager
      .getByRole("button", {
        name: "Move Scientific truth boundary up",
        exact: true,
      })
      .press("Enter");
    const related = manager.getByRole("checkbox", {
      name: "Show Related workspaces",
      exact: true,
    });
    await related.press("Space");
    await expect(related).not.toBeChecked();
    await manager
      .getByRole("combobox", { name: "Local plugin panel", exact: true })
      .selectOption(plugin.id);
    await manager
      .getByRole("button", { name: "Add plugin panel", exact: true })
      .press("Enter");
    await expect(
      pluginPanel.getByText("Plugin disabled.", { exact: true }),
    ).toBeVisible();
    const revisedOrder = [
      "truth-boundary",
      "workflow-context",
      "preset-guidance",
      "project-context",
      `plugin:${plugin.id}`,
    ];
    await expect.poll(visibleOrder).toEqual(revisedOrder);

    await reopenWorkflow();
    await expect.poll(visibleOrder).toEqual(revisedOrder);
    await expect(
      pluginPanel.getByText("Plugin disabled.", { exact: true }),
    ).toBeVisible();

    // Move only this test's freshly installed package, verified against the generated upload.
    const packagePath = join(runtime.profile, "plugins", plugin.id);
    expect(plugin.id).toMatch(/^[0-9a-f-]{36}$/);
    const modulePath = join(packagePath, "module.wasm");
    expect(digest(await readFile(modulePath))).toBe(
      plugin.manifest.module_sha256,
    );
    const holding = join(
      runtime.profile,
      "plugins",
      `layout-holding-${caseId}`,
    );
    expect(await stat(holding).catch(() => null)).toBeNull();
    await rename(packagePath, holding);
    displaced = { original: packagePath, holding };
    await reopenWorkflow();
    await expect(
      pluginPanel.getByText(
        "Plugin missing. Reinstall its package to recover this panel.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect.poll(visibleOrder).toEqual(revisedOrder);
    await pluginPanel
      .getByRole("button", { name: "Open Plugins and providers", exact: true })
      .click();
    await expect(
      page.getByRole("tab", { name: "Plugins and providers", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    const plugins = page.getByRole("region", {
      name: "Local plugins",
      exact: true,
    });
    await plugins
      .getByLabel("Plugin package (JSON)")
      .setInputFiles({
        name: "layout-fixture.rvplugin.json",
        mimeType: "application/json",
        buffer: bytes,
      });
    const recovery = page.waitForResponse(
      (response) =>
        response.url() === `${api}/plugins` &&
        response.request().method() === "POST",
    );
    await plugins
      .getByRole("button", { name: "Install plugin", exact: true })
      .press("Enter");
    const recovered = await recovery;
    expect(recovered.status(), await recovered.text()).toBe(201);
    expect(await recovered.json()).toMatchObject({
      id: plugin.id,
      package_sha256: plugin.package_sha256,
    });
    await plugins
      .getByRole("button", { name: `Enable ${pluginLabel}`, exact: true })
      .click();
    await expect(
      pluginPanel.getByText("Plugin enabled.", { exact: true }),
    ).toBeVisible();
    expect(digest(await readFile(modulePath))).toBe(
      plugin.manifest.module_sha256,
    );

    await reopenWorkflow();
    const disclosure = page.getByText("Advanced: edit workflow JSON directly", {
      exact: true,
    });
    await disclosure.click();
    const draft = page.locator("details.advanced-disclosure textarea");
    const editedGraph = JSON.parse(await draft.inputValue());
    editedGraph.name = `Draft kept across layout reset ${caseId}`;
    const edited = JSON.stringify(editedGraph, null, 2);
    await draft.fill(edited);
    const sameDraft = await draft.elementHandle();
    await panelButton.press("Enter");
    await manager
      .getByRole("button", { name: "Reset layout", exact: true })
      .press("Enter");
    await expect.poll(visibleOrder).toEqual(initialOrder);
    await expect(draft).toHaveValue(edited);
    expect(await sameDraft?.evaluate((element) => element.isConnected)).toBe(
      true,
    );
    await expect(pluginPanel).toHaveCount(0);
    const savedResponse = page.waitForResponse(
      (response) =>
        response.url() === `${api}/projects/${project.id}/workflow-graphs` &&
        response.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Save revision", exact: true })
      .click();
    const saved = await savedResponse;
    expect(saved.status(), await saved.text()).toBe(201);
    const graph = (await saved.json()) as WorkflowGraphRecord;
    expect(graph.graph_json.name).toBe(editedGraph.name);

    await reopenWorkflow();
    await expect.poll(visibleOrder).toEqual(initialOrder);
    await expect(
      page.getByText(editedGraph.name, { exact: true }),
    ).toBeVisible();
    await writeFile(
      info.outputPath("contextual-panel-layout-evidence.json"),
      JSON.stringify(
        {
          surface,
          application_version: runtime.application_version,
          schema: runtime.schema_revision,
          viewport,
          project_id: project.id,
          initial_order: initialOrder,
          persisted_order: revisedOrder,
          restored_order: await visibleOrder(),
          plugin_record_id: plugin.id,
          plugin_package_sha256: plugin.package_sha256,
          module_sha256: plugin.manifest.module_sha256,
          recovered_exact_package: true,
          saved_graph_id: graph.id,
          saved_graph_sha256: graph.graph_sha256,
          draft_preserved: true,
        },
        null,
        2,
      ),
    );
  } finally {
    if (displaced && !(await stat(displaced.original).catch(() => null))) {
      await rename(displaced.holding, displaced.original);
    }
    await cdp.send("Emulation.clearDeviceMetricsOverride");
    await cdp.detach();
  }
});
