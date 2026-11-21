import { createHash, randomUUID } from "node:crypto";
import { readFile, realpath, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";

import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";

import type { Project } from "../../src/api/client";
import type { ScientificRecord } from "../../src/features/environmental-context/environmentalContextApi";
import type { EventSummary } from "../../src/features/ecology/EventSummaryPanel";
import type {
  MonitoringAlert,
  MonitoringAssessment,
  MonitoringReview,
  MonitoringRule,
  MonitoringSummary,
} from "../../src/features/monitoring/monitoringApi";
import type {
  WorkflowGraphRecord,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import { test } from "./spatialDesktop";

const protocol = "example-minute-temperature-v1";
const windowStart = "2026-11-19T13:00:00Z";
const windowEnd = "2026-11-19T13:05:00Z";
const version = process.env.REEFVISION_MONITORING_EXPECTED_VERSION ?? "2.0.0";

async function checked<T>(response: APIResponse | Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

async function confirmDisposableRuntime(page: Page, api: string) {
  const root = process.env.REEFVISION_MONITORING_EXPECTED_DATA_DIR;
  const schema = process.env.REEFVISION_MONITORING_EXPECTED_SCHEMA;
  if (!root || !schema)
    throw new Error(
      "Set the independently verified monitoring QA profile and schema.",
    );
  expect(new URL(api).origin).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
  const dataDir = await realpath(root);
  const marked = await Promise.all(
    [".reefvision-clean-install-acceptance", ".reefvision-disposable-qa"].map(
      (marker) =>
        stat(join(dataDir, marker))
          .then((result) => result.isFile())
          .catch(() => false),
    ),
  );
  expect(marked).toContain(true);
  const runtime = await checked<{
    application_version: string;
    data_dir: string;
    database_path: string;
    current_schema_revision: string;
    expected_schema_revision: string;
    safe_mode: boolean;
  }>(await page.request.get(`${api}/system/version`), 200);
  expect(runtime).toEqual(
    expect.objectContaining({
      application_version: version,
      current_schema_revision: schema,
      expected_schema_revision: schema,
      safe_mode: false,
    }),
  );
  expect(await realpath(runtime.data_dir)).toBe(dataDir);
  expect(await realpath(runtime.database_path)).toBe(
    await realpath(join(dataDir, "reefvision.db")),
  );
  return schema;
}

const waitPost = (page: Page, url: string) =>
  page.waitForResponse(
    (response) =>
      response.url() === url && response.request().method() === "POST",
  );

const dateInput = (isoUtc: string) => isoUtc.slice(0, 19).replace(/:00$/, "");

async function openProject(page: Page, web: string, project: Project) {
  await page.goto(web);
  await page
    .getByRole("button", { name: `Open ${project.name}`, exact: true })
    .click();
}

async function openMonitoring(page: Page, web: string, project: Project) {
  await openProject(page, web, project);
  await page.getByRole("tab", { name: "Research", exact: true }).click();
  await page.getByRole("tab", { name: "Monitoring", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Monitoring workspace" }),
  ).toBeVisible();
}

async function replay(
  page: Page,
  api: string,
  web: string,
  project: Project,
  graph: WorkflowGraphRecord,
  dataType: string,
) {
  const result = [];
  for (const _ of [1, 2]) {
    await openProject(page, web, project);
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
    const row = page.getByRole("listitem").filter({
      hasText: graph.name,
      has: page.getByRole("button", {
        name: "Run saved revision",
        exact: true,
      }),
    });
    const queued = waitPost(
      page,
      `${api}/projects/${project.id}/workflow-runs`,
    );
    await row
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const { id } = await checked<{ id: string }>(await queued, 202);
    let detail!: WorkflowRunDetail;
    await expect
      .poll(
        async () => {
          detail = await checked<WorkflowRunDetail>(
            await page.request.get(`${api}/workflow-runs/${id}`),
            200,
          );
          return detail.run.status;
        },
        { timeout: 40_000 },
      )
      .not.toMatch(/queued|running/);
    expect(detail.run.status, detail.run.error_message ?? undefined).toBe(
      "succeeded",
    );
    expect(detail.run.project_id).toBe(project.id);
    expect(detail.run.workflow_graph_record_id).toBe(graph.id);
    const artifact = detail.artifacts.find(
      (record) => record.data_type === dataType,
    )!;
    expect(artifact.payload_sha256).toMatch(/^[a-f0-9]{64}$/);
    await expect(
      page.getByText(dataType, { exact: true }).last(),
    ).toBeVisible();
    result.push({
      id,
      payloadSha256: artifact.payload_sha256,
      payload: artifact.payload_json,
    });
  }
  expect(result[0].id).not.toBe(result[1].id);
  expect(result[0].payloadSha256).toBe(result[1].payloadSha256);
  expect(result[0].payload).toEqual(result[1].payload);
  return result;
}

test("reviews monitoring findings and compares only compatible project-local assessments", async ({
  desktop,
}, info) => {
  test.setTimeout(180_000);
  const { page, api, web, surface } = desktop;
  const schema = await confirmDisposableRuntime(page, api);
  await page.addInitScript((release) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${release}`, "true");
  }, version);

  const caseId = randomUUID().slice(0, 8);
  async function seed(
    site: string,
    unit: string,
    values: Array<number | null>,
  ) {
    const project = await checked<Project>(
      await page.request.post(`${api}/projects`, {
        data: {
          name: `Monitoring fixture ${site} ${caseId}`,
          template: "blank",
        },
      }),
      201,
    );
    const original = await checked<{ items: ScientificRecord[] }>(
      await page.request.post(
        `${api}/projects/${project.id}/scientific-records`,
        {
          data: {
            records: values.flatMap((value, minute) =>
              value === null
                ? []
                : [
                    {
                      variable: "water_temperature",
                      value,
                      unit,
                      observed_at: `2026-11-19T13:0${minute}:00Z`,
                      source_kind: "observed",
                      qc: "accepted",
                      provenance: {
                        source: `Generated logger ${site}`,
                        acquired_at: `2026-11-19T13:0${minute + (site === "A" && minute === 3 ? 2 : 0)}:00Z`,
                        method:
                          "Generated monitoring fixture with known inputs",
                        temporal_resolution_s: 60,
                        source_metadata: { synthetic: true, protocol },
                      },
                    },
                  ],
            ),
          },
        },
      ),
      201,
    );
    return { project, original: original.items };
  }
  const north = await seed("A", "degF", [68, 68, null, 71.6, 68]);
  const south = await seed("B", "degC", [20, 20, 20, 20, 20]);
  const short = await seed("C", "degC", [20, 20, 20, 20, 20]);
  const monitor = (project: Project) =>
    `${api}/projects/${project.id}/monitoring`;

  async function assess(project: Project, end = windowEnd) {
    await openMonitoring(page, web, project);
    await page
      .getByRole("button", { name: "New monitoring rule", exact: true })
      .click();
    const ruleForm = page.getByRole("form", {
      name: "New monitoring rule",
      exact: true,
    });
    await ruleForm.getByLabel("Rule name").fill("Minute water temperature");
    await ruleForm.getByLabel("Protocol", { exact: true }).fill(protocol);
    await ruleForm
      .getByLabel("Metric", { exact: true })
      .fill("water_temperature");
    await ruleForm.getByLabel("Unit", { exact: true }).fill("degC");
    await ruleForm.getByLabel("Cadence (seconds)").fill("60");
    await ruleForm.getByLabel("Upper limit").fill("21");
    await ruleForm
      .getByLabel("Maximum change between adjacent accepted observations")
      .fill("1");
    await ruleForm.getByLabel("Maximum acquisition delay (seconds)").fill("30");
    const created = waitPost(page, `${monitor(project)}/rules`);
    await ruleForm
      .getByRole("button", { name: "Create monitoring rule" })
      .click();
    const rule = await checked<MonitoringRule>(await created, 201);
    expect(rule.protocol).toBe(protocol);
    expect(rule.rule_sha256).toMatch(/^[a-f0-9]{64}$/);
    await page.getByLabel("Window start (UTC)").fill(dateInput(windowStart));
    await page.getByLabel("Window end (UTC)").fill(dateInput(end));
    const assessing = waitPost(page, `${monitor(project)}/assessments`);
    await page
      .getByRole("button", { name: "Assess monitoring window" })
      .click();
    const assessment = await checked<MonitoringAssessment>(
      await assessing,
      201,
    );
    expect(Date.parse(assessment.window_start)).toBe(Date.parse(windowStart));
    expect(Date.parse(assessment.window_end)).toBe(Date.parse(end));
    expect(assessment.rule_id).toBe(rule.id);
    await expect(
      page.getByRole("region", { name: "Assessment evidence" }),
    ).toBeVisible();
    return { assessment, rule };
  }

  const b = await assess(south.project);
  expect(b.assessment.result.estimate).toBe(20);
  expect(b.assessment.result.findings).toEqual([]);
  const c = await assess(short.project, "2026-11-19T13:04:00Z");
  expect(c.assessment.result.effort.expected_slots).toBe(4);
  const a = await assess(north.project);
  expect(a.assessment.result.estimate).toBeCloseTo(20.5, 10);
  expect(a.assessment.result.effort).toEqual(
    expect.objectContaining({
      expected_slots: 5,
      observed_slots: 4,
      accepted_observations: 4,
    }),
  );
  const findings = (
    await checked<{ items: MonitoringAlert[] }>(
      await page.request.get(
        `${monitor(north.project)}/alerts?assessment_id=${a.assessment.id}`,
      ),
      200,
    )
  ).items;
  expect(new Set(findings.map((alert) => alert.kind))).toEqual(
    new Set(["drop", "delay", "drift", "upper_limit"]),
  );
  expect(findings.every((alert) => alert.status === "proposed")).toBe(true);
  const high = findings.find((alert) => alert.kind === "upper_limit")!;
  const highCard = page.getByRole("article", {
    name: high.proposal.detail,
    exact: true,
  });
  await highCard.getByText("Inspect linked evidence", { exact: true }).click();
  await expect(highCard.getByText("71.6 degF", { exact: true })).toBeVisible();
  await expect(highCard.getByText("22 degC", { exact: true })).toBeVisible();
  const reviews: MonitoringReview[] = [];
  for (const finding of findings) {
    const card = page.getByRole("article", {
      name: finding.proposal.detail,
      exact: true,
    });
    await card
      .getByRole("button", { name: "Review finding", exact: true })
      .click();
    const confirmed = finding.kind === "drop";
    const reason = confirmed
      ? "Confirmed missing slot in the generated station ledger."
      : `Dismissed synthetic ${finding.kind} for the fixture review.`;
    await card.getByLabel("Review reason").fill(reason);
    const sent = waitPost(
      page,
      `${monitor(north.project)}/alerts/${finding.id}/reviews`,
    );
    await card
      .getByRole("button", {
        name: confirmed ? "Confirm finding" : "Dismiss finding",
        exact: true,
      })
      .click();
    const review = await checked<MonitoringReview>(await sent, 201);
    expect(review).toEqual(
      expect.objectContaining({
        project_id: north.project.id,
        alert_id: finding.id,
        decision: confirmed ? "confirmed" : "dismissed",
        reason,
        revision: 1,
        reviewer: expect.any(String),
      }),
    );
    await expect(
      card.getByRole("region", { name: "Review history" }).getByText(reason),
    ).toBeVisible();
    reviews.push(review);
  }

  await openMonitoring(page, web, north.project);
  await page
    .getByRole("combobox", { name: "Saved assessment", exact: true })
    .selectOption(a.assessment.id);
  const replaySaved = waitPost(
    page,
    `${api}/projects/${north.project.id}/workflow-graphs`,
  );
  await page.getByRole("button", { name: "Save assessment workflow" }).click();
  const graph = await checked<WorkflowGraphRecord>(await replaySaved, 201);
  const assessmentReplays = await replay(
    page,
    api,
    web,
    north.project,
    graph,
    "monitoring_assessment",
  );
  for (const run of assessmentReplays) {
    expect(run.payload).toEqual(
      expect.objectContaining({
        assessment_id: a.assessment.id,
        evidence_sha256: a.assessment.evidence_sha256,
        result_sha256: a.assessment.result_sha256,
      }),
    );
  }

  await openMonitoring(page, web, north.project);
  await page
    .getByRole("tab", { name: "Project summaries", exact: true })
    .click();
  await page.getByLabel("Reference assessment").selectOption(a.assessment.id);
  await page
    .getByLabel("Comparison project 1")
    .selectOption({ label: south.project.name });
  await page
    .getByLabel("Comparison assessment 1")
    .selectOption(b.assessment.id);
  await page.getByRole("button", { name: "Add comparison project" }).click();
  await page
    .getByLabel("Comparison project 2")
    .selectOption({ label: short.project.name });
  await page
    .getByLabel("Comparison assessment 2")
    .selectOption(c.assessment.id);
  const comparing = waitPost(page, `${monitor(north.project)}/summaries`);
  await page.getByRole("button", { name: "Compare projects" }).click();
  const summary = await checked<MonitoringSummary>(await comparing, 201);
  expect(summary.snapshot.reference_project_id).toBe(north.project.id);
  expect(
    summary.snapshot.rows.map((row) => [
      row.project_id,
      row.assessment_id,
      row.status,
    ]),
  ).toEqual([
    [north.project.id, a.assessment.id, "included"],
    [south.project.id, b.assessment.id, "included"],
    [short.project.id, c.assessment.id, "excluded"],
  ]);
  expect(summary.snapshot.rows[0].review).toEqual(
    expect.objectContaining({ proposed: 0, confirmed: 1, dismissed: 3 }),
  );
  expect(summary.snapshot.rows[1].review).toEqual(
    expect.objectContaining({ proposed: 0, confirmed: 0, dismissed: 0 }),
  );
  expect(summary.snapshot.rows[2].reasons).toContain(
    "The UTC observation windows differ.",
  );
  const summaryCard = page.getByRole("region", {
    name: "Saved project summary",
  });
  await expect(
    summaryCard
      .getByRole("article", { name: short.project.name })
      .getByText("Excluded", { exact: true }),
  ).toBeVisible();
  await expect(
    summaryCard
      .getByRole("article", { name: north.project.name })
      .getByText("20.5 degC", { exact: true }),
  ).toBeVisible();
  await expect(
    summaryCard
      .getByRole("article", { name: south.project.name })
      .getByText("20 degC", { exact: true }),
  ).toBeVisible();

  await openMonitoring(page, web, north.project);
  await page
    .getByRole("tab", { name: "Project summaries", exact: true })
    .click();
  await page.getByRole("button", { name: /^Open project summary/ }).click();
  const downloadEvent = page.waitForEvent("download");
  const exported = page.waitForResponse(
    (response) =>
      response.url() ===
      `${monitor(north.project)}/summaries/${summary.id}/export`,
  );
  await page.getByRole("button", { name: "Download summary JSON" }).click();
  const download = await downloadEvent;
  const received = await readFile(await download.path());
  const response = await exported;
  expect(response.status()).toBe(200);
  expect(await response.body()).toEqual(received);
  expect(download.suggestedFilename()).toContain(summary.content_sha256);
  expect(JSON.parse(received.toString("utf8"))).toEqual(summary);
  const save = waitPost(
    page,
    `${api}/projects/${north.project.id}/workflow-graphs`,
  );
  await page.getByRole("button", { name: "Save summary workflow" }).click();
  const summaryGraph = await checked<WorkflowGraphRecord>(await save, 201);
  const summaryReplays = await replay(
    page,
    api,
    web,
    north.project,
    summaryGraph,
    "monitoring_project_summary",
  );
  for (const run of summaryReplays) expect(run.payload).toEqual(summary);

  for (const site of [north, south, short]) {
    const originals = await checked<{ items: ScientificRecord[] }>(
      await page.request.get(
        `${api}/projects/${site.project.id}/scientific-records`,
      ),
      200,
    );
    const rows = (items: ScientificRecord[]) =>
      [...items].sort((first, second) => first.id.localeCompare(second.id));
    expect(rows(originals.items)).toEqual(rows(site.original));
  }
  const biologyFixture = process.env.REEFVISION_MONITORING_BIO_FIXTURE;
  let biological: Record<string, unknown> | undefined;
  if (biologyFixture) {
    const fixture = JSON.parse(await readFile(biologyFixture, "utf8")) as {
      project_id: string;
      summary_id: string;
      protocol_sha256: string;
      video_sha256: string;
    };
    const project = await checked<Project>(
      await page.request.get(`${api}/projects/${fixture.project_id}`),
      200,
    );
    const reviewed = await checked<EventSummary>(
      await page.request.get(
        `${api}/projects/${project.id}/ecology/event-summaries/${fixture.summary_id}`,
      ),
      200,
    );
    expect(reviewed.stale_reasons).toEqual([]);
    expect(reviewed.snapshot.protocol_sha256).toBe(fixture.protocol_sha256);
    await openMonitoring(page, web, project);
    await page
      .getByRole("button", { name: "New monitoring rule", exact: true })
      .click();
    await page.getByLabel("Source type").selectOption("biological");
    await page.getByLabel("Rule name").fill("Dated reviewed event effort");
    await page
      .getByRole("checkbox", {
        name: reviewed.snapshot.selection.name,
        exact: true,
      })
      .check();
    await page.getByLabel("Minimum effort (seconds)").fill("1");
    const ruleResponse = waitPost(page, `${monitor(project)}/rules`);
    await page.getByRole("button", { name: "Create monitoring rule" }).click();
    const rule = await checked<MonitoringRule>(await ruleResponse, 201);
    expect(rule).toEqual(
      expect.objectContaining({
        kind: "biological",
        protocol: fixture.protocol_sha256,
        metric: "confirmed_events_per_minute",
        unit: "events/min",
      }),
    );
    await page.getByLabel("Window start (UTC)").fill("2026-01-01T10:00");
    await page.getByLabel("Window end (UTC)").fill("2026-01-01T10:01");
    const assessed = waitPost(page, `${monitor(project)}/assessments`);
    await page
      .getByRole("button", { name: "Assess monitoring window" })
      .click();
    const record = await checked<MonitoringAssessment>(await assessed, 201);
    expect(record.result.estimate).toBeCloseTo(60 / 4.7, 10);
    expect(record.result.effort.valid_duration_s).toBeCloseTo(4.7, 10);
    expect(record.result.effort.confirmed_event_count).toBe(1);
    expect(record.result.biological_sessions).toHaveLength(1);
    expect(record.result.biological_sessions?.[0]).toEqual(
      expect.objectContaining({
        summary_id: reviewed.id,
        video_sha256: fixture.video_sha256,
        confirmed_event_count: 1,
      }),
    );
    await page
      .getByText("Reviewed biological sessions (1)", { exact: true })
      .click();
    await expect(
      page.getByText(fixture.video_sha256, { exact: true }),
    ).toBeVisible();
    biological = {
      project_id: project.id,
      summary_id: reviewed.id,
      assessment_id: record.id,
      result_sha256: record.result_sha256,
      evidence_sha256: record.evidence_sha256,
      method: record.result.method,
      protocol_sha256: record.result.protocol,
      estimate: record.result.estimate,
      unit: record.result.unit,
      effort: record.result.effort,
      video_sha256: fixture.video_sha256,
    };
  }
  const path = info.outputPath("monitoring-proof.json");
  await writeFile(
    path,
    JSON.stringify(
      {
        surface,
        version,
        schema,
        generated_fixture: true,
        biological,
        assessments: [a, b, c].map(({ assessment }) => ({
          project_id: assessment.project_id,
          id: assessment.id,
          evidence_sha256: assessment.evidence_sha256,
          result_sha256: assessment.result_sha256,
          effort: assessment.result.effort,
        })),
        findings: findings.map(({ id, kind, proposal_sha256 }) => ({
          id,
          kind,
          proposal_sha256,
        })),
        reviews,
        summary: {
          id: summary.id,
          content_sha256: summary.content_sha256,
          project_rows: summary.snapshot.rows.map(
            ({ project_id, status, reasons }) => ({
              project_id,
              status,
              reasons,
            }),
          ),
        },
        export_sha256: createHash("sha256").update(received).digest("hex"),
        assessment_replays: assessmentReplays.map(({ id, payloadSha256 }) => ({
          id,
          payloadSha256,
        })),
        summary_replays: summaryReplays.map(({ id, payloadSha256 }) => ({
          id,
          payloadSha256,
        })),
      },
      null,
      2,
    ),
  );
  await info.attach("monitoring-proof", {
    path,
    contentType: "application/json",
  });
});
