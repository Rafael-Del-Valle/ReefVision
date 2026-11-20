import { test } from "./spatialDesktop";
import { expect, type Locator } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

test("compares two project originals, reviews identity, reopens and exports the same result", async ({
  desktop: { page, web, api },
}, info) => {
  test.setTimeout(90_000);
  const name = `Two synthetic acquisitions ${randomUUID().slice(0, 8)}`;
  const project = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(project.ok(), await project.text()).toBeTruthy();
  const { id: projectId } = await project.json();
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.8.0", "true"),
  );
  async function openProject(projectName: string) {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${projectName}`, exact: true })
      .click();
  }
  async function openWorkflow(projectName: string) {
    await openProject(projectName);
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
  }
  await openWorkflow(name);
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
    await group.getByLabel("Coordinate frame ID").fill(`${observation}-frame`);
    await group.getByLabel("Acquisition timestamp", { exact: true }).fill(day);
  }
  await configure(earlier, "survey-1", "2026-10-01T12:00:00Z");
  await configure(later, "survey-2", "2026-10-02T12:00:00Z");
  const registration = task.getByRole("group", {
    name: "Registration review",
    exact: true,
  });
  await registration
    .getByText("Rigid transform and error bounds", { exact: true })
    .click({ timeout: 5000 });
  const matrix = registration.getByLabel(
    "Earlier-to-later rigid transform (4 × 4)",
  );
  const transform = [
    [0, -1, 0, 0.5],
    [1, 0, 0, 0.125],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
  ];
  const separation = Math.sqrt(41) / 24;
  const interval = [separation - 0.1, separation + 0.1];

  const registrationFields = {
    "RMS residual (meters)": "0.025",
    "Correspondence count": "4",
    "Registration evidence note":
      "Synthetic control coordinates in the two source frames.",
    "Registration operator": "fixture-registration-operator",
    "Independent registration reviewer": "fixture-registration-reviewer",
    "Independent registration review note":
      "Synthetic control transform and declared error bounds.",
    "Registration review timestamp": "2026-10-03T12:00:00Z",
    "Earlier centroid error bound (meters)": "0.02",
    "Later centroid error bound (meters)": "0.03",
    "Alignment error bound (meters)": "0.05",
  };
  for (const [label, value] of Object.entries(registrationFields)) {
    await registration.getByLabel(label, { exact: true }).fill(value);
  }
  await registration
    .getByLabel("Independent registration decision")
    .selectOption("supports_alignment");
  const preview = task.getByRole("button", {
    name: "Preview comparison",
    exact: true,
  });
  await matrix.fill("[[0");
  await expect(preview).toBeDisabled();
  await expect(
    task.getByText("Enter a 4 × 4 registration matrix with finite numbers."),
  ).toBeVisible();
  await matrix.fill(JSON.stringify([[2, -1, 0, 0.5], ...transform.slice(1)]));
  const checkedInvalid = page.waitForResponse((r) =>
    r.url().endsWith("/spatial/mesh-longitudinal-comparison"),
  );
  await preview.click();
  const invalid = await checkedInvalid;
  expect(invalid.status(), await invalid.text()).toBe(422);
  expect(await invalid.text()).toContain(
    "Registration transform must have unit rotation axes",
  );
  await expect(
    task.getByRole("button", { name: "Save comparison workflow" }),
  ).toBeDisabled();
  await matrix.fill(JSON.stringify(transform));

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
  expect(standalone.provenance.coordinate_registration_verified).toBe(false);
  expect(standalone.registered_surface_centroid_separation_m).toBeCloseTo(
    separation,
    12,
  );
  expect(
    standalone.registered_surface_centroid_separation_caller_bound_interval_m,
  ).toEqual(interval.map((value) => expect.closeTo(value, 12)));
  await expect(
    task.getByText("Registered surface centroid separation", { exact: true }),
  ).toBeVisible();
  await expect(
    task.getByText("Caller-declared separation bounds", { exact: true }),
  ).toBeVisible();
  const saving = page.waitForResponse(
    (r) =>
      r.url().endsWith("/workflow-graphs") && r.request().method() === "POST",
  );
  await task.getByRole("button", { name: "Save comparison workflow" }).click();
  const saved = await (await saving).json();
  const savedComparison = saved.graph_json.nodes.find(
    (node: { node_id: string }) => node.node_id === "compare",
  );
  expect(savedComparison.parameters.registration_evidence).toMatchObject({
    source_frame_id: "survey-1-frame",
    target_frame_id: "survey-2-frame",
    source_to_target_transform_m: transform,
    source_payload_sha256: before.sha256,
    target_payload_sha256: after.sha256,
    source_centroid_position_error_bound_m: 0.02,
    target_centroid_position_error_bound_m: 0.03,
    registration_alignment_error_bound_m: 0.05,
  });
  await task.screenshot({
    path: info.outputPath("registered-centroid-comparison.png"),
  });
  async function downloadComparison(filename: string) {
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Download 3D comparison JSON", exact: true })
      .click();
    const path = info.outputPath(filename);
    await (await download).saveAs(path);
    return JSON.parse(await readFile(path, "utf8"));
  }
  async function replayAndExport(
    projectName: string,
    graphId: string,
    filename: string,
  ) {
    await openWorkflow(projectName);
    const row = page.getByRole("listitem").filter({ hasText: saved.name });
    await row.getByRole("button", { name: "Load", exact: true }).click();
    await page
      .locator("[data-node-id='compare']")
      .getByRole("button", { name: "Configure", exact: true })
      .click();
    const reopened = page.getByRole("group", {
      name: "Registration review",
      exact: true,
    });
    await reopened
      .getByText("Rigid transform and error bounds", { exact: true })
      .click();
    await expect(
      reopened.getByLabel("Earlier-to-later rigid transform (4 × 4)"),
    ).toHaveValue(JSON.stringify(transform));
    await expect(
      reopened.getByLabel("Alignment error bound (meters)"),
    ).toHaveValue("0.05");
    const queued = page.waitForResponse(
      (r) =>
        r.url().endsWith("/workflow-runs") && r.request().method() === "POST",
    );
    await row
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const run = await (await queued).json();
    expect(run.workflow_graph_record_id).toBe(graphId);
    const artifact = await downloadComparison(filename);
    expect(artifact.workflow_run_id).toBe(run.id);
    return artifact;
  }
  const first = await replayAndExport(name, saved.id, "first-comparison.json");
  const second = await replayAndExport(
    name,
    saved.id,
    "reopened-comparison.json",
  );
  expect(first.payload_json).toEqual(standalone);
  expect(second.payload_json).toEqual(standalone);
  expect(second.workflow_run_id).not.toBe(first.workflow_run_id);
  expect(second.payload_sha256).toBe(first.payload_sha256);

  await openProject(name);
  await page.getByRole("tab", { name: "Data & annotation" }).click();
  await page.getByRole("tab", { name: "Interoperability" }).click();
  await page.getByRole("button", { name: "Create exchange ZIP" }).click();
  const link = page.getByRole("link", { name: "Download ZIP" }).first();
  const href = await link.getAttribute("href", { timeout: 20_000 });
  expect(href).toBeTruthy();
  const archive = await page.request.get(href!);
  expect(archive.ok(), await archive.statusText()).toBeTruthy();
  await page.getByLabel("Project exchange ZIP").setInputFiles({
    name: "spatial-comparison.reefvision.zip",
    mimeType: "application/zip",
    buffer: await archive.body(),
  });
  await page.getByRole("button", { name: "Inspect safely" }).click();
  const restoredName = name + " restored";
  await page.getByLabel("Imported project name (optional)").fill(restoredName);
  const importing = page.waitForResponse((response) =>
    response.url().endsWith("/exchange-packages/import"),
  );
  await page.getByRole("button", { name: "Import as new project" }).click();
  const response = await importing;
  expect(response.status(), await response.text()).toBe(201);
  const restored = await response.json();
  const mapped = restored.package.options_json.id_map;
  expect(restored.project_id).not.toBe(projectId);
  await expect(
    page.getByText("Imported project", { exact: true }),
  ).toBeVisible();

  await openWorkflow(restoredName);
  await page
    .getByRole("button", { name: /^succeeded ·/ })
    .first()
    .click();
  const historical = await downloadComparison("archived-comparison.json");
  expect(historical.payload_json).toEqual(standalone);
  expect(historical.payload_sha256).toBe(first.payload_sha256);

  const local = await replayAndExport(
    restoredName,
    mapped[saved.id],
    "restored-replay.json",
  );
  expect(local.payload_json.delta_surface_area_m2).toBe(
    standalone.delta_surface_area_m2,
  );
  expect(local.payload_json.delta_surface_area_scale_interval_m2).toEqual(
    standalone.delta_surface_area_scale_interval_m2,
  );
  expect(local.payload_json.provenance.review_evidence_bundle).toMatchObject({
    project_id: restored.project_id,
    before_spatial_source_asset_id: mapped[before.id],
    after_spatial_source_asset_id: mapped[after.id],
    before_source_payload_sha256: before.sha256,
    after_source_payload_sha256: after.sha256,
  });
  expect(local.payload_json.provenance.review_evidence_bundle_sha256).not.toBe(
    standalone.provenance.review_evidence_bundle_sha256,
  );
});
