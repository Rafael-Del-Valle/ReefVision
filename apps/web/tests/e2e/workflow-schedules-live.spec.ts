import { createHash, randomUUID } from "node:crypto";
import { readFile, realpath, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";

import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";

import type {
  DatasetVersionRecord,
  Project,
  ReviewQueueItem,
} from "../../src/api/client";
import type {
  WorkflowGraphRecord,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import type {
  ScheduleOccurrence,
  WorkflowSchedule,
  WorkflowScheduleReceipt,
} from "../../src/features/workflow-schedules/workflowScheduleApi";
import { test } from "./spatialDesktop";

type ImageOriginal = { id: string; sha256: string };

interface FrozenQcFixture {
  projectId: string;
  projectName: string;
  graphId: string;
  datasetId: string;
  manifestSha256: string;
  images: ImageOriginal[];
}

interface RestartWitness {
  fixture: FrozenQcFixture;
  graphSha256: string;
  schedule: WorkflowSchedule;
  first: ScheduleOccurrence;
  paused: WorkflowSchedule;
}

const graphLabel = "QC review queue from a frozen dataset";
const intervalSeconds = 30;

async function checked<T>(response: APIResponse | Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

function sha256(bytes: Buffer) {
  return createHash("sha256").update(bytes).digest("hex");
}

function waitForWrite(page: Page, url: string, method = "POST") {
  return page.waitForResponse(
    (response) =>
      response.url() === url && response.request().method() === method,
  );
}

async function verifyDisposableRuntime(page: Page, api: string) {
  const data = process.env.REEFVISION_SCHEDULE_TEST_EXPECTED_DATA_DIR;
  const version = process.env.REEFVISION_SCHEDULE_TEST_EXPECTED_VERSION;
  const schema = process.env.REEFVISION_SCHEDULE_TEST_EXPECTED_SCHEMA;
  if (!data || !version || !schema) {
    throw new Error(
      "Schedule acceptance requires an independently recorded disposable data directory, application version, and schema.",
    );
  }
  expect(new URL(api).origin).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
  const expected = await realpath(data);
  const markers = await Promise.all(
    [".reefvision-clean-install-acceptance", ".reefvision-disposable-qa"].map(
      (marker) =>
        stat(join(expected, marker))
          .then((result) => result.isFile())
          .catch(() => false),
    ),
  );
  expect(markers).toContain(true);
  const runtime = await checked<{
    data_dir: string;
    database_path: string;
    application_version: string;
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
  expect(await realpath(runtime.data_dir)).toBe(expected);
  expect(await realpath(runtime.database_path)).toBe(
    await realpath(join(expected, "reefvision.db")),
  );
  return runtime;
}

async function openProject(page: Page, web: string, name: string) {
  await page.goto(web);
  await page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
}

async function seedFrozenQc(
  page: Page,
  api: string,
  web: string,
): Promise<FrozenQcFixture> {
  const name = `Scheduled frozen QC ${randomUUID().slice(0, 8)}`;
  const { id: projectId } = await checked<Project>(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
    201,
  );
  const root = `${api}/projects/${projectId}`;
  const label = await checked<{ id: string }>(
    await page.request.post(`${root}/classes`, {
      data: {
        name: "Synthetic outline",
        class_index: 0,
        display_color: "#B79870",
      },
    }),
    201,
  );
  const images: ImageOriginal[] = [];
  await page.goto(web);
  for (const width of [40, 41]) {
    const base64 = await page.evaluate((width) => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = 40;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#386578";
      context.fillRect(0, 0, width, 40);
      context.fillStyle = "#b79870";
      context.fillRect(5, 5, 20, 20);
      return canvas.toDataURL("image/png").split(",")[1];
    }, width);
    const bytes = Buffer.from(base64, "base64");
    const file = `schedule-qc-${width}.png`;
    const imported = await checked<{ successful: { image_id: string }[] }>(
      await page.request.post(`${root}/imports/images`, {
        multipart: {
          files: { name: file, mimeType: "image/png", buffer: bytes },
          relative_paths: file,
        },
      }),
      200,
    );
    const id = imported.successful[0].image_id;
    images.push({ id, sha256: sha256(bytes) });
    await checked(
      await page.request.put(`${api}/images/${id}/annotations`, {
        data: {
          base_revision: 0,
          annotation_status: "reviewed",
          annotations: [
            {
              id: randomUUID(),
              label_class_id: label.id,
              x_min: 5,
              y_min: 5,
              x_max: 25,
              y_max: 25,
            },
          ],
        },
      }),
      200,
    );
  }
  const dataset = await checked<DatasetVersionRecord>(
    await page.request.post(`${root}/dataset-versions`, {
      data: {
        name: "Scheduled frozen QC source",
        eligible_annotation_statuses: ["reviewed"],
        split_method: "group_random",
        requested_ratios: { train: 0.7, validation: 0.2, test: 0.1 },
        split_seed: 11,
      },
    }),
    201,
  );
  await openProject(page, web, name);
  await page
    .getByRole("tab", { name: "Workflow builder", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: /^Template/ })
    .selectOption({ label: graphLabel });
  await page
    .locator('[data-node-id="dataset"]')
    .getByRole("button", { name: "Configure", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: /^Frozen dataset version/ })
    .selectOption(dataset.id);
  const save = waitForWrite(page, `${root}/workflow-graphs`);
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  const graph = await checked<WorkflowGraphRecord>(await save, 201);

  return {
    projectId,
    projectName: name,
    graphId: graph.id,
    datasetId: dataset.id,
    manifestSha256: dataset.manifest_sha256,
    images,
  };
}

test("schedules a frozen QC workflow and follows its durable occurrence to review", async ({
  desktop,
}, info) => {
  test.setTimeout(180_000);
  const { page, web, api, surface } = desktop;
  const phase = process.env.REEFVISION_SCHEDULE_TEST_PHASE ?? "single";
  const fixturePath = process.env.REEFVISION_SCHEDULE_TEST_FIXTURE;
  const witnessPath = process.env.REEFVISION_SCHEDULE_TEST_RESTART_WITNESS;
  expect(["single", "before-restart", "after-restart"]).toContain(phase);
  if (phase !== "single" && !witnessPath)
    throw new Error("Schedule restart proof needs a witness path.");
  const preceding =
    phase === "after-restart"
      ? (JSON.parse(await readFile(witnessPath!, "utf8")) as RestartWitness)
      : null;
  const runtime = await verifyDisposableRuntime(page, api);
  const health = await checked<{ version: string }>(
    await page.request.get(`${api}/health`),
    200,
  );
  expect(health.version).toBe(runtime.application_version);
  await page.addInitScript((version) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${version}`, "true");
  }, health.version);

  const fixture =
    preceding?.fixture ??
    (fixturePath
      ? (JSON.parse(await readFile(fixturePath, "utf8")) as FrozenQcFixture)
      : await seedFrozenQc(page, api, web));
  const root = `${api}/projects/${fixture.projectId}`;
  const schedules = `${root}/workflow-schedules`;
  const savedGraphs = await checked<WorkflowGraphRecord[]>(
    await page.request.get(`${root}/workflow-graphs`),
    200,
  );
  const graph = savedGraphs.find((row) => row.id === fixture.graphId)!;
  expect(graph.project_id).toBe(fixture.projectId);
  expect(graph.graph_json.nodes).toContainEqual(
    expect.objectContaining({
      node_type: "dataset_version_source",
      parameters: { dataset_version_id: fixture.datasetId },
    }),
  );
  const history = async (id: string) =>
    (
      await checked<{ items: ScheduleOccurrence[]; total: number }>(
        await page.request.get(`${schedules}/${id}/occurrences`),
        200,
      )
    ).items;
  const current = async (id: string) =>
    (
      await checked<{ items: WorkflowSchedule[] }>(
        await page.request.get(schedules),
        200,
      )
    ).items.find((row) => row.id === id)!;
  const select = (name: string) =>
    page.getByRole("button", { name, exact: true }).click();
  async function openSchedules() {
    await openProject(page, web, fixture.projectName);
    await page.getByRole("tab", { name: "Schedules", exact: true }).click();
    await expect(
      page
        .getByRole("region", { name: "Schedules", exact: true })
        .getByRole("heading", { name: "Schedules", exact: true }),
    ).toBeVisible();
  }
  async function fillSchedule(
    name: string,
    offset: number,
    minimumFreeBytes = 0,
    purpose = "Quality control",
  ) {
    await page.getByLabel("Schedule name").fill(name);
    await page.getByLabel("Purpose").selectOption({ label: purpose });
    await page.getByLabel("Saved workflow revision").selectOption({
      label: `${graph.name} (revision ${graph.revision})`,
    });
    await expect(
      page.getByText(graph.graph_sha256, { exact: true }).first(),
    ).toBeVisible();
    await page
      .getByLabel("Repeat interval (seconds)")
      .fill(String(intervalSeconds));
    await page
      .getByLabel("Minimum free storage (bytes)")
      .fill(String(minimumFreeBytes));
    const date = new Date(Date.now() + offset)
      .toISOString()
      .slice(0, 19)
      .replace(/:00$/, "");
    await page.getByLabel("First due (UTC)").fill(date);
    return date;
  }
  async function createSchedule(
    name: string,
    offset: number,
    minimumFreeBytes = 0,
  ) {
    const date = await fillSchedule(name, offset, minimumFreeBytes);
    const creation = waitForWrite(page, schedules);
    await page.getByRole("button", { name: "Create schedule" }).click();
    const record = await checked<WorkflowSchedule>(await creation, 201);
    expect(record.workflow_graph_record_id).toBe(graph.id);
    expect(record.graph_sha256).toBe(graph.graph_sha256);
    expect(Date.parse(record.next_due_at)).toBe(Date.parse(`${date}Z`));
    return record;
  }
  async function pause(schedule: WorkflowSchedule) {
    const change = waitForWrite(page, `${schedules}/${schedule.id}`, "PATCH");
    await page
      .getByRole("button", { name: "Pause schedule", exact: true })
      .click();
    const paused = await checked<WorkflowSchedule>(await change, 200);
    expect(paused.enabled).toBe(false);
    expect(paused.revision).toBe(schedule.revision + 1);
    return paused;
  }
  async function waitForOccurrence(
    schedule: WorkflowSchedule,
    previousId?: string,
  ) {
    let target: ScheduleOccurrence | undefined;
    await expect
      .poll(
        async () => {
          target = (await history(schedule.id)).find(
            (item) => item.id !== previousId,
          );
          return target?.status ?? "no occurrence yet";
        },
        { timeout: 50_000 },
      )
      .toMatch(/^(succeeded|failed|cancelled|waiting_for_review)$/);
    expect(target?.status, target?.detail ?? undefined).toBe("succeeded");
    expect(target).toEqual(
      expect.objectContaining({
        project_id: fixture.projectId,
        schedule_id: schedule.id,
        graph_sha256: graph.graph_sha256,
        inputs_sha256: schedule.inputs_sha256,
        workflow_run_id: expect.any(String),
        job_id: expect.any(String),
      }),
    );
    return target!;
  }

  await openSchedules();
  let pausedControl: WorkflowSchedule;
  let rejectedPurpose: string | undefined;
  if (preceding) {
    pausedControl = preceding.paused;
    const persisted = await current(pausedControl.id);
    expect(persisted).toEqual(pausedControl);
    expect(Date.parse(persisted.next_due_at)).toBeLessThan(Date.now());
    expect(await history(pausedControl.id)).toEqual([]);
    await select(pausedControl.name);
    await expect(
      page.getByRole("button", { name: "Resume schedule", exact: true }),
    ).toBeVisible();
  } else {
    const refusedName = "Wrong typed outcome";
    await fillSchedule(refusedName, 60_000, 0, "Report");
    const attempt = waitForWrite(page, schedules);
    await page.getByRole("button", { name: "Create schedule" }).click();
    const error = await checked<{ detail: string }>(await attempt, 400);
    expect(error.detail).toContain("must end in a typed report result");
    await expect(page.getByRole("alert")).toHaveText(error.detail);
    await expect(
      page.getByRole("button", { name: refusedName, exact: true }),
    ).toHaveCount(0);
    rejectedPurpose = error.detail;
    const blocked = await createSchedule(
      "Storage limited QC",
      -2_000,
      Number.MAX_SAFE_INTEGER,
    );
    await select(blocked.name);
    await expect(
      page.getByText("Blocked by free space", { exact: false }),
    ).toBeVisible();
    expect((await current(blocked.id)).last_status).toBe("blocked_storage");
    expect((await current(blocked.id)).next_due_at).toBe(blocked.next_due_at);
    expect(await history(blocked.id)).toEqual([]);
    pausedControl = await pause(blocked);
  }
  const schedule =
    preceding?.schedule ??
    (await createSchedule(`Scheduled QC ${randomUUID().slice(0, 8)}`, 6_000));
  expect((await current(schedule.id)).graph_sha256).toBe(graph.graph_sha256);
  await select(schedule.name);
  const occurrence = await waitForOccurrence(schedule, preceding?.first.id);
  if (preceding) {
    expect(graph.graph_sha256).toBe(preceding.graphSha256);
    expect(occurrence.missed_intervals).toBeGreaterThanOrEqual(1);
    expect(Date.parse(occurrence.scheduled_at)).toBe(
      Date.parse(schedule.next_due_at) +
        occurrence.missed_intervals * schedule.interval_seconds * 1_000,
    );
    expect(occurrence.workflow_run_id).not.toBe(
      preceding.first.workflow_run_id,
    );
  } else {
    expect(occurrence.missed_intervals).toBe(0);
    expect(Date.parse(occurrence.scheduled_at)).toBe(
      Date.parse(schedule.next_due_at),
    );
  }
  const run = await checked<WorkflowRunDetail>(
    await page.request.get(
      `${api}/workflow-runs/${occurrence.workflow_run_id}`,
    ),
    200,
  );
  expect(run.run).toEqual(
    expect.objectContaining({
      id: occurrence.workflow_run_id,
      job_id: occurrence.job_id,
      project_id: fixture.projectId,
      workflow_graph_record_id: graph.id,
      graph_sha256: graph.graph_sha256,
      status: "succeeded",
    }),
  );
  const artifact = run.artifacts.find(
    (record) => record.data_type === "review_queue_reference",
  )!;
  expect(artifact.producer_port_id).toBe("queue");
  expect(artifact.payload_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(artifact.payload_json).toEqual(
    expect.objectContaining({
      project_id: fixture.projectId,
      dataset_version_id: fixture.datasetId,
      dataset_manifest_sha256: fixture.manifestSha256,
      item_count: fixture.images.length,
      review_status: "requires_researcher_review",
      workflow_run_id: occurrence.workflow_run_id,
    }),
  );

  const list = await history(schedule.id);
  expect(list.map(({ id }) => id).sort()).toEqual(
    (preceding ? [occurrence.id, preceding.first.id] : [occurrence.id]).sort(),
  );
  expect(
    new Set(list.map(({ scheduled_at }) => Date.parse(scheduled_at))).size,
  ).toBe(list.length);
  if (phase === "before-restart") {
    const advanced = await current(schedule.id);
    expect(advanced.enabled).toBe(true);
    expect(Date.parse(advanced.next_due_at)).toBe(
      Date.parse(occurrence.scheduled_at) + intervalSeconds * 1_000,
    );
    await writeFile(
      witnessPath!,
      JSON.stringify(
        {
          fixture,
          graphSha256: graph.graph_sha256,
          schedule: advanced,
          first: occurrence,
          paused: pausedControl,
        } satisfies RestartWitness,
        null,
        2,
      ),
    );
  } else {
    await pause(schedule);
    await openSchedules();
    await select(schedule.name);
    await expect(
      page.getByRole("button", { name: "Resume schedule", exact: true }),
    ).toBeVisible();
  }
  const row = page.getByRole("article").filter({ hasText: occurrence.id });
  await expect(row.getByText("Succeeded", { exact: true })).toBeVisible();
  if (preceding) {
    await expect(row.getByText(/coalesced intervals?/)).toBeVisible();
  }
  const jobResponse = page.waitForResponse(
    (response) =>
      response.url().split("?")[0] === `${api}/jobs/${occurrence.job_id}`,
  );
  await row.getByRole("button", { name: "Open job", exact: true }).click();
  const job = await checked<{
    id: string;
    project_id: string;
    request_json: Record<string, unknown>;
    status: string;
  }>(await jobResponse, 200);
  expect(job).toEqual(
    expect.objectContaining({
      id: occurrence.job_id,
      project_id: fixture.projectId,
      request_json: expect.objectContaining({
        workflow_run_id: occurrence.workflow_run_id,
      }),
      status: "succeeded",
    }),
  );
  const jobDetails = row.getByRole("region", { name: "Scheduled job details" });
  await expect(
    jobDetails.getByRole("heading", { name: "succeeded", exact: true }),
  ).toBeVisible();
  await expect(
    row.getByText(occurrence.job_id!, { exact: true }),
  ).toBeVisible();
  await row.getByRole("button", { name: "Open workflow run" }).click();
  await expect(
    page.getByText("review_queue_reference", { exact: true }),
  ).toBeVisible();
  const queueId = String(artifact.payload_json.queue_id);
  const queueResponse = page.waitForResponse(
    (response) =>
      response.url().split("?")[0] === `${api}/review-queues/${queueId}/items`,
  );
  await page
    .getByRole("button", { name: "Open generated review queue" })
    .click();
  const ranks = page.locator(".dashboard-card").filter({
    has: page.getByRole("heading", { name: "Ranked images", exact: true }),
  });
  await expect(ranks.getByText("Rank #1", { exact: true })).toBeVisible();
  await expect(ranks.getByText("Rank #2", { exact: true })).toBeVisible();
  const ranked = (
    await checked<{ items: ReviewQueueItem[] }>(await queueResponse, 200)
  ).items;
  expect(ranked.map((item) => item.image_id).sort()).toEqual(
    fixture.images.map(({ id }) => id).sort(),
  );
  const originalHashes = [];
  for (const image of fixture.images) {
    const original = await page.request.get(
      `${api}/images/${image.id}/content`,
    );
    expect(original.status()).toBe(200);
    const digest = sha256(await original.body());
    expect(digest).toBe(image.sha256);
    originalHashes.push({ id: image.id, sha256: digest });
  }
  let receiptProof: Record<string, unknown> | undefined;
  if (phase !== "before-restart") {
    await openSchedules();
    await select(schedule.name);
    const terminal = page
      .getByRole("article")
      .filter({ hasText: occurrence.id });
    const receiptURL = `${root}/workflow-schedule-occurrences/${occurrence.id}/receipt`;
    const receiptResponse = page.waitForResponse(
      (response) => response.url() === receiptURL,
    );
    const transfer = page.waitForEvent("download");
    await terminal
      .getByRole("button", { name: "Download receipt JSON" })
      .click();
    const standalone = await checked<WorkflowScheduleReceipt>(
      await receiptResponse,
      200,
    );
    const download = await transfer;
    expect(standalone.receipt_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(download.suggestedFilename()).toBe(
      `workflow-schedule-receipt-${standalone.receipt_sha256}.json`,
    );
    const receiptBytes = await readFile(await download.path());
    expect(JSON.parse(receiptBytes.toString("utf8"))).toEqual(standalone);
    expect(standalone.receipt).toEqual(
      expect.objectContaining({
        project_id: fixture.projectId,
        schedule_id: schedule.id,
        occurrence_id: occurrence.id,
        workflow_graph_record_id: graph.id,
        graph_sha256: occurrence.graph_sha256,
        inputs_sha256: occurrence.inputs_sha256,
        workflow_run_id: occurrence.workflow_run_id,
        job_id: occurrence.job_id,
        status: "succeeded",
        artifacts: expect.arrayContaining([
          expect.objectContaining({
            artifact_id: artifact.id,
            data_type: "review_queue_reference",
            payload_sha256: artifact.payload_sha256,
          }),
        ]),
      }),
    );
    const savedNode = waitForWrite(page, `${root}/workflow-graphs`);
    await terminal
      .getByRole("button", { name: "Save receipt workflow" })
      .click();
    const receiptGraph = await checked<WorkflowGraphRecord>(
      await savedNode,
      201,
    );
    const revision = page.getByRole("listitem").filter({
      hasText: receiptGraph.name,
      has: page.getByRole("button", {
        name: "Run saved revision",
        exact: true,
      }),
    });
    await expect(revision).toBeVisible();
    const replays = [];
    for (const replayNumber of [1, 2]) {
      if (replayNumber > 1) {
        await openProject(page, web, fixture.projectName);
        await page
          .getByRole("tab", { name: "Workflow builder", exact: true })
          .click();
        await revision
          .getByRole("button", { name: "Load", exact: true })
          .click();
      }
      const queued = waitForWrite(page, `${root}/workflow-runs`);
      await revision
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
          { timeout: 45_000 },
        )
        .not.toMatch(/queued|running/);
      expect(detail.run.status, detail.run.error_message ?? undefined).toBe(
        "succeeded",
      );
      expect(detail.run.workflow_graph_record_id).toBe(receiptGraph.id);
      const result = detail.artifacts.find(
        ({ data_type }) => data_type === "workflow_schedule_receipt",
      )!;
      expect(result.producer_port_id).toBe("receipt");
      expect(result.payload_json).toEqual(standalone);
      replays.push({ id, payloadSha256: result.payload_sha256 });
      await expect(
        page.getByText("workflow_schedule_receipt", { exact: true }).last(),
      ).toBeVisible();
    }
    expect(replays[0].id).not.toBe(replays[1].id);
    expect(replays[0].payloadSha256).toBe(replays[1].payloadSha256);
    expect((await history(schedule.id)).map(({ id }) => id)).toEqual(
      list.map(({ id }) => id),
    );
    expect((await current(schedule.id)).enabled).toBe(false);
    expect(await history(pausedControl.id)).toEqual([]);
    receiptProof = {
      receiptSha256: standalone.receipt_sha256,
      downloadedFileSha256: sha256(receiptBytes),
      graphId: receiptGraph.id,
      graphSha256: receiptGraph.graph_sha256,
      replays,
    };
  }
  const proofPath = info.outputPath("schedule-proof.json");
  await writeFile(
    proofPath,
    JSON.stringify(
      {
        surface,
        phase,
        version: health.version,
        schema: runtime.current_schema_revision,
        pausedControl,
        rejectedPurpose,
        receiptProof,
        projectId: fixture.projectId,
        graphId: graph.id,
        graphSha256: graph.graph_sha256,
        datasetId: fixture.datasetId,
        manifestSha256: fixture.manifestSha256,
        originalHashes,
        schedule: await current(schedule.id),
        occurrence,
        job: { id: job.id, project_id: job.project_id, status: job.status },
        queueId,
        artifactSha256: artifact.payload_sha256,
        ranked: ranked.map(
          ({ image_id, rank_position, score, input_checksum }) => ({
            image_id,
            rank_position,
            score,
            input_checksum,
          }),
        ),
      },
      null,
      2,
    ),
  );
  await info.attach("schedule-proof", {
    contentType: "application/json",
    path: proofPath,
  });
});
