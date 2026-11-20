import { expect } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { test } from "./spatialDesktop";

const sourceImage = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
  "base64",
);
const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");

test("captures local field originals and replays a transferred batch", async ({
  desktop,
}, info) => {
  test.setTimeout(120_000);
  const { page, web, api } = desktop;
  page.setDefaultTimeout(10_000);
  if (desktop.surface === "source-browser") {
    await page.setViewportSize({ width: 1350, height: 900 });
  }
  const { version } = JSON.parse(await readFile("package.json", "utf8")) as {
    version: string;
  };
  await page.addInitScript((value) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${value}`, "true");
  }, version);
  const marker = randomUUID().slice(0, 8);
  async function project(name: string) {
    const response = await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    });
    expect(response.status(), await response.text()).toBe(201);
    return (await response.json()) as { id: string; name: string };
  }
  const source = await project(`Offline field fixture ${marker}`);
  const receiver = await project(`Field receiver fixture ${marker}`);
  const sourceVideo = await readFile(
    new URL("./fixtures/synthetic-ordinary-clip.mp4", import.meta.url),
  );
  async function openProject(name: string) {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  }
  async function openField(name: string) {
    await openProject(name);
    await page
      .getByRole("tab", { name: "Data & annotation", exact: true })
      .click();
    await page.getByRole("tab", { name: "Field capture", exact: true }).click();
  }
  const title = `Fixture transect ${marker}`;
  async function createBatch(name: string) {
    await page.getByLabel("Batch name", { exact: true }).fill(name);
    await page
      .getByRole("button", { name: "Create field batch", exact: true })
      .click();
  }
  await openField(source.name);
  await createBatch(title);
  const capture = page.getByRole("form", { name: "Capture local media" });
  async function captureOriginal() {
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith("/observations"),
    );
    await capture
      .getByRole("button", { name: "Capture original", exact: true })
      .click();
    const response = await saved;
    expect(response.status(), await response.text()).toBe(201);
  }
  async function sealBatch() {
    await page
      .getByRole("button", { name: "Seal field batch", exact: true })
      .click();
    await expect(
      page.getByRole("link", { name: "Download field batch", exact: true }),
    ).toBeVisible();
  }
  await capture.getByLabel("Local media file", { exact: true }).setInputFiles({
    name: "field-fixture.png",
    mimeType: "image/png",
    buffer: sourceImage,
  });
  await capture
    .getByLabel("Observer", { exact: true })
    .fill("Synthetic fixture recorder");
  await capture
    .getByLabel("Observation key", { exact: true })
    .fill("Site 7 / image 1");
  await capture.getByLabel("Site", { exact: true }).fill("Synthetic station 7");
  await capture
    .getByLabel("Source clock", { exact: true })
    .selectOption("known_offset");
  await capture
    .getByLabel("Source wall time", { exact: true })
    .fill("2026-11-19T08:15:03");
  await capture
    .getByLabel("UTC offset (minutes)", { exact: true })
    .fill("-300");
  await capture
    .getByLabel("Clock evidence", { exact: true })
    .fill("Declared offset from synthetic fixture");
  await captureOriginal();
  await expect(
    page.getByText("2026-11-19T13:15:03Z", { exact: false }),
  ).toBeVisible();
  await capture.getByLabel("Local media file", { exact: true }).setInputFiles({
    name: "field-fixture.mp4",
    mimeType: "video/mp4",
    buffer: sourceVideo,
  });
  await capture
    .getByLabel("Observer", { exact: true })
    .fill("Synthetic video recorder");
  await capture
    .getByLabel("Observation key", { exact: true })
    .fill("Site 7 / video 1");
  await capture
    .getByLabel("Source clock", { exact: true })
    .selectOption("unknown");
  await capture
    .getByLabel("Clock evidence", { exact: true })
    .fill("Synthetic fixture has no source offset evidence");
  await captureOriginal();
  await expect(
    page.getByText("Capture UTC unknown", { exact: true }),
  ).toBeVisible();
  await sealBatch();

  await openField(source.name);
  await page
    .getByRole("button", { name: `Open batch ${title}`, exact: true })
    .click();
  await expect(
    page.getByText(sha256(sourceImage), { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(sha256(sourceVideo), { exact: true }),
  ).toBeVisible();
  const pendingArchive = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Download field batch", exact: true })
    .click();
  const archiveDownload = await pendingArchive;
  const archive = await readFile(await archiveDownload.path());
  expect(archive.subarray(0, 2).toString()).toBe("PK");

  await openField(receiver.name);
  await page
    .getByLabel("Local field batch archive", { exact: true })
    .setInputFiles({
      name: "synthetic.reefvision-field.zip",
      mimeType: "application/zip",
      buffer: archive,
    });
  await page
    .getByRole("button", { name: "Import field batch", exact: true })
    .click();
  const reconcileResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/field-capture\/batches\/[^/]+\/reconcile$/.test(response.url()),
  );
  await page
    .getByRole("button", { name: "Reconcile field batch", exact: true })
    .click();
  const response = await reconcileResponse;
  expect(response.status(), await response.text()).toBe(200);
  const report = (await response.json()) as {
    batch_id: string;
    report_sha256: string;
    rows: Array<{
      asset_id: string;
      kind: "image" | "video";
      sha256: string;
      outcome: string;
    }>;
  };
  expect(report.rows).toEqual([
    expect.objectContaining({
      sha256: sha256(sourceImage),
      kind: "image",
      outcome: "imported",
    }),
    expect.objectContaining({
      sha256: sha256(sourceVideo),
      kind: "video",
      outcome: "imported",
    }),
  ]);
  const original = await page.request.get(
    `${api}/images/${report.rows[0].asset_id}/content`,
  );
  expect(sha256(await original.body())).toBe(sha256(sourceImage));
  const video = await page.request.get(
    `${api}/videos/${report.rows[1].asset_id}/content`,
  );
  expect(sha256(await video.body())).toBe(sha256(sourceVideo));

  const savedResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${api}/projects/${receiver.id}/workflow-graphs`,
  );
  await page
    .getByRole("button", { name: "Save field workflow", exact: true })
    .click();
  const saved = await savedResponse;
  expect(saved.status(), await saved.text()).toBe(201);
  const graph = (await saved.json()) as {
    id: string;
    name: string;
    graph_sha256: string;
  };

  async function replay() {
    await openProject(receiver.name);
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
    const revision = page.getByRole("listitem").filter({ hasText: graph.name });
    await revision.getByRole("button", { name: "Load", exact: true }).click();
    await expect(page.locator("[data-node-id='reconcile']")).toBeVisible();
    const queuedResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url() === `${api}/projects/${receiver.id}/workflow-runs`,
    );
    await revision
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const queued = await queuedResponse;
    expect(queued.status(), await queued.text()).toBe(202);
    const { id } = (await queued.json()) as { id: string };
    await expect
      .poll(
        async () => {
          const savedRun = await page.request.get(`${api}/workflow-runs/${id}`);
          return (await savedRun.json()).run.status;
        },
        { timeout: 35_000 },
      )
      .toBe("succeeded");
    const pending = page.waitForEvent("download");
    await page
      .getByRole("button", {
        name: "Download field reconciliation JSON",
        exact: true,
      })
      .click();
    const download = await pending;
    expect(JSON.parse(await readFile(await download.path(), "utf8"))).toEqual(
      report,
    );
    return id;
  }
  const first = await replay();
  const second = await replay();
  expect(second).not.toBe(first);

  await openField(receiver.name);
  const conflictTitle = `Conflicting field fixture ${marker}`;
  await createBatch(conflictTitle);
  await capture.getByLabel("Local media file", { exact: true }).setInputFiles({
    name: "second-field-observation.png",
    mimeType: "image/png",
    buffer: sourceImage,
  });
  await capture
    .getByLabel("Observer", { exact: true })
    .fill("Synthetic second observer");
  await capture
    .getByLabel("Observation key", { exact: true })
    .fill("Site 7 / image 1");
  await capture
    .getByLabel("Clock evidence", { exact: true })
    .fill("Synthetic observation did not include the source clock");
  await capture
    .getByLabel("Notes", { exact: true })
    .fill("A conflicting field observation for review");
  await captureOriginal();
  await sealBatch();
  await page
    .getByRole("button", { name: "Reconcile field batch", exact: true })
    .click();
  await page
    .getByText("The same observation key has different evidence", {
      exact: false,
    })
    .click();
  const review = page.getByRole("form", { name: "Review field conflict" });
  await review
    .getByLabel("Reviewer", { exact: true })
    .fill("Synthetic independent reviewer");
  const reviewNotes = "Retain both source records to compare original claims.";
  await review.getByLabel("Review notes", { exact: true }).fill(reviewNotes);
  await review
    .getByRole("button", { name: "Save review decision", exact: true })
    .click();
  await expect(page.getByText(reviewNotes, { exact: false })).toBeVisible();
  await openField(receiver.name);
  await page
    .getByRole("button", { name: `Open batch ${conflictTitle}`, exact: true })
    .click();
  await page
    .getByText("The same observation key has different evidence", {
      exact: false,
    })
    .click();
  await expect(page.getByText(reviewNotes, { exact: false })).toBeVisible();
  await expect(
    page.getByText("Retain both records", { exact: true }),
  ).toBeVisible();
  const duplicateOriginal = await page.request.get(
    `${api}/images/${report.rows[0].asset_id}/content`,
  );
  expect(sha256(await duplicateOriginal.body())).toBe(sha256(sourceImage));
  await writeFile(
    info.outputPath("field-capture-evidence.json"),
    JSON.stringify(
      {
        surface: desktop.surface,
        generated_fixture: true,
        source_sha256: sha256(sourceImage),
        video_sha256: sha256(sourceVideo),
        archive_sha256: sha256(archive),
        report_sha256: report.report_sha256,
        graph_sha256: graph.graph_sha256,
        saved_workflow_id: graph.id,
        replay_ids: [first, second],
        persisted_conflict_decision: "retain_both",
      },
      null,
      2,
    ),
  );
});
