import { test } from "./spatialDesktop";
import { expect, type Page, type TestInfo } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import type {
  WorkflowArtifact,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";

test("replays and exports a two-acquisition mesh comparison with review evidence", async ({
  desktop,
}, info) => {
  test.setTimeout(120_000);
  await runSpatialWorkflow(
    desktop.page,
    desktop.web,
    desktop.api,
    info,
    desktop.surface,
  );
});

async function runSpatialWorkflow(
  page: Page,
  web: string,
  api: string,
  info: TestInfo,
  surface: "tauri-webview2" | "source-browser",
): Promise<void> {
  page.setDefaultTimeout(12_000);
  const name = `Synthetic spatial workflow ${randomUUID().slice(0, 8)}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { id } = (await created.json()) as { id: string };
  const base = `${api}/projects/${id}`;
  const observations = [
    {
      filename: "before.obj",
      mesh: "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n",
      date: "2026-01-01T11:34:56.123456-05:00",
      id: "survey-before",
      frame: "frame-before",
    },
    {
      filename: "after.obj",
      mesh: "v 0 0 0\nv 2 0 0\nv 0 4 0\nf 1 2 3\n",
      date: "2026-01-08T16:34:56.123456Z",
      id: "survey-after",
      frame: "frame-after",
    },
  ];
  const reviewDate = "2026-01-09T10:00:00Z";
  const scaleEvidence = "Synthetic scale bar with known reference length";

  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.9.0", "true"),
  );
  const openWorkflow = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
  };
  await openWorkflow();

  const assets = [];
  for (const observation of observations) {
    await page.getByLabel("Import 3D original").setInputFiles({
      name: observation.filename,
      mimeType: "text/plain",
      buffer: Buffer.from(observation.mesh),
    });
    const importResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url() === `${base}/spatial/assets`,
    );
    await page
      .getByRole("button", { name: "Import original", exact: true })
      .click();
    const imported = await importResponse;
    expect(imported.status(), await imported.text()).toBe(201);
    const asset = (await imported.json()) as { id: string; sha256: string };
    expect(asset.sha256).toBe(
      createHash("sha256").update(observation.mesh).digest("hex"),
    );
    assets.push(asset);
  }
  await expect
    .poll(async () => {
      const list = await page.request.get(`${base}/spatial/assets`);
      const rows = (await list.json()) as { parse_status: string }[];
      return rows.map((asset) => asset.parse_status);
    })
    .toEqual(["succeeded", "succeeded"]);

  await page
    .getByRole("combobox")
    .filter({
      has: page.getByRole("option", { name: "Project images", exact: true }),
    })
    .selectOption("project-images");
  const addNode = page.getByLabel("Add node");
  const meshNodes = page.locator("[data-node-id^='mesh_surface_preview-']");
  const guidedMeasurement = page.getByRole("group", {
    name: "Guided 3D geometric measurement",
    exact: true,
  });
  const source = page.locator("[data-node-id='project']");
  for (const [index, observation] of observations.entries()) {
    await addNode.selectOption("mesh_surface_preview");
    const node = meshNodes.nth(index);
    await node.getByRole("button", { name: "Configure", exact: true }).click();
    await page
      .getByLabel("Project 3D original")
      .selectOption({ label: `${observation.filename} · OBJ · parsed` });
    await guidedMeasurement
      .getByLabel("Meters per source unit", { exact: true })
      .fill("0.01");
    await guidedMeasurement
      .getByRole("combobox", { name: /Calibration method/ })
      .selectOption("ruler");
    await guidedMeasurement
      .getByLabel("Calibration evidence", { exact: true })
      .fill(scaleEvidence);
    await guidedMeasurement
      .getByLabel("Relative scale uncertainty (0 to 1)")
      .fill("0.02");
    await guidedMeasurement
      .getByLabel("Provisional specimen ID")
      .fill("colony-a");
    await page
      .getByLabel("Observation ID", { exact: true })
      .fill(observation.id);
    await guidedMeasurement
      .getByLabel("Coordinate frame ID")
      .fill(observation.frame);
    await page
      .getByLabel("Acquisition timestamp", { exact: true })
      .fill(observation.date, { timeout: 5000 });
    await source
      .getByRole("button", { name: "Project ▶", exact: true })
      .click();
    await node.getByRole("button", { name: "◀ Project", exact: true }).click();
  }

  await addNode.selectOption("mesh_longitudinal_comparison");
  const comparison = page.locator(
    "[data-node-id^='mesh_longitudinal_comparison-']",
  );
  for (const [index, timepoint] of ["Earlier", "Later"].entries()) {
    await meshNodes
      .nth(index)
      .getByRole("button", {
        name: "Unverified mesh measurement ▶",
        exact: true,
      })
      .click();
    await comparison
      .getByRole("button", {
        name: `◀ ${timepoint} mesh observation`,
        exact: true,
      })
      .click();
  }
  await comparison
    .getByRole("button", { name: "Configure", exact: true })
    .click();
  const fields = {
    "Registration source frame": observations[0].frame,
    "Registration target frame": observations[1].frame,
    "RMS residual (meters)": "0.0005",
    "Correspondence count": "3",
    "Registration evidence note": "Synthetic control locations",
    "Registration operator": "registration-operator",
    "Independent registration reviewer": "registration-reviewer",
    "Independent registration review note":
      "Fixture controls support alignment",
    "Registration review timestamp": reviewDate,
    "Earlier observation ID": observations[0].id,
    "Later observation ID": observations[1].id,
    "Matching observer": "matching-observer",
    "Correspondence evidence note": "Synthetic colony tag across acquisitions",
    "Independent correspondence reviewer": "matching-reviewer",
    "Independent correspondence review note":
      "Fixture tag supports correspondence",
    "Correspondence review timestamp": reviewDate,
  };
  for (const [label, value] of Object.entries(fields)) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page
    .getByLabel("Independent registration decision")
    .selectOption("supports_alignment");
  await page
    .getByLabel("Independent correspondence decision")
    .selectOption("supports_match");

  const run = async (button: string) => {
    const queued = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith("/workflow-runs"),
    );
    await page.getByRole("button", { name: button, exact: true }).click();
    const response = await queued;
    expect(response.status(), await response.text()).toBe(202);
    const started = (await response.json()) as { id: string };
    let detail: WorkflowRunDetail;
    await expect
      .poll(
        async () => {
          const current = await page.request.get(
            `${api}/workflow-runs/${started.id}`,
          );
          detail = await current.json();
          return detail.run.status;
        },
        { timeout: 25_000 },
      )
      .not.toMatch(/queued|running/);
    expect(detail!.run.status, detail!.run.error_message ?? undefined).toBe(
      "succeeded",
    );
    const result = detail!.artifacts.find(
      (item) => item.data_type === "mesh_longitudinal_comparison",
    );
    expect(result).toBeDefined();
    return { run: detail!.run, result: result! };
  };
  const first = await run("Save & run");

  const [before, after] = observations.map((observation, index) => ({
    asset_id: assets[index].id,
    meters_per_unit: 0.01,
    calibration_method: "ruler",
    calibration_evidence: scaleEvidence,
    relative_scale_uncertainty: 0.02,
    specimen_id: "colony-a",
    observation_id: observation.id,
    observed_at_utc: observation.date,
    coordinate_frame_id: observation.frame,
  }));
  const standalone = await page.request.post(
    `${base}/spatial/mesh-longitudinal-comparison`,
    {
      data: {
        before,
        after,
        registration_evidence: {
          source_frame_id: before.coordinate_frame_id,
          target_frame_id: after.coordinate_frame_id,
          method: "landmark",
          rms_residual_m: 0.0005,
          correspondence_count: 3,
          evidence_note: fields["Registration evidence note"],
          registration_operator_id: fields["Registration operator"],
          independent_reviewer_id: fields["Independent registration reviewer"],
          independent_review_decision: "supports_alignment",
          independent_review_note:
            fields["Independent registration review note"],
          independent_reviewed_at_utc: reviewDate,
        },
        reidentification_evidence: {
          before_observation_id: before.observation_id,
          after_observation_id: after.observation_id,
          observer_id: fields["Matching observer"],
          method: "visual_morphology",
          evidence_note: fields["Correspondence evidence note"],
          independent_reviewer_id:
            fields["Independent correspondence reviewer"],
          independent_review_decision: "supports_match",
          independent_review_note:
            fields["Independent correspondence review note"],
          independent_reviewed_at_utc: reviewDate,
        },
      },
    },
  );
  expect(standalone.status(), await standalone.text()).toBe(200);
  const expected = await standalone.json();
  expect(first.result.payload_json).toEqual(expected);
  expect(first.result.payload_json).toMatchObject({
    elapsed_days: 7,
    before_observed_at_utc_normalized: "2026-01-01T16:34:56.123456Z",
    after_observed_at_utc_normalized: observations[1].date,
    provenance: {
      calibration_verified: false,
      coordinate_registration_verified: false,
      specimen_identity_verified: false,
      review_evidence_bundle: {
        before_spatial_source_asset_id: assets[0].id,
        after_spatial_source_asset_id: assets[1].id,
        before_source_payload_sha256: assets[0].sha256,
        after_source_payload_sha256: assets[1].sha256,
      },
    },
  });
  expect(expected.delta_surface_area_m2).toBeCloseTo(0.0001, 12);
  expect(expected.delta_surface_area_scale_interval_m2[0]).toBeLessThan(0.0001);
  expect(expected.delta_surface_area_scale_interval_m2[1]).toBeGreaterThan(
    0.0001,
  );

  await openWorkflow();
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await meshNodes
    .first()
    .getByRole("button", { name: "Configure", exact: true })
    .click();
  await expect(
    page.getByLabel("Acquisition timestamp", { exact: true }),
  ).toHaveValue(observations[0].date);
  const replay = await run("Run saved revision");
  expect(replay.run.id).not.toBe(first.run.id);
  expect(replay.run.workflow_graph_record_id).toBe(
    first.run.workflow_graph_record_id,
  );
  expect(replay.run.graph_sha256).toBe(first.run.graph_sha256);
  expect(replay.result.payload_sha256).toBe(first.result.payload_sha256);
  expect(replay.result.payload_json).toEqual(first.result.payload_json);

  const downloadPending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download 3D comparison JSON", exact: true })
    .click();
  const download = await downloadPending;
  const exported = JSON.parse(
    await readFile((await download.path())!, "utf-8"),
  ) as WorkflowArtifact;
  expect(exported).toEqual(replay.result);
  const evidencePath = info.outputPath("spatial-workflow.json");
  await writeFile(
    evidencePath,
    JSON.stringify(
      {
        surface,
        graph_record_id: first.run.workflow_graph_record_id,
        graph_sha256: first.run.graph_sha256,
        first_run_id: first.run.id,
        replay_run_id: replay.run.id,
        artifact: exported,
      },
      null,
      2,
    ),
  );
  await info.attach("two-acquisition-spatial-replay", {
    contentType: "application/json",
    path: evidencePath,
  });
}
