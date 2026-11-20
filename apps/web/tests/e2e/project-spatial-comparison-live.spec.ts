import { expect, test, type Locator } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

test("compares two project originals, reviews identity, reopens and exports the same result", async ({
  page,
}, info) => {
  const web = process.env.REEFVISION_GUIDED_TEST_WEB;
  const api = process.env.REEFVISION_GUIDED_TEST_API;
  test.skip(
    !web || !api,
    "Requires the isolated ReefVision API and desktop frontend",
  );
  const name = `Two synthetic acquisitions ${randomUUID().slice(0, 8)}`;
  const project = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(project.ok(), await project.text()).toBeTruthy();
  const { id: projectId } = await project.json();
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.4.0", "true"),
  );
  async function open() {
    await page.goto(web!);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
  }
  await open();
  const assets = page.getByRole("region", { name: "Project 3D source assets" });
  async function importMesh(filename: string, height: number) {
    const buffer = Buffer.from(`v 0 0 0\nv 1 0 0\nv 0 ${height} 0\nf 1 2 3\n`);
    await assets
      .getByLabel("Import 3D original")
      .setInputFiles({ name: filename, mimeType: "text/plain", buffer });
    const received = page.waitForResponse(
      (r) =>
        r.url().endsWith("/spatial/assets") && r.request().method() === "POST",
    );
    await assets.getByRole("button", { name: "Import original" }).click();
    const response = await received;
    expect(response.ok(), await response.text()).toBeTruthy();
    const record = await response.json();
    expect(record.sha256).toBe(
      createHash("sha256").update(buffer).digest("hex"),
    );
    await expect(
      assets.getByLabel("Project 3D source", { exact: true }),
    ).toHaveValue(record.id);
    return record;
  }
  const before = await importMesh("earlier-reef.obj", 1);
  const after = await importMesh("later-reef.obj", 2);
  await assets
    .getByLabel("Project 3D source", { exact: true })
    .selectOption(before.id);
  await assets
    .getByRole("button", { name: "Compare two acquisitions" })
    .click();
  const task = assets.getByRole("region", {
    name: "Two-acquisition mesh comparison",
  });
  const earlier = task.getByRole("group", {
    name: "Earlier acquisition",
    exact: true,
  });
  const later = task.getByRole("group", {
    name: "Later acquisition",
    exact: true,
  });
  await expect(earlier.getByLabel("Project 3D original")).toHaveValue(
    before.id,
  );
  await expect(
    later.getByRole("option", { name: /later-reef.obj.*parsed/ }),
  ).toBeEnabled();
  await later.getByLabel("Project 3D original").selectOption(after.id);
  async function configure(group: Locator, observation: string, day: string) {
    await group.getByLabel("Meters per source unit", { exact: true }).fill("1");
    await group
      .getByRole("combobox", { name: /Calibration method/ })
      .selectOption("ruler");
    await group
      .getByLabel("Calibration evidence", { exact: true })
      .fill(`Synthetic 1 m reference for ${observation}`);
    await group.getByLabel("Relative scale uncertainty").fill("0.1");
    await group.getByLabel("Provisional specimen ID").fill("synthetic-colony");
    await group.getByLabel("Observation ID", { exact: true }).fill(observation);
    await group.getByLabel("Coordinate frame ID").fill("synthetic-frame");
    await group.getByLabel("Acquisition timestamp", { exact: true }).fill(day);
  }
  await configure(earlier, "survey-1", "2026-10-01T12:00:00Z");
  await configure(later, "survey-2", "2026-10-02T12:00:00Z");
  const review = task.getByRole("group", {
    name: "Organism correspondence",
    exact: true,
  });
  await review.getByLabel("Matching method").selectOption("survey_tag");
  await review.getByLabel("Matching observer").fill("fixture-observer");
  await review
    .getByLabel("Correspondence evidence note")
    .fill("Synthetic matching survey tags");
  await review
    .getByLabel("Independent correspondence decision")
    .selectOption("disputes_match");
  await review
    .getByLabel("Independent correspondence reviewer")
    .fill("fixture-reviewer");
  await review
    .getByLabel("Independent correspondence review note")
    .fill("Deliberate disagreement in test fixture");
  await review
    .getByLabel("Correspondence review timestamp", { exact: true })
    .fill("2026-10-03T12:00:00Z");
  async function compare() {
    const response = page.waitForResponse((r) =>
      r.url().endsWith("/spatial/mesh-longitudinal-comparison"),
    );
    await task
      .getByRole("button", { name: "Preview comparison", exact: true })
      .click();
    const compared = await response;
    expect(compared.ok(), await compared.text()).toBeTruthy();
    return compared.json();
  }
  const disputed = await compare();
  expect(disputed.delta_surface_area_m2).toBeNull();
  await expect(task.getByText("Withheld", { exact: true })).toBeVisible();
  await review
    .getByLabel("Independent correspondence decision")
    .selectOption("supports_match");
  await expect(
    task.getByRole("button", { name: "Save comparison workflow" }),
  ).toBeDisabled();
  await review
    .getByLabel("Independent correspondence review note")
    .fill("Fixture identities agree with the synthetic survey key.");
  const standalone = await compare();
  expect(standalone.delta_surface_area_m2).toBeCloseTo(0.5, 12);
  expect(standalone.delta_surface_area_scale_interval_m2[0]).toBeCloseTo(
    0.205,
    12,
  );
  expect(standalone.delta_surface_area_scale_interval_m2[1]).toBeCloseTo(
    0.805,
    12,
  );
  expect(standalone.provenance.review_evidence_bundle).toMatchObject({
    project_id: projectId,
    before_spatial_source_asset_id: before.id,
    after_spatial_source_asset_id: after.id,
    before_source_payload_sha256: before.sha256,
    after_source_payload_sha256: after.sha256,
  });
  expect(standalone.provenance.specimen_identity_verified).toBe(false);
  const saving = page.waitForResponse(
    (r) =>
      r.url().endsWith("/workflow-graphs") && r.request().method() === "POST",
  );
  await task.getByRole("button", { name: "Save comparison workflow" }).click();
  const saved = await (await saving).json();
  const filename = info.outputPath("reopened-comparison.json");
  async function replayAndExport() {
    await open();
    const row = page.getByRole("listitem").filter({ hasText: saved.name });
    await row.getByRole("button", { name: "Load", exact: true }).click();
    const queued = page.waitForResponse(
      (r) =>
        r.url().endsWith("/workflow-runs") && r.request().method() === "POST",
    );
    await row
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const run = await (await queued).json();
    expect(run.workflow_graph_record_id).toBe(saved.id);
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Download 3D comparison JSON", exact: true })
      .click();
    await (await download).saveAs(filename);
    const artifact = JSON.parse(await readFile(filename, "utf8"));
    expect(artifact.workflow_run_id).toBe(run.id);
    expect(artifact.payload_json).toEqual(standalone);
    return artifact;
  }
  const first = await replayAndExport();
  const second = await replayAndExport();
  expect(second.workflow_run_id).not.toBe(first.workflow_run_id);
  expect(second.payload_sha256).toBe(first.payload_sha256);
});
