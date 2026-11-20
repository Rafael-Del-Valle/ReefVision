import { test } from "./spatialDesktop";
import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

test("records and reopens an attributed condition disagreement from a project asset", async ({
  desktop: { page, web, api },
}, info) => {
  const project = `Synthetic condition ${randomUUID().slice(0, 8)}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name: project },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.4.0", "true"),
  );
  const open = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${project}`, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Project-owned 3D originals",
        exact: true,
      }),
    ).toBeVisible();
  };

  await open();
  await page.getByLabel("Import 3D original").setInputFiles({
    name: "condition-fixture.obj",
    mimeType: "text/plain",
    buffer: Buffer.from("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"),
  });
  await page
    .getByRole("button", { name: "Import original", exact: true })
    .click();
  const panel = page.getByRole("region", { name: "Biological condition" });
  await panel
    .getByRole("button", { name: "Condition review", exact: true })
    .click();
  const values = {
    "Rubric ID": "synthetic-condition",
    "Rubric version": "fixture-v1",
    "Rubric reference": "Fixture protocol",
    "Observation unit": "fixture specimen",
    "Observation unit ID": "synthetic-unit-1",
    "Rubric labels (one per line)": "fixture-a\nfixture-b",
    "Observed label": "fixture-a",
    "Observer ID": "observer-1",
    "Observed at (local time)": "2026-01-01T10:30",
    "Observation evidence": "Fixture reference R1",
    "Observation uncertainty": "Fixture view partially occluded",
  };
  for (const [label, value] of Object.entries(values)) {
    await panel.getByLabel(label, { exact: true }).fill(value);
  }
  await panel
    .getByRole("button", { name: "Record observation", exact: true })
    .click();
  await expect(
    panel.getByText("Awaiting independent review", { exact: true }),
  ).toBeVisible();

  await panel.getByLabel("Reviewer ID").fill("reviewer-2");
  await panel
    .getByRole("combobox", { name: "Decision", exact: true })
    .selectOption("disagree");
  await panel
    .getByRole("combobox", { name: "Decision label", exact: true })
    .selectOption("fixture-b");
  await panel.getByLabel("Decided at (local time)").fill("2026-01-02T10:30");
  await panel
    .getByLabel("Decision evidence")
    .fill("Separate synthetic reference R2");
  await panel.getByLabel("Decision uncertainty").fill("Single fixture view");
  await panel.getByRole("button", { name: "Save decision" }).click();
  await expect(
    panel.getByText("Disagreement: fixture-b", { exact: true }),
  ).toBeVisible();

  await open();
  const assets = page.getByRole("combobox", {
    name: "Project 3D source",
    exact: true,
  });
  await expect(
    assets.getByRole("option", { name: /condition-fixture\.obj/ }),
  ).toHaveCount(1);
  await assets.selectOption({ index: 1 });
  await panel
    .getByRole("button", { name: "Condition review", exact: true })
    .click();
  const restored = panel
    .getByRole("listitem")
    .filter({ hasText: "Disagreement: fixture-b" });
  await expect(restored).toContainText("reviewer-2");
  const download = page.waitForEvent("download");
  await restored.getByRole("link", { name: "Download report" }).click();
  const payload = await download;
  const reportPath = info.outputPath("condition-evidence.json");
  await payload.saveAs(reportPath);
  const report = JSON.parse(await readFile(reportPath, "utf8"));
  expect(report.revisions).toHaveLength(2);
  expect(report.revisions[0].observation).toMatchObject({
    rubric: { rubric_id: "synthetic-condition", version: "fixture-v1" },
    observer_id: "observer-1",
  });
  expect(report.revisions[1]).toMatchObject({
    decision: {
      actor_id: "reviewer-2",
      decision: "disagree",
      label: "fixture-b",
    },
    resolved_label: null,
    scientifically_verified: false,
  });
});
