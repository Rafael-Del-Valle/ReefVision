import { expect, type Page, type Response } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import {
  checked,
  heldOutGroups,
  seedPairedStills,
  verifyOriginal,
} from "./pairedStillComparisonFixture";
import { test } from "./spatialDesktop";

const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
const checksum = /^[a-f0-9]{64}$/;

interface Observation {
  media_id: string;
  media_kind: string;
  exclusion: string | null;
  metrics: {
    name: string;
    left: number | null;
    right: number | null;
    unit: string;
  }[];
}

interface Report {
  content_sha256: string;
  snapshot: {
    comparison_id: string;
    models: { model_id: string; receipt: { checkpoint_sha256: string } }[];
    evidence: {
      evaluation_status: string;
      reference_id: string;
      reference_sha256: string;
      groups: { group_id: string; observations: Observation[] }[];
    };
    summary: { group_count: number; excluded_observations: number };
  };
}

function posting(page: Page, path: string) {
  return page.waitForResponse(
    (request) =>
      request.request().method() === "POST" && request.url() === path,
  );
}

async function written<T>(response: Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

test("compares two local detectors on held-out originals and replays the saved comparison", async ({
  desktop: { page, api, web, surface },
}, info) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(15_000);
  const fixture = await seedPairedStills(page, api);
  const { version } = JSON.parse(await readFile("package.json", "utf8")) as {
    version: string;
  };
  await page.addInitScript((value) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${value}`, "true");
  }, version);
  async function openProject() {
    await page.goto(web);
    await page
      .getByRole("button", {
        name: `Open ${fixture.project_name}`,
        exact: true,
      })
      .click();
  }
  async function openComparison() {
    await openProject();
    await page.getByRole("tab", { name: "Models & AI", exact: true }).click();
    await page
      .getByRole("tab", { name: "Model comparison", exact: true })
      .click();
    return page.getByRole("region", { name: "Model comparison", exact: true });
  }

  const endpoint = `${api}/projects/${fixture.project_id}`;
  const comparisons = endpoint + "/paired-model-comparisons";
  const workspace = await openComparison();
  const [left, right] = fixture.registered_model_choices;
  expect(left.checkpoint_sha256).toMatch(checksum);
  expect(right.checkpoint_sha256).toMatch(checksum);
  expect(left.checkpoint_sha256).not.toBe(right.checkpoint_sha256);
  await workspace.getByLabel("Comparison task").selectOption("detector");
  await workspace
    .getByLabel("Left reviewed configuration")
    .selectOption(left.runtime_selection_id);
  await workspace
    .getByLabel("Right reviewed configuration")
    .selectOption(right.runtime_selection_id);
  await workspace
    .getByLabel("Frozen dataset")
    .selectOption(fixture.report.reference_id);

  const launching = posting(page, comparisons);
  await workspace
    .getByRole("button", { name: "Run paired comparison" })
    .click();
  const { id } = await written<{ id: string }>(await launching, 202);
  let job!: {
    status: string;
    error_message: string | null;
    result_json: Report;
  };
  await expect
    .poll(
      async () => {
        job = await checked(await page.request.get(`${comparisons}/${id}`));
        return job.status;
      },
      { timeout: 60_000 },
    )
    .not.toMatch(/queued|running/);
  expect(job.status, job.error_message ?? undefined).toBe("succeeded");
  const report = job.result_json;
  expect(report.content_sha256).toMatch(checksum);
  expect(report.snapshot.comparison_id).toBe(id);
  expect(
    report.snapshot.models.map((model) => [
      model.model_id,
      model.receipt.checkpoint_sha256,
    ]),
  ).toEqual([
    [left.model_id, left.checkpoint_sha256],
    [right.model_id, right.checkpoint_sha256],
  ]);
  const { evidence, summary } = report.snapshot;
  expect(evidence.evaluation_status).toBe("held_out");
  expect(evidence.reference_id).toBe(fixture.report.reference_id);
  expect(evidence.reference_sha256).toBe(fixture.report.reference_sha256);
  expect(summary.group_count).toBe(2);
  expect(summary.excluded_observations).toBe(0);
  expect(evidence.groups.map(({ group_id }) => group_id)).toEqual(
    heldOutGroups,
  );
  const observations = evidence.groups.flatMap((group) => group.observations);
  expect(observations).toHaveLength(3);
  expect(new Set(observations.map((row) => row.media_id)).size).toBe(3);
  const originals = await Promise.all(
    observations.map(async (row) => ({
      id: row.media_id,
      ...(await verifyOriginal(page, api, row.media_id)),
    })),
  );

  const results = page.getByRole("region", {
    name: "Paired comparison results",
  });
  await expect(
    results.getByText(
      /Held-out · 2 independent groups · 0 excluded observations/,
    ),
  ).toBeVisible();
  const disagreement = observations.find((row) =>
    row.metrics.some((m) => m.left !== m.right),
  );
  if (!disagreement)
    await results.getByLabel("Include matching observations").check();
  const observed = disagreement ?? observations[0];
  await results
    .getByRole("button", {
      name: `Open image ${observed.media_id.slice(0, 8)}`,
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Paired comparison evidence", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByText(
        originals.find((item) => item.id === observed.media_id)!
          .original_filename,
        { exact: true },
      )
      .first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Back to model comparison", exact: true })
    .click();
  if (!(await results.isVisible())) {
    await workspace
      .getByRole("button", { name: `Detector · ${id.slice(0, 8)} · succeeded` })
      .click();
  }

  async function exported(label: string, format: "json" | "csv") {
    const download = page.waitForEvent("download");
    await results.getByRole("link", { name: label, exact: true }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe(`paired-models-${id}.${format}`);
    const path = info.outputPath(file.suggestedFilename());
    await file.saveAs(path);
    const saved = await readFile(path);
    const source = await page.request.get(
      `${comparisons}/${id}/export?format=${format}`,
    );
    expect(source.status()).toBe(200);
    expect(sha256(saved)).toBe(sha256(await source.body()));
    return saved;
  }
  const json = await exported("Export comparison JSON", "json");
  expect(JSON.parse(json.toString("utf8"))).toEqual(report);
  const csv = await exported("Export paired observations CSV", "csv");
  const [header, ...rows] = csv.toString("utf8").trim().split(/\r?\n/);
  expect(header).toBe(
    "group,media_kind,media_id,frame,seconds,metric,unit,left,right,exclusion,report_sha256",
  );
  expect(rows).toHaveLength(
    observations.reduce((sum, row) => sum + row.metrics.length, 0),
  );
  for (const row of observations)
    expect(rows.some((line) => line.includes(row.media_id))).toBeTruthy();
  expect(
    rows.every((line) => line.endsWith("," + report.content_sha256)),
  ).toBeTruthy();

  const saving = posting(page, endpoint + "/workflow-graphs");
  await results
    .getByRole("button", { name: "Save comparison workflow", exact: true })
    .click();
  const graph = await written<{
    id: string;
    name: string;
    graph_sha256: string;
  }>(await saving, 201);
  await results
    .getByRole("button", {
      name: "Open saved comparison workflow",
      exact: true,
    })
    .click();
  const replays: { id: string; payload_sha256: string }[] = [];
  for (let index = 0; index < 2; index++) {
    if (index === 1) {
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
    const running = posting(page, endpoint + "/workflow-runs");
    await saved
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const run = await written<{ id: string }>(await running, 202);
    let detail!: {
      run: { status: string; error_message: string | null };
      artifacts: {
        data_type: string;
        payload_sha256: string;
        payload_json: unknown;
      }[];
    };
    await expect
      .poll(
        async () => {
          detail = await checked(
            await page.request.get(`${api}/workflow-runs/${run.id}`),
          );
          return detail.run.status;
        },
        { timeout: 60_000 },
      )
      .not.toMatch(/queued|running/);
    expect(detail.run.status, detail.run.error_message ?? undefined).toBe(
      "succeeded",
    );
    const [proof] = detail.artifacts.filter(
      (item) => item.data_type === "paired_model_report",
    );
    expect(proof.payload_json).toEqual({
      snapshot: report.snapshot,
      content_sha256: report.content_sha256,
    });
    expect(proof.payload_sha256).toMatch(checksum);
    replays.push({ id: run.id, payload_sha256: proof.payload_sha256 });
  }
  expect(replays[0].id).not.toBe(replays[1].id);
  expect(replays[0].payload_sha256).toBe(replays[1].payload_sha256);
  for (const original of originals) {
    expect((await verifyOriginal(page, api, original.id)).sha256).toBe(
      original.sha256,
    );
  }
  await writeFile(
    info.outputPath("paired-model-comparison-evidence.json"),
    JSON.stringify(
      {
        surface,
        fixture_source: fixture.fixture_source,
        project_id: fixture.project_id,
        comparison_id: id,
        training_runs: fixture.training_runs,
        checkpoint_sha256: [left.checkpoint_sha256, right.checkpoint_sha256],
        report_sha256: report.content_sha256,
        reference_sha256: evidence.reference_sha256,
        groups: evidence.groups.map((group) => ({
          id: group.group_id,
          observations: group.observations.length,
        })),
        inspected_observation_id: observed.media_id,
        inspected_disagreement: Boolean(disagreement),
        original_images: originals,
        json_sha256: sha256(json),
        csv_sha256: sha256(csv),
        graph_id: graph.id,
        graph_sha256: graph.graph_sha256,
        replays,
      },
      null,
      2,
    ),
  );
});
