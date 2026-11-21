import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";

import type {
  AudioAnchor,
  AudioProposal,
  AudioRecording,
  AudioReport,
  AudioReview,
} from "../../src/features/bioacoustics/bioacousticsApi";
import type {
  WorkflowGraphRecord,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

const hash = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
const name = "Generated stereo recording.wav";
const filename = "generated-wav";
const sampleRate = 8000;
const sampleCount = 16000;

function generatedWav() {
  const bytes = Buffer.alloc(44 + sampleCount * 4);
  bytes.write("RIFF", 0, "ascii");
  bytes.writeUInt32LE(bytes.length - 8, 4);
  bytes.write("WAVEfmt ", 8, "ascii");
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(2, 22);
  bytes.writeUInt32LE(sampleRate, 24);
  bytes.writeUInt32LE(sampleRate * 4, 28);
  bytes.writeUInt16LE(4, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write("data", 36, "ascii");
  bytes.writeUInt32LE(bytes.length - 44, 40);
  for (let sample = 0; sample < sampleCount; sample++) {
    const value = Math.round(
      8192 * Math.sin((sample * Math.PI * 2 * 400) / sampleRate),
    );
    bytes.writeInt16LE(value, 44 + sample * 4);
    bytes.writeInt16LE(value * 2, 46 + sample * 4);
  }
  return bytes;
}

async function checked<T>(
  response: APIResponse | Response,
  code: number,
): Promise<T> {
  expect(response.status(), await response.text()).toBe(code);
  return response.json() as Promise<T>;
}

function posted(page: Page, path: string) {
  return page.waitForResponse(
    (response) =>
      response.url() === path && response.request().method() === "POST",
  );
}

test("reviews original audio and replays an explicitly aligned report", async ({
  desktop,
}, info) => {
  test.setTimeout(170000);
  const { page, web, api, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  await page.addInitScript((version) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${version}`, "true");
  }, runtime.application_version);
  const title = `Generated acoustic witness ${randomUUID().slice(0, 8)}`;
  const project = await checked<{ id: string }>(
    await page.request.post(`${api}/projects`, {
      data: { name: title, template: "blank" },
    }),
    201,
  );
  const base = `${api}/projects/${project.id}`;

  async function openProject() {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${title}`, exact: true })
      .click();
  }
  async function openAudio() {
    await openProject();
    await page
      .getByRole("tab", { name: "Project assets", exact: true })
      .click();
    await page.getByRole("tab", { name: "Audio", exact: true }).click();
    await expect(
      page.getByRole("region", { name: "Bioacoustics workspace", exact: true }),
    ).toBeVisible();
  }

  await openAudio();
  const recordingPath = `${base}/bioacoustics/assets`;
  const bytes = generatedWav();
  const original = hash(bytes);
  await page
    .getByLabel("Original WAV file", { exact: true })
    .setInputFiles({ name, mimeType: "audio/wav", buffer: bytes });
  const uploaded = posted(page, recordingPath);
  await page.getByRole("button", { name: "Import WAV", exact: true }).click();
  const audio = await checked<AudioRecording>(await uploaded, 201);
  expect(audio).toMatchObject({
    project_id: project.id,
    sha256: original,
    sample_rate_hz: sampleRate,
    sample_count: sampleCount,
    channel_count: 2,
    bits_per_sample: 16,
  });
  const scoped = `${recordingPath}/${audio.id}`;
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page
    .getByRole("combobox", { name: "Waveform channel", exact: true })
    .selectOption("1");
  await expect(
    page.getByRole("img", {
      name: "Source waveform for channel 2",
      exact: true,
    }),
  ).toBeVisible();
  const player = page.locator("audio[aria-label='Original audio playback']");
  await expect
    .poll(() =>
      player.evaluate((element: HTMLAudioElement) => element.duration),
    )
    .toBe(2);
  await page
    .getByRole("spinbutton", { name: "Start sample", exact: true })
    .fill("2000");
  await page
    .getByRole("spinbutton", { name: "End sample (exclusive)", exact: true })
    .fill("6000");
  await page
    .getByRole("button", { name: "Seek to interval start", exact: true })
    .click();
  await expect
    .poll(() =>
      player.evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBe(0.25);
  await page
    .getByRole("button", { name: "Play original audio", exact: true })
    .click();
  await expect
    .poll(() =>
      player.evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThan(0.25);
  await player.evaluate((element: HTMLAudioElement) => element.pause());

  await page
    .getByRole("textbox", { name: "Proposed label", exact: true })
    .fill("Generated pulse");
  const proposed = posted(page, `${scoped}/proposals`);
  await page.getByRole("button", { name: "Add proposal", exact: true }).click();
  const proposal = await checked<AudioProposal>(await proposed, 201);
  expect(proposal).toMatchObject({
    start_sample: 2000,
    end_sample: 6000,
    channel: 1,
    status: "proposed",
    source_sha256: original,
  });
  await page
    .getByRole("combobox", { name: "Review decision", exact: true })
    .selectOption("accepted");
  const reason = "Listened to the generated channel fixture.";
  await page
    .getByRole("textbox", { name: "Review reason", exact: true })
    .fill(reason);
  const reviewed = posted(page, `${scoped}/proposals/${proposal.id}/reviews`);
  await page
    .getByRole("button", { name: "Record decision", exact: true })
    .click();
  const review = await checked<AudioReview>(await reviewed, 201);
  expect(review).toMatchObject({
    decision: "accepted",
    reason,
    revision: 1,
    proposal_id: proposal.id,
  });
  expect(review.reviewer).toMatch(/^local-user:/);
  await expect(
    page.getByRole("list", { name: "Attributed review history" }),
  ).toContainText(reason);

  await page
    .getByRole("spinbutton", { name: "Anchor sample", exact: true })
    .fill("4000");
  await page
    .getByRole("textbox", { name: "Anchor timestamp with offset", exact: true })
    .fill("2026-04-17T11:30:00-04:00");
  await page
    .getByRole("spinbutton", {
      name: "Uncertainty (microseconds)",
      exact: true,
    })
    .fill("200000");
  await page
    .getByRole("textbox", { name: "Clock evidence", exact: true })
    .fill("Known explicit offset in synthetic witness.");
  const createdAnchor = posted(page, `${scoped}/anchors`);
  await page
    .getByRole("button", { name: "Save clock anchor", exact: true })
    .click();
  const anchor = await checked<AudioAnchor>(await createdAnchor, 201);
  const selection = page.getByRole("combobox", {
    name: "Anchor for the report",
    exact: true,
  });
  await expect(selection).toHaveValue(anchor.id);
  const frozen = posted(page, `${scoped}/reports`);
  await page
    .getByRole("button", { name: "Freeze bioacoustic report", exact: true })
    .click();
  const report = await checked<AudioReport>(await frozen, 201);
  expect(report.snapshot.entries).toHaveLength(1);
  expect(report.snapshot.entries[0]).toMatchObject({
    proposal: { id: proposal.id, latest_review: { id: review.id } },
    alignment: {
      start_utc: "2026-04-17T15:29:59.750000Z",
      end_utc: "2026-04-17T15:30:00.250000Z",
      uncertainty_us: 200000,
      status: "utc",
    },
  });

  await openAudio();
  await expect(
    page.getByRole("combobox", {
      name: "Saved bioacoustic report",
      exact: true,
    }),
  ).toHaveValue(report.id);
  await expect(
    page.getByRole("list", { name: "Attributed review history" }),
  ).toContainText(reason);
  const downloadEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download report JSON", exact: true })
    .click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe(
    `bioacoustics-${report.report_sha256}.json`,
  );
  const target = info.outputPath("reviewed-bioacoustic-report.json");
  await download.saveAs(target);
  const exported = await readFile(target);
  expect(JSON.parse(exported.toString())).toEqual(report);

  const saved = posted(page, `${base}/workflow-graphs`);
  await page
    .getByRole("button", { name: "Save bioacoustic workflow", exact: true })
    .click();
  const graph = await checked<WorkflowGraphRecord>(await saved, 201);
  const replays = [];
  for (const _ of [1, 2]) {
    await openProject();
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
    const requested = posted(page, `${base}/workflow-runs`);
    await row
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const run = await checked<{ id: string }>(await requested, 202);
    let detail!: WorkflowRunDetail;
    await expect
      .poll(
        async () => {
          detail = await checked<WorkflowRunDetail>(
            await page.request.get(`${api}/workflow-runs/${run.id}`),
            200,
          );
          return detail.run.status;
        },
        { timeout: 45000 },
      )
      .not.toMatch(/queued|running/);
    expect(detail.run.status, detail.run.error_message ?? "").toBe("succeeded");
    const artifact = detail.artifacts.find(
      (entry) => entry.data_type === "bioacoustic_report",
    );
    expect(artifact?.payload_json).toEqual(report);
    expect(artifact?.payload_sha256).toBe(hash(exported));
    replays.push({ run_id: run.id, payload_sha256: artifact?.payload_sha256 });
  }
  expect(replays[0].run_id).not.toBe(replays[1].run_id);
  const savedWav = await page.request.get(`${scoped}/content`);
  expect(savedWav.status()).toBe(200);
  expect(hash(await savedWav.body())).toBe(original);
  await writeFile(
    info.outputPath("bioacoustics-evidence.json"),
    JSON.stringify(
      {
        surface,
        version: runtime.application_version,
        schema: runtime.schema_revision,
        generated_fixture: true,
        fixture: filename,
        recording_id: audio.id,
        source_sha256: original,
        review_id: review.id,
        anchor_id: anchor.id,
        report_sha256: report.report_sha256,
        export_sha256: hash(exported),
        replays,
      },
      null,
      2,
    ),
  );
});
