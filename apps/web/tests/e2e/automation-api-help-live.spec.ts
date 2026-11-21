import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { expect } from "@playwright/test";

import type { WorkflowGraphRecord } from "../../src/features/workflow-graphs/workflowGraphApi";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

test("Help copies the exact open project and selected saved CLI revision", async ({
  desktop,
}, info) => {
  const { page, api, web, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${version}`,
        "true",
      ),
    runtime.application_version,
  );
  const suffix = randomUUID().slice(0, 8);
  const projectResponse = await page.request.post(`${api}/projects`, {
    data: { name: `Automation CLI ${suffix}`, template: "blank" },
  });
  expect(projectResponse.status(), await projectResponse.text()).toBe(201);
  const project = (await projectResponse.json()) as {
    id: string;
    name: string;
  };
  const graphs: WorkflowGraphRecord[] = [];
  for (const name of ["Earlier CLI proof", "Selected CLI proof"]) {
    const response = await page.request.post(
      `${api}/projects/${project.id}/workflow-graphs`,
      {
        data: {
          create_new_revision: true,
          graph: {
            schema_version: "workflow-graph-0001",
            graph_id: `cli-proof-${suffix}`,
            name,
            nodes: [{ node_id: "project", node_type: "project_source" }],
            edges: [],
          },
        },
      },
    );
    expect(response.status(), await response.text()).toBe(201);
    graphs.push((await response.json()) as WorkflowGraphRecord);
  }
  expect(graphs[1].revision).toBe(graphs[0].revision + 1);
  expect(graphs[1].graph_sha256).not.toBe(graphs[0].graph_sha256);

  await page.goto(web);
  const help = page.getByRole("button", { name: "Help", exact: true });
  const automation = page.getByRole("button", {
    name: "Automation API",
    exact: true,
  });
  const dialog = page.getByRole("dialog", {
    name: "Automation API",
    exact: true,
  });
  await help.press("Enter");
  await automation.press("Enter");
  await expect(
    dialog.getByText("Open a project to generate its commands."),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(help).toBeFocused();

  await page
    .getByRole("button", { name: `Open ${project.name}`, exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Workflow builder", exact: true })
    .click();
  await page
    .getByRole("listitem")
    .filter({ hasText: graphs[1].name })
    .getByRole("button", { name: "Load", exact: true })
    .click();
  await help.press("Enter");
  await automation.press("Enter");
  await expect(dialog).toBeVisible();

  const commandPrefix = `.\\automation\\reefvision.exe --api-url ${api}`;
  const openProject = `${commandPrefix} project open ${project.id}`;
  await expect(
    dialog.getByRole("textbox", { name: "Open project command", exact: true }),
  ).toHaveValue(openProject);
  const revision = dialog.getByRole("combobox", {
    name: "Saved workflow revision",
    exact: true,
  });
  const command = dialog.getByRole("textbox", {
    name: "Pinned workflow command",
    exact: true,
  });
  await expect(revision).toHaveValue(graphs[1].id);
  const plan = `${commandPrefix} workflow plan ${project.id} ${graphs[1].id} --sha256 ${graphs[1].graph_sha256}`;
  await expect(command).toHaveValue(plan);
  await dialog
    .getByRole("combobox", { name: "Workflow action", exact: true })
    .selectOption("run");
  await revision.selectOption(graphs[0].id);
  const run = `${commandPrefix} workflow run ${project.id} ${graphs[0].id} --sha256 ${graphs[0].graph_sha256}`;
  await expect(command).toHaveValue(run);
  if (surface === "source-browser") {
    await page
      .context()
      .grantPermissions(["clipboard-read", "clipboard-write"], {
        origin: new URL(web).origin,
      });
  }
  await dialog
    .getByRole("button", { name: "Copy workflow command", exact: true })
    .press("Enter");
  const copyStatus = dialog.getByRole("status");
  await expect(copyStatus).toHaveText(/Copied command|Command selected/);
  const copied = (await copyStatus.innerText()).startsWith("Copied");
  if (surface === "source-browser") {
    expect(copied).toBe(true);
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(run);
  } else if (!copied) {
    await expect(command).toBeFocused();
    expect(
      await command.evaluate((field) => {
        const element = field as HTMLTextAreaElement;
        return element.value.slice(
          element.selectionStart,
          element.selectionEnd,
        );
      }),
    ).toBe(run);
  }
  await expect(dialog.getByText(/exit code 3/i)).toBeVisible();
  await expect(
    dialog.getByText(/--profile 'C:\\ReefVisionOffline'/),
  ).toBeVisible();
  await expect(dialog).not.toContainText(runtime.profile);
  const noRuns = await page.request.get(
    `${api}/projects/${project.id}/workflow-runs`,
  );
  expect(noRuns.status()).toBe(200);
  expect(await noRuns.json()).toEqual([]);

  await dialog
    .getByRole("button", { name: "Back to Help", exact: true })
    .press("Enter");
  await expect(automation).toBeFocused();
  await writeFile(
    info.outputPath("automation-api-help-evidence.json"),
    JSON.stringify(
      {
        surface,
        application_version: runtime.application_version,
        schema: runtime.schema_revision,
        project_id: project.id,
        saved_revisions: graphs.map((graph) => ({
          id: graph.id,
          revision: graph.revision,
          sha256: graph.graph_sha256,
        })),
        planRevisionFromBuilder: graphs[1].id,
        chosenRunRevisionId: graphs[0].id,
        live_loopback_attached: true,
        copied_to_clipboard: copied,
        workflow_runs_after_copy: 0,
      },
      null,
      2,
    ),
  );
});
