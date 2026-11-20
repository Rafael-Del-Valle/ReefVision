import { expect, type APIResponse, type Response } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { lstat, readFile, realpath, writeFile } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";

import type {
  AcquisitionReceipt,
  AcquisitionSource,
} from "../../src/features/acquisition-sources/acquisitionSourceApi";
import type {
  FieldBatch,
  FieldObservation,
} from "../../src/features/field-capture/fieldCaptureApi";
import type {
  WorkflowSchedule,
  ScheduleOccurrence,
} from "../../src/features/workflow-schedules/workflowScheduleApi";
import type {
  WorkflowGraphRecord,
  WorkflowRun,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import { test } from "./spatialDesktop";

const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");

async function checked<T>(response: APIResponse | Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

test("collects recorded and simulated sources and replays acquisition evidence", async ({
  desktop,
}, info) => {
  test.setTimeout(150_000);
  const { page, web, api, surface } = desktop;
  const expectedProfile = process.env.REEFVISION_ACQUISITION_TEST_PROFILE;
  const expectedVersion = process.env.REEFVISION_ACQUISITION_TEST_VERSION;
  const expectedSchema = process.env.REEFVISION_ACQUISITION_TEST_SCHEMA;
  if (!expectedProfile || !expectedVersion || !expectedSchema) {
    throw new Error(
      "The acquisition test requires independently declared profile, version and schema.",
    );
  }
  expect(isAbsolute(expectedProfile)).toBe(true);
  expect(new URL(api).hostname).toBe("127.0.0.1");
  const profile = await realpath(expectedProfile);
  expect(
    (
      await lstat(join(profile, ".reefvision-clean-install-acceptance"))
    ).isFile(),
  ).toBe(true);
  const runtime = await checked<{
    application_version: string;
    current_schema_revision: string;
    expected_schema_revision: string;
    data_dir: string;
    database_path: string;
    safe_mode: boolean;
  }>(await page.request.get(api + "/system/version"), 200);
  expect(runtime).toMatchObject({
    application_version: expectedVersion,
    current_schema_revision: expectedSchema,
    expected_schema_revision: expectedSchema,
    safe_mode: false,
  });
  expect(await realpath(runtime.data_dir)).toBe(profile);
  expect(await realpath(runtime.database_path)).toBe(
    await realpath(join(profile, "reefvision.db")),
  );
  await page.addInitScript((version) => {
    localStorage.setItem("reefvision.onboarding.dismissed." + version, "true");
  }, expectedVersion);

  const title = "Generated acquisition " + randomUUID().slice(0, 8);
  const project = await checked<{ id: string; storage_root: string }>(
    await page.request.post(api + "/projects", {
      data: { name: title, template: "blank" },
    }),
    201,
  );
  const projectApi = api + "/projects/" + project.id;
  const root = projectApi + "/acquisition-sources";
  const batches = projectApi + "/field-capture/batches";
  const batch = await checked<FieldBatch>(
    await page.request.post(batches, {
      data: { label: "Generated field recording" },
    }),
    201,
  );
  await page.goto(web);
  const originals: Array<{ observation: FieldObservation; bytes: Buffer }> = [];
  for (const [index, fill] of ["#1576a8", "#bd495f"].entries()) {
    const bytes = Buffer.from(
      await page.evaluate((color) => {
        const canvas = document.createElement("canvas");
        canvas.width = 24;
        canvas.height = 16;
        const context = canvas.getContext("2d")!;
        context.fillStyle = color;
        context.fillRect(0, 0, 24, 16);
        return canvas.toDataURL("image/png").split(",")[1];
      }, fill),
      "base64",
    );
    const clock =
      index === 0
        ? {
            state: "known_offset",
            wall_time: "2025-08-02T18:05:06",
            utc_offset_minutes: -240,
            evidence: "Declared recording clock and offset",
          }
        : {
            state: "unknown",
            evidence: "The recording has no second-frame clock offset",
          };
    const observation = await checked<FieldObservation>(
      await page.request.post(batches + "/" + batch.id + "/observations", {
        multipart: {
          file: {
            name: "generated-" + index + ".png",
            mimeType: "image/png",
            buffer: bytes,
          },
          metadata: JSON.stringify({ observer: "Generated fixture", clock }),
        },
      }),
      201,
    );
    expect(observation.sha256).toBe(sha256(bytes));
    originals.push({ observation, bytes });
  }
  const sealed = await checked<FieldBatch>(
    await page.request.post(batches + "/" + batch.id + "/seal"),
    200,
  );
  expect(sealed.manifest_sha256).toMatch(/^[a-f0-9]{64}$/);

  async function openProject(tab: string) {
    await page.goto(web);
    await page
      .getByRole("button", { name: "Open " + title, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page.getByRole("tab", { name: tab, exact: true }).click();
  }
  function waitForWrite(url: string, method = "POST") {
    return page.waitForResponse(
      (response) =>
        response.url() === url && response.request().method() === method,
    );
  }
  async function addSource(name: string, kind: string) {
    await page.getByLabel("Source type").selectOption({ label: kind });
    await page.getByLabel("Source name").fill(name);
  }
  async function submitSource() {
    const created = waitForWrite(root);
    await page.getByRole("button", { name: "Add source", exact: true }).click();
    return checked<AcquisitionSource>(await created, 201);
  }

  await openProject("Acquisition sources");
  await page
    .getByRole("heading", { name: "Acquisition sources", exact: true })
    .waitFor();
  await addSource("Recorded transect", "Recorded field batch");
  await page.getByLabel("Sealed field batch").selectOption(sealed.id);
  const recorded = await submitSource();
  const recordedApi = root + "/" + recorded.id;
  const recordedRegion = page.getByRole("region", {
    name: "Recorded transect acquisition source",
  });
  async function captureRecorded(status: number) {
    const response = waitForWrite(recordedApi + "/captures");
    await recordedRegion
      .getByRole("button", { name: "Capture once", exact: true })
      .click();
    return checked<AcquisitionReceipt>(await response, status);
  }
  const initial = await captureRecorded(200);
  expect(initial.receipt).toMatchObject({
    source_sha256: recorded.source_sha256,
    ordinal: 0,
    media: {
      sha256: originals[0].observation.sha256,
      field_batch_id: sealed.id,
      field_batch_sha256: sealed.manifest_sha256,
      field_observation_id: originals[0].observation.id,
    },
    time: {
      captured_at_utc: "2025-08-02T22:05:06Z",
      uncertainty_seconds: null,
    },
  });
  await expect(
    recordedRegion.getByText("2025-08-02T22:05:06Z", { exact: true }),
  ).toBeVisible();

  const original = originals[1];
  const secondPath = await realpath(
    join(
      profile,
      project.storage_root,
      "field_capture",
      "originals",
      "image",
      original.observation.sha256,
    ),
  );
  expect(relative(profile, secondPath).split(/[\\/]/)[0]).toBe("projects");
  expect(sha256(await readFile(secondPath))).toBe(original.observation.sha256);
  let failedSource: AcquisitionSource;
  try {
    // A temporary failure in generated bytes exercises the real source adapter.
    await writeFile(secondPath, "generated recording disconnected");
    await captureRecorded(409);
    failedSource = await checked<AcquisitionSource>(
      await page.request.get(recordedApi),
      200,
    );
    expect(failedSource).toMatchObject({ state: "disconnected", cursor: 1 });
    await expect(
      recordedRegion
        .getByRole("status", { name: "" })
        .filter({ hasText: "disconnected" }),
    ).toBeVisible();
  } finally {
    await writeFile(secondPath, original.bytes);
  }
  await expect
    .poll(() => Date.now(), { timeout: 9000 })
    .toBeGreaterThanOrEqual(Date.parse(failedSource.next_retry_at!));
  const reconnected = waitForWrite(recordedApi + "/state", "PATCH");
  await recordedRegion
    .getByRole("button", { name: "Reconnect source", exact: true })
    .click();
  expect(
    await checked<AcquisitionSource>(await reconnected, 200),
  ).toMatchObject({ state: "ready", cursor: 1 });
  const recovered = await captureRecorded(200);
  expect(recovered.receipt).toMatchObject({
    ordinal: 1,
    media: {
      sha256: original.observation.sha256,
      field_observation_id: original.observation.id,
    },
    time: {
      captured_at_utc: null,
      uncertainty_seconds: null,
      clock: { state: "unknown" },
    },
  });
  await expect(
    recordedRegion.getByRole("status").filter({ hasText: "exhausted" }),
  ).toBeVisible();
  const replayGraphResponse = waitForWrite(projectApi + "/workflow-graphs");
  await recordedRegion
    .getByRole("article", { name: "Observation 2" })
    .getByRole("button", { name: "Save receipt workflow", exact: true })
    .click();
  const replayGraph = await checked<WorkflowGraphRecord>(
    await replayGraphResponse,
    201,
  );

  await addSource("Synthetic sensor clock", "Simulated source");
  await page.getByLabel("Simulation seed").fill("41");
  await page.getByLabel("First timestamp (UTC)").fill("2025-08-02T22:05");
  const simulated = await submitSource();
  const simulatedRegion = page.getByRole("region", {
    name: "Synthetic sensor clock acquisition source",
  });
  const captureGraphResponse = waitForWrite(projectApi + "/workflow-graphs");
  await simulatedRegion
    .getByRole("button", { name: "Save capture workflow", exact: true })
    .click();
  const captureGraph = await checked<WorkflowGraphRecord>(
    await captureGraphResponse,
    201,
  );

  await addSource("Unapproved local camera", "Local camera");
  await page.getByLabel("Local camera index").fill("15");
  const camera = await submitSource();
  const cameraRegion = page.getByRole("region", {
    name: "Unapproved local camera acquisition source",
  });
  await expect(
    cameraRegion.getByRole("button", { name: "Capture once" }),
  ).toBeDisabled();
  await cameraRegion.getByRole("button", { name: "Approve camera" }).click();
  await page
    .getByRole("alertdialog", { name: "Approve this local camera?" })
    .getByRole("button", { name: "Cancel" })
    .click();
  expect(
    await checked<AcquisitionSource>(
      await page.request.get(root + "/" + camera.id),
      200,
    ),
  ).toMatchObject({ cursor: 0, local_consent_until: null });

  await openProject("Schedules");
  const scheduleName = "Generated simulated acquisition";
  const scheduleApi = projectApi + "/workflow-schedules";
  await page.getByLabel("Schedule name").fill(scheduleName);
  await page.getByLabel("Purpose").selectOption({ label: "Acquisition" });
  await page
    .getByLabel("Saved workflow revision")
    .selectOption(captureGraph.id);
  await page
    .getByLabel("First due (UTC)")
    .fill(new Date(Date.now() + 7000).toISOString().slice(0, 19));
  await page.getByLabel("Repeat interval (seconds)").fill("300");
  const scheduled = waitForWrite(scheduleApi);
  await page
    .getByRole("button", { name: "Create schedule", exact: true })
    .click();
  const schedule = await checked<WorkflowSchedule>(await scheduled, 201);
  expect(schedule.workflow_graph_record_id).toBe(captureGraph.id);
  await page.getByRole("button", { name: scheduleName, exact: true }).click();
  const scheduleRegion = page.getByRole("region", {
    name: "Schedule details for " + scheduleName,
  });
  await expect(
    scheduleRegion.getByRole("article").getByText("Succeeded", { exact: true }),
  ).toBeVisible({ timeout: 40_000 });
  const { items: occurrences } = await checked<{ items: ScheduleOccurrence[] }>(
    await page.request.get(scheduleApi + "/" + schedule.id + "/occurrences"),
    200,
  );
  expect(occurrences).toHaveLength(1);
  const [occurrence] = occurrences;
  const outcome = await checked<WorkflowRunDetail>(
    await page.request.get(
      api + "/workflow-runs/" + occurrence.workflow_run_id,
    ),
    200,
  );
  const captureArtifact = outcome.artifacts.find(
    (asset) => asset.data_type === "acquisition_capture_receipt",
  );
  expect(captureArtifact?.payload_json).toMatchObject({
    receipt: {
      source_id: simulated.id,
      ordinal: 0,
      dispatch: { kind: "schedule", occurrence_id: occurrence.id },
      synthetic_reading: { unit: "synthetic arbitrary units" },
      time: { captured_at_utc: "2025-08-02T22:05:00Z", uncertainty_seconds: 0 },
    },
  });
  const pauseResponse = waitForWrite(scheduleApi + "/" + schedule.id, "PATCH");
  await scheduleRegion
    .getByRole("button", { name: "Pause schedule", exact: true })
    .click();
  expect(
    await checked<WorkflowSchedule>(await pauseResponse, 200),
  ).toMatchObject({ enabled: false });

  const replayDigests: string[] = [];
  for (let replay = 0; replay < 2; replay += 1) {
    await openProject("Workflow builder");
    const saved = page.getByRole("listitem").filter({
      hasText: replayGraph.name,
      has: page.getByRole("button", {
        name: "Run saved revision",
        exact: true,
      }),
    });
    await saved.getByRole("button", { name: "Load", exact: true }).click();
    const queued = waitForWrite(projectApi + "/workflow-runs");
    await saved
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const run = await checked<WorkflowRun>(await queued, 202);
    await expect
      .poll(
        async () =>
          (
            await checked<WorkflowRunDetail>(
              await page.request.get(api + "/workflow-runs/" + run.id),
              200,
            )
          ).run.status,
        { timeout: 30_000 },
      )
      .toBe("succeeded");
    const replayed = await checked<WorkflowRunDetail>(
      await page.request.get(api + "/workflow-runs/" + run.id),
      200,
    );
    const artifact = replayed.artifacts.find(
      (item) => item.data_type === "acquisition_capture_receipt",
    )!;
    expect(artifact.payload_json).toEqual(recovered);
    replayDigests.push(artifact.payload_sha256);
  }
  expect(replayDigests[0]).toBe(replayDigests[1]);
  await openProject("Acquisition sources");
  await page
    .getByRole("button", { name: "Recorded transect", exact: true })
    .click();
  await expect(
    recordedRegion
      .getByRole("article", { name: "Observation 2" })
      .getByText(recovered.content_sha256, { exact: true }),
  ).toBeVisible();
  expect(
    await checked<AcquisitionSource>(await page.request.get(recordedApi), 200),
  ).toMatchObject({ state: "exhausted", cursor: 2 });
  expect(sha256(await readFile(secondPath))).toBe(original.observation.sha256);
  await writeFile(
    info.outputPath("acquisition-source-evidence.json"),
    JSON.stringify(
      {
        surface,
        version: runtime.application_version,
        schema: runtime.current_schema_revision,
        project_id: project.id,
        recorded: [initial, recovered],
        disconnected_cursor: failedSource.cursor,
        simulated_source_id: simulated.id,
        occurrence_id: occurrence.id,
        capture_artifact: captureArtifact,
        replay_digests: replayDigests,
        camera_consent_cancelled_without_capture: true,
      },
      null,
      2,
    ),
  );
});
