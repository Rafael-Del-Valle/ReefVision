import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { expect } from "@playwright/test";
import type { ImageAdjustmentRecord } from "../../src/features/annotation-editor/imageAdjustmentApi";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { checked, verifyOriginal } from "./pairedStillComparisonFixture";
import { test } from "./spatialDesktop";

const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");

interface DomainProof {
  content_sha256: string;
  snapshot: {
    declaration: {
      comparison_id: string;
      comparison_sha256: string;
      adjustments: {
        recipe_id: string;
        image_id: string;
        original_sha256: string;
        rendition_sha256: string;
      }[];
    };
    preprocessing_executed: "adjusted";
    models: { checkpoint_sha256: string }[];
    reference: { manifest_sha256: string };
    summary: {
      lineage: string;
      status: string;
      groups: { group_id: string; status: string; domain: string }[];
      metrics: {
        left: {
          reference_n: number;
          target_n: number;
          ci95: number[] | null;
          interval_status: string;
        };
      }[];
    };
    observed_evidence: { inference_job_ids: string[] };
  };
}

test("scores pinned still adjustments across two frozen domains and replays the saved report", async ({
  desktop,
}, info) => {
  test.setTimeout(155_000);
  const { page, api, web, surface } = desktop;
  const witness = process.env.REEFVISION_RESEARCH_TOOLS_PAIRED_RECEIPT;
  test.skip(
    !witness,
    "Requires the generated paired model evidence from this disposable profile",
  );
  const runtime = await verifyResearchDesktop(page, api);
  page.setDefaultTimeout(12_000);
  const fixture = JSON.parse(await readFile(witness!, "utf8")) as {
    fixture_source: string;
    project_id: string;
    comparison_id: string;
    report_sha256: string;
    reference_sha256: string;
    checkpoint_sha256: string[];
    groups: { id: string; observations: number }[];
    original_images: { id: string; sha256: string }[];
  };
  expect(fixture.groups).toHaveLength(2);
  expect(fixture.original_images).toHaveLength(3);
  const endpoint = `${api}/projects/${fixture.project_id}`;
  const project = await checked<{ name: string }>(
    await page.request.get(endpoint),
  );
  const baseline = await checked<{
    status: string;
    result_json: {
      content_sha256: string;
      snapshot: {
        evidence: { evaluation_status: string; reference_sha256: string };
        models: { receipt: { checkpoint_sha256: string } }[];
      };
    };
  }>(
    await page.request.get(
      `${endpoint}/paired-model-comparisons/${fixture.comparison_id}`,
    ),
  );
  expect(baseline.status).toBe("succeeded");
  expect(baseline.result_json.content_sha256).toBe(fixture.report_sha256);
  expect(baseline.result_json.snapshot.evidence).toMatchObject({
    evaluation_status: "held_out",
    reference_sha256: fixture.reference_sha256,
  });
  expect(
    baseline.result_json.snapshot.models.map(
      (row) => row.receipt.checkpoint_sha256,
    ),
  ).toEqual(fixture.checkpoint_sha256);

  const recipes: ImageAdjustmentRecord[] = [];
  for (const image of fixture.original_images) {
    expect((await verifyOriginal(page, api, image.id)).sha256).toBe(
      image.sha256,
    );
    recipes.push(
      await checked<ImageAdjustmentRecord>(
        await page.request.post(`${api}/images/${image.id}/adjustments`, {
          data: {
            original_sha256: image.sha256,
            parameters: { red_gain_percent: 125, blue_gain_percent: 90 },
          },
        }),
        201,
      ),
    );
  }
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${version}`,
        "true",
      ),
    runtime.application_version,
  );
  async function openProject() {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${project.name}`, exact: true })
      .click();
  }
  async function openDomain() {
    await openProject();
    await page.getByRole("tab", { name: "Models & AI", exact: true }).click();
    await page
      .getByRole("tab", { name: "Model comparison", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Domain shift", exact: true })
      .click();
    return page.getByRole("region", { name: "Domain shift", exact: true });
  }
  const domain = await openDomain();
  await domain
    .getByLabel("Completed paired comparison")
    .selectOption(fixture.comparison_id);
  await domain
    .getByLabel("Reference domain", { exact: true })
    .fill("Synthetic clear-water reference");
  await domain
    .getByLabel("Target domain", { exact: true })
    .fill("Synthetic turbid-water target");
  await domain
    .getByLabel("Declared independent unit")
    .fill("One generated reef recording");
  await domain
    .getByLabel(`Group ${fixture.groups[0].id}`)
    .selectOption("reference");
  await domain
    .getByLabel(`Group ${fixture.groups[1].id}`)
    .selectOption("target");
  await domain
    .getByLabel("Planned missing target groups, one per line")
    .fill("Unobserved validation acquisition");
  await domain.getByLabel("Model input preprocessing").selectOption("adjusted");
  for (const recipe of recipes) {
    await domain
      .getByRole("combobox")
      .filter({
        has: page.getByRole("option", {
          name: recipe.content_sha256.slice(0, 12),
          exact: true,
        }),
      })
      .selectOption(recipe.id);
  }
  const post = (url: string) =>
    page.waitForResponse(
      (event) => event.url() === url && event.request().method() === "POST",
    );
  const queued = post(`${endpoint}/domain-shift`);
  await domain
    .getByRole("button", { name: "Run domain shift analysis" })
    .click();
  const { id: reportId } = await checked<{ id: string }>(await queued, 202);
  const reportUrl = `${endpoint}/domain-shift/${reportId}`;
  let result:
    | { status: string; error_message: string | null; result_json: DomainProof }
    | undefined;
  await expect
    .poll(
      async () => {
        result = await checked(await page.request.get(reportUrl));
        return result!.status;
      },
      { timeout: 60_000 },
    )
    .not.toMatch(/queued|running/);
  expect(result!.status, result!.error_message ?? undefined).toBe("succeeded");
  const report = result!.result_json;
  const { snapshot } = report;
  expect(snapshot.declaration.comparison_id).toBe(fixture.comparison_id);
  expect(snapshot.declaration.comparison_sha256).toBe(fixture.report_sha256);
  expect(snapshot.models.map((model) => model.checkpoint_sha256)).toEqual(
    fixture.checkpoint_sha256,
  );
  expect(snapshot.preprocessing_executed).toBe("adjusted");
  expect(snapshot.reference.manifest_sha256).toBe(fixture.reference_sha256);
  expect(snapshot.summary).toMatchObject({
    status: "scored",
    lineage: "held_out",
  });
  expect(
    snapshot.summary.groups
      .filter((row) => row.status === "included")
      .map((row) => row.group_id),
  ).toEqual(fixture.groups.map((row) => row.id));
  expect(
    snapshot.summary.groups.find(
      (row) => row.group_id === "Unobserved validation acquisition",
    )?.status,
  ).toBe("missing");
  expect(snapshot.summary.metrics.length).toBeGreaterThan(0);
  expect(
    snapshot.summary.metrics.some(
      (item) =>
        item.left.reference_n === 1 &&
        item.left.target_n === 1 &&
        item.left.interval_status === "insufficient_complete_groups",
    ),
  ).toBe(true);
  const jobIds = snapshot.observed_evidence.inference_job_ids;
  expect(jobIds).toHaveLength(2 * recipes.length);
  for (const id of jobIds) {
    const job = await checked<{
      status: string;
      request_json: { evaluation_only: boolean; checkpoint_sha256: string };
      result_json: { model_input: { rendition_sha256: string } };
    }>(await page.request.get(`${api}/jobs/${id}`));
    expect(job.status).toBe("succeeded");
    expect(job.request_json.evaluation_only).toBe(true);
    expect(fixture.checkpoint_sha256).toContain(
      job.request_json.checkpoint_sha256,
    );
    expect(recipes.map((recipe) => recipe.receipt.rendition_sha256)).toContain(
      job.result_json.model_input.rendition_sha256,
    );
  }

  const reopened = await openDomain();
  await reopened
    .getByRole("button", {
      name: `Domain shift · ${reportId.slice(0, 8)} · succeeded`,
    })
    .click();
  const visible = page.getByRole("region", { name: "Domain shift results" });
  await expect(
    visible.getByText(report.content_sha256, { exact: true }),
  ).toBeVisible();
  await expect(
    visible.getByText(/Unobserved validation acquisition.*missing/),
  ).toBeVisible();
  async function exportFile(label: string, suffix: string, path: string) {
    const downloading = page.waitForEvent("download");
    await visible.getByRole("link", { name: label, exact: true }).click();
    const file = await downloading;
    expect(file.suggestedFilename()).toBe(`domain-shift-${reportId}.${suffix}`);
    const output = info.outputPath(`domain-shift-report.${suffix}`);
    await file.saveAs(output);
    const actual = await readFile(output);
    expect(sha256(actual)).toBe(
      sha256(await (await page.request.get(`${reportUrl}/${path}`)).body()),
    );
    return actual;
  }
  const json = await exportFile("Export domain report JSON", "json", "report");
  expect(JSON.parse(json.toString("utf8"))).toEqual(report);
  const csv = await exportFile(
    "Export acquisition groups CSV",
    "csv",
    "groups.csv",
  );
  expect(csv.toString("utf8")).toContain(
    "target,Unobserved validation acquisition,missing",
  );
  expect(csv.toString("utf8")).toContain(report.content_sha256);

  const saving = post(`${endpoint}/workflow-graphs`);
  await visible
    .getByRole("button", { name: "Save domain replay to Workflow Builder" })
    .click();
  const graph = await checked<{
    id: string;
    name: string;
    graph_sha256: string;
  }>(await saving, 201);
  await visible.getByRole("button", { name: "Open Workflow Builder" }).click();
  const replays: { id: string; payloadSha256: string }[] = [];
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt) {
      await openProject();
      await page
        .getByRole("tab", { name: "Video & automation", exact: true })
        .click();
      await page
        .getByRole("tab", { name: "Workflow builder", exact: true })
        .click();
    }
    const saved = page.getByRole("listitem").filter({ hasText: graph.name });
    await saved.getByRole("button", { name: "Load", exact: true }).click();
    const running = post(`${endpoint}/workflow-runs`);
    await saved
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const { id } = await checked<{ id: string }>(await running, 202);
    let detail:
      | {
          run: { status: string; error_message: string | null };
          artifacts: {
            data_type: string;
            payload_sha256: string;
            payload_json: unknown;
          }[];
        }
      | undefined;
    await expect
      .poll(async () => {
        detail = await checked(
          await page.request.get(`${api}/workflow-runs/${id}`),
        );
        return detail!.run.status;
      })
      .not.toMatch(/queued|running/);
    expect(detail!.run.status, detail!.run.error_message ?? undefined).toBe(
      "succeeded",
    );
    const artifact = detail!.artifacts.find(
      (row) => row.data_type === "domain_shift_report",
    );
    expect(artifact?.payload_json).toEqual(report);
    replays.push({ id, payloadSha256: artifact!.payload_sha256 });
  }
  expect(replays[0].id).not.toBe(replays[1].id);
  expect(replays[0].payloadSha256).toBe(replays[1].payloadSha256);
  for (const image of fixture.original_images)
    expect((await verifyOriginal(page, api, image.id)).sha256).toBe(
      image.sha256,
    );
  await writeFile(
    info.outputPath("domain-shift-evidence.json"),
    JSON.stringify(
      {
        surface,
        applicationVersion: runtime.application_version,
        schemaRevision: runtime.schema_revision,
        projectId: fixture.project_id,
        comparisonId: fixture.comparison_id,
        comparisonSha256: fixture.report_sha256,
        reportId,
        reportSha256: report.content_sha256,
        referenceSha256: fixture.reference_sha256,
        checkpointSha256: fixture.checkpoint_sha256,
        groups: snapshot.summary.groups,
        adjustments: snapshot.declaration.adjustments,
        inferenceJobIds: jobIds,
        jsonSha256: sha256(json),
        csvSha256: sha256(csv),
        graphId: graph.id,
        graphSha256: graph.graph_sha256,
        replays,
      },
      null,
      2,
    ),
  );
});
