import { expect, type APIResponse, type Page } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import type {
  WorkflowGraphRecord,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import {
  recordPairedGrowthTimeLapse,
  type RecordingShot,
} from "./pairedGrowthRecordingFixture";
import { test } from "./spatialDesktop";

const baseline = "2026-11-01";
const followup = "2026-11-02";
const unitType = process.env.REEFVISION_PAIRED_GROWTH_ACCEPTANCE_UNIT ?? "tank";
if (!["tank", "site", "colony", "recording"].includes(unitType)) {
  throw new Error(`Unsupported paired growth acceptance unit: ${unitType}`);
}
const unitLabel = unitType[0].toUpperCase() + unitType.slice(1);
const estimand = `Equal-${unitType} mean follow-up minus baseline change in fragment width.`;
const graphName = `Paired growth · ${baseline} to ${followup} · ${unitType}`;
const dates = [baseline, followup];
const design = {
  baseline_date: baseline,
  followup_date: followup,
  experimental_unit_type: unitType,
  estimand,
  missingness_policy: "complete_unit",
};

// 80 × 60 synthetic JPEG with an EXIF DateTimeOriginal and explicit +00:00 offset.
const originalPhoto = Buffer.from(
  "/9j/4AAQSkZJRgABAQAAAQABAAD/4QBKRXhpZgAATU0AKgAAAAgAApADAAIAAAAUAAAAJpARAAIAAAAHAAAAOgAAAAAyMDI2OjExOjAxIDEyOjAwOjAwACswMDowMAAA/9sAQwAIBgYHBgUIBwcHCQkICgwUDQwLCwwZEhMPFB0aHx4dGhwcICQuJyAiLCMcHCg3KSwwMTQ0NB8nOT04MjwuMzQy/9sAQwEJCQkMCwwYDQ0YMiEcITIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy/8AAEQgAPABQAwEiAAIRAQMRAf/EABUAAQEAAAAAAAAAAAAAAAAAAAAH/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/EABUBAQEAAAAAAAAAAAAAAAAAAAAF/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AnwCuigAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/9k=",
  "base64",
);

const visitDateOffset = originalPhoto.indexOf("2026:11:01 12:00:00");
const roster = [
  { suffix: "A", followupWidths: [24] },
  { suffix: "B", followupWidths: [28, 36] },
  {
    suffix: "C",
    followupWidths: unitType === "site" ? [20, 28, 56] : [32, 40, 48],
  },
  { suffix: "D", followupWidths: [52, null] },
];

type PairedReport = {
  report_sha256: string;
  confidence_interval_95: [number, number] | null;
  source_exclusions: { reason: string }[];
  units: {
    experimental_unit_id: string;
    status: "included" | "excluded";
    difference: number | null;
    organisms: {
      parent_colony_id: string | null;
      difference: number | null;
      baseline_source_record_id: string | null;
      followup_source_record_id: string | null;
    }[];
  }[];
};

async function checkedJson<T>(
  response: APIResponse,
  status: number,
): Promise<T> {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

function sha256(bytes: Buffer) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function seedReviewedGrowth(
  page: Page,
  api: string,
  projectName: string,
) {
  expect(visitDateOffset).toBeGreaterThanOrEqual(0);
  const { id: projectId } = await checkedJson<{ id: string }>(
    await page.request.post(`${api}/projects`, { data: { name: projectName } }),
    201,
  );
  const root = `${api}/projects/${projectId}`;
  const ecology = `${root}/ecology`;
  const { id: labelId } = await checkedJson<{ id: string }>(
    await page.request.post(`${root}/classes`, {
      data: {
        class_index: 0,
        name: "Synthetic fragment",
        display_color: "#28A95C",
      },
    }),
    201,
  );

  async function register(unit: string, key: string, parent?: string) {
    const response = await page.request.post(`${ecology}/organisms`, {
      data: {
        organism_key: key,
        experimental_unit_type: unitType,
        experimental_unit_id: unit,
        kind: parent ? "fragment" : "colony",
        parent_colony_key: parent,
        reason: "Synthetic roster recorded before selecting the two visits.",
      },
    });
    expect(response.status(), await response.text()).toBe(201);
  }

  const sources: {
    calibration_evidence_id: string;
    exclusion_reason?: string;
  }[] = [];
  const sourceFiles: {
    image_id: string;
    image_sha256: string;
    excluded?: boolean;
    recording_id?: string;
    capture_order?: number;
    capture_utc?: string;
  }[] = [];
  const excludedFrameReason =
    "Glare obscured the time-lapse follow-up boundary.";
  const recordings: {
    id: string;
    unit_id: string;
    sha256: string;
    frame_count: number;
  }[] = [];
  async function seedVisit(
    organism: string,
    date: string,
    width: number,
    capture?: {
      jpeg: string;
      order: number;
      recordingId: string;
      excluded?: boolean;
    },
  ) {
    const clock = `12:00:${String(capture?.order ?? 0).padStart(2, "0")}`;
    const captureTime = `${date}T${clock}Z`;
    const photo = Buffer.from(originalPhoto);
    photo.write(
      `${date.replaceAll("-", ":")} ${clock}`,
      visitDateOffset,
      "ascii",
    );
    // Inject the explicitly logged UTC capture timestamp into the actual acquisition still.
    const exifStart = photo.indexOf("Exif") - 4;
    const exifEnd = exifStart + 2 + photo.readUInt16BE(exifStart + 2);
    const captured = capture ? Buffer.from(capture.jpeg, "base64") : undefined;
    const bytes = captured
      ? Buffer.concat([
          captured.subarray(0, 2),
          photo.subarray(exifStart, exifEnd),
          captured.subarray(2),
        ])
      : Buffer.concat([photo, Buffer.from(`${organism}-${date}`)]);
    const name = `${organism}-${date}.jpg`;
    const upload = await checkedJson<{ successful: { image_id: string }[] }>(
      await page.request.post(`${root}/imports/images`, {
        multipart: { files: { name, mimeType: "image/jpeg", buffer: bytes } },
      }),
      200,
    );
    expect(upload.successful).toHaveLength(1);
    const [{ image_id: imageId }] = upload.successful;
    sourceFiles.push({
      image_id: imageId,
      image_sha256: sha256(bytes),
      ...(capture
        ? {
            excluded: capture.excluded ?? false,
            recording_id: capture.recordingId,
            capture_order: capture.order,
            capture_utc: captureTime,
          }
        : {}),
    });

    const organismUrl = `${ecology}/organisms/${organism}`;
    const evidence = await checkedJson<{ id: string }>(
      await page.request.post(`${organismUrl}/image-evidence`, {
        data: {
          image_id: imageId,
          expected_identity_revision: 1,
          reason: capture
            ? `Synthetic time-lapse ${capture.recordingId}, capture ${capture.order} at ${captureTime}.`
            : "Known synthetic image and acquisition date.",
        },
      }),
      201,
    );
    const annotationId = randomUUID();
    const annotated = await page.request.put(
      `${api}/images/${imageId}/annotations`,
      {
        data: {
          base_revision: 0,
          annotation_status: "reviewed",
          annotations: [
            {
              id: annotationId,
              label_class_id: labelId,
              x_min: 5,
              x_max: 5 + width,
              y_min: 8,
              y_max: 20,
            },
          ],
        },
      },
    );
    expect(annotated.status(), await annotated.text()).toBe(200);
    const annotation = await checkedJson<{
      id: string;
      annotation_sha256: string;
    }>(
      await page.request.post(`${organismUrl}/annotation-evidence`, {
        data: {
          image_evidence_id: evidence.id,
          annotation_kind: "box",
          annotation_id: annotationId,
          expected_annotation_revision: 1,
          reason: "Reviewed the exact image-plane fixture width.",
        },
      }),
      201,
    );
    const scale = await page.request.put(
      `${api}/images/${imageId}/measurement-calibration`,
      {
        data: {
          distance_per_pixel: 0.25,
          unit: "mm",
          source: "manual",
          reference_length: 5,
          reference_pixel_length: 20,
          reference_plane_only: true,
        },
      },
    );
    expect(scale.status(), await scale.text()).toBe(200);
    const calibration = await checkedJson<{ id: string }>(
      await page.request.post(`${organismUrl}/calibration-evidence`, {
        data: {
          annotation_evidence_id: annotation.id,
          expected_annotation_sha256: annotation.annotation_sha256,
          confirm_source_calibration: true,
          reason: "Known synthetic reference-plane scale (0.25 mm per pixel).",
        },
      }),
      201,
    );
    sources.push({
      calibration_evidence_id: calibration.id,
      ...(capture?.excluded ? { exclusion_reason: excludedFrameReason } : {}),
    });
  }

  const samplingPlan = [];
  for (const [unitIndex, { suffix, followupWidths }] of roster.entries()) {
    const name = `${unitLabel}-${suffix}`;
    const primaryColony = `colony-${name.toLowerCase()}`;
    const fragments = followupWidths.map((width, index) => ({
      organism: `${primaryColony}-fragment-${index + 1}`,
      colony:
        unitType === "site" && suffix === "C" && index === 2
          ? `${primaryColony}-2`
          : primaryColony,
      width,
    }));
    const shots: RecordingShot[] = fragments.map(({ organism }) => ({
      organism,
      visit: baseline,
      width: 20,
    }));
    for (const { organism, width } of fragments) {
      if (width !== null || unitType === "recording") {
        shots.push({
          organism,
          visit: followup,
          width: width ?? 48,
          excluded: width === null,
        });
      }
    }

    let unit = name;
    let recording:
      Awaited<ReturnType<typeof recordPairedGrowthTimeLapse>> | undefined;
    let recordingId: string | undefined;
    if (unitType === "recording") {
      recording = await recordPairedGrowthTimeLapse(page, shots, unitIndex);
      const bytes = recording.video;
      const imported = await checkedJson<{
        id: string;
        sha256: string;
        frame_count: number;
      }>(
        await page.request.post(`${root}/imports/videos`, {
          multipart: {
            file: {
              name: `${name}.mp4`,
              mimeType: "video/mp4",
              buffer: bytes,
            },
          },
        }),
        201,
      );
      expect(imported.sha256).toBe(sha256(bytes));
      expect(imported.frame_count).toBe(shots.length);
      recordingId = imported.id;
      unit = `${name}-${imported.sha256.slice(0, 12)}`;
      recordings.push({
        id: imported.id,
        unit_id: unit,
        sha256: imported.sha256,
        frame_count: imported.frame_count,
      });
    }

    for (const colony of new Set(
      fragments.map((fragment) => fragment.colony),
    )) {
      await register(unit, colony);
    }
    for (const fragment of fragments) {
      await register(unit, fragment.organism, fragment.colony);
    }
    for (const [capture, shot] of shots.entries()) {
      await seedVisit(
        shot.organism,
        shot.visit,
        shot.width,
        recording && recordingId
          ? {
              jpeg: recording.photos[capture],
              recordingId,
              order: capture + 1,
              excluded: shot.excluded,
            }
          : undefined,
      );
    }
    samplingPlan.push({
      experimental_unit_id: unit,
      organism_keys: fragments.map((fragment) => fragment.organism),
      dates,
    });
  }

  const analysis = await checkedJson<{
    id: string;
    content_sha256: string;
    stale: boolean;
    snapshot: { result: { kind: string; observations: typeof sourceFiles } };
  }>(
    await page.request.post(`${ecology}/verified-analyses`, {
      data: {
        selection: {
          kind: "growth",
          metric: "box_width",
          sources,
          sampling_plan: samplingPlan,
        },
        reviewed_by: "Synthetic fixture reviewer",
        review_note: `Checked the two explicit UTC visits, sources and incomplete ${unitType}.`,
        confirm_reviewed_selection: true,
      },
    }),
    201,
  );
  expect(analysis.stale).toBe(false);
  expect(analysis.snapshot.result.kind).toBe("growth");
  const includedFiles = sourceFiles.filter((file) => !file.excluded);
  expect(analysis.snapshot.result.observations).toHaveLength(
    includedFiles.length,
  );
  expect(analysis.snapshot.result.observations).toEqual(
    expect.arrayContaining(
      includedFiles.map(({ image_id, image_sha256, capture_utc }) =>
        expect.objectContaining({
          image_id,
          image_sha256,
          ...(capture_utc ? { observed_at: capture_utc } : {}),
        }),
      ),
    ),
  );
  return {
    root,
    projectId,
    analysis,
    sourceFiles,
    recordings,
    samplingPlan,
    excludedFrameReason,
  };
}

test.use({
  spatialApi:
    process.env.REEFVISION_ECOLOGY_TEST_API ??
    process.env.REEFVISION_GUIDED_TEST_API ??
    "",
  spatialWeb:
    process.env.REEFVISION_ECOLOGY_TEST_WEB ??
    process.env.REEFVISION_GUIDED_TEST_WEB ??
    "",
});

test(`declares, downloads and replays an equal-${unitType} two-visit growth contrast`, async ({
  desktop: { page, api, web, surface },
}, info) => {
  test.setTimeout(120_000);
  const projectName = `Synthetic paired ${unitType} growth ${randomUUID()}`;
  const {
    root,
    projectId,
    analysis,
    sourceFiles,
    recordings,
    samplingPlan,
    excludedFrameReason,
  } = await seedReviewedGrowth(page, api, projectName);
  const unitIds = samplingPlan.map((row) => row.experimental_unit_id);
  const { version } = JSON.parse(await readFile("package.json", "utf8")) as {
    version: string;
  };
  await page.addInitScript(
    (value) =>
      localStorage.setItem(`reefvision.onboarding.dismissed.${value}`, "true"),
    version,
  );

  async function openProject() {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${projectName}`, exact: true })
      .click();
  }

  const post = (url: string) =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" && response.url() === url,
    );
  const download = async (
    button: ReturnType<Page["getByRole"]>,
    filename: string,
    report: PairedReport,
  ) => {
    const pending = page.waitForEvent("download");
    await button.click();
    const completed = await pending;
    expect(completed.suggestedFilename()).toBe(
      `paired-growth-${report.report_sha256}.json`,
    );
    const path = info.outputPath(filename);
    await completed.saveAs(path);
    expect(JSON.parse(await readFile(path, "utf8"))).toEqual(report);
  };

  await openProject();
  await page
    .getByRole("tab", { name: "Organisms & ecology", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Reviewed analyses", exact: true })
    .click();
  const analyses = page.getByRole("region", {
    name: "Reviewed ecological analyses",
  });
  await analyses.getByRole("button", { name: /^Growth ·/ }).click();
  await analyses
    .getByText("Repeated measures", { exact: true })
    .click({ timeout: 8_000 });
  const form = analyses.getByRole("form", {
    name: "Declare paired growth contrast",
  });
  await form
    .getByRole("combobox", { name: /^Baseline UTC date/ })
    .selectOption(baseline);
  await form
    .getByRole("combobox", { name: /^Follow-up UTC date/ })
    .selectOption(followup);
  await form.getByLabel("Independent unit type").fill(unitType);
  await form.getByLabel("Declared estimand").fill(estimand);
  const calculate = form.getByRole("button", {
    name: "Calculate paired contrast",
  });
  await expect(calculate).toBeDisabled();
  await form.getByRole("checkbox", { name: /^Exclude a unit/ }).check();
  const pairedResponse = post(
    `${root}/ecology/verified-analyses/${analysis.id}/paired-contrast`,
  );
  await calculate.click();
  const paired = await pairedResponse;
  const request = { ...design, source_sha256: analysis.content_sha256 };
  expect(paired.request().postDataJSON()).toEqual(request);
  expect(paired.status(), await paired.text()).toBe(200);
  const result = (await paired.json()) as PairedReport;

  const standardError = 2 / Math.sqrt(3);
  const studentTCritical = 4.302652729696142;
  expect(result).toMatchObject({
    analysis_id: analysis.id,
    source_sha256: analysis.content_sha256,
    design,
    metric: "box_width",
    unit: "mm",
    planned_unit_count: 4,
    included_unit_count: 3,
    mean_difference: 3,
    standard_error: expect.closeTo(standardError, 10),
    degrees_of_freedom: 2,
    confidence_interval_95: [
      expect.closeTo(3 - studentTCritical * standardError, 8),
      expect.closeTo(3 + studentTCritical * standardError, 8),
    ],
    report_sha256: expect.stringMatching(/^[0-9a-f]{64}$/),
  });
  const units = new Map(
    result.units.map((row) => [row.experimental_unit_id, row]),
  );
  expect(units.size).toBe(4);
  expect(
    unitIds.slice(0, 3).map((unit) => units.get(unit)?.difference),
  ).toEqual([1, 3, 5]);
  if (unitType === "site") {
    const site = units.get(unitIds[2])!;
    expect(site.organisms.map((row) => row.difference)).toEqual([0, 2, 9]);
    expect(
      new Set(site.organisms.map((row) => row.parent_colony_id)).size,
    ).toBe(2);
  }
  if (unitType === "colony") {
    expect(
      result.units.every(
        (row) =>
          new Set(row.organisms.map((organism) => organism.parent_colony_id))
            .size === 1,
      ),
    ).toBe(true);
  }
  if (unitType === "recording") {
    expect(new Set(recordings.map((row) => row.sha256)).size).toBe(4);
    expect(result.source_exclusions).toContainEqual(
      expect.objectContaining({ reason: excludedFrameReason }),
    );
  }
  expect(units.get(unitIds[3])).toMatchObject({
    status: "excluded",
    reason: "incomplete_unit",
    difference: null,
    organisms: expect.arrayContaining([
      expect.objectContaining({ difference: 8 }),
      expect.objectContaining({
        baseline_source_record_id: expect.any(String),
        followup_source_record_id: null,
      }),
    ]),
  });
  const report = analyses.getByRole("region", {
    name: "Paired contrast result",
  });
  await expect(
    report.getByText("3 of 4 planned independent units included", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    report.getByRole("row", { name: new RegExp(unitIds[3]) }),
  ).toContainText("incomplete_unit");
  await report.screenshot({ path: info.outputPath("paired-contrast.png") });
  await download(
    report.getByRole("button", { name: "Download paired result JSON" }),
    "standalone.json",
    result,
  );

  const graphResponse = post(`${root}/workflow-graphs`);
  await analyses
    .getByRole("button", { name: "Save paired workflow", exact: true })
    .click();
  const saved = await graphResponse;
  expect(saved.status(), await saved.text()).toBe(201);
  const graph = (await saved.json()) as WorkflowGraphRecord;
  expect(graph.name).toBe(graphName);
  expect(graph.graph_json.nodes).toContainEqual(
    expect.objectContaining({
      node_type: "paired_growth_contrast",
      parameters: { analysis_id: analysis.id, ...request },
    }),
  );

  async function replaySaved(index: number) {
    await openProject();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
    const revision = page.getByRole("listitem").filter({ hasText: graphName });
    await revision.getByRole("button", { name: "Load", exact: true }).click();
    await expect(page.locator("[data-node-id='paired']")).toBeVisible();
    const queuedResponse = post(`${root}/workflow-runs`);
    await revision
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const queued = await queuedResponse;
    expect(queued.status(), await queued.text()).toBe(202);
    const { id } = (await queued.json()) as { id: string };
    let detail!: WorkflowRunDetail;
    await expect
      .poll(async () => {
        detail = await checkedJson<WorkflowRunDetail>(
          await page.request.get(`${api}/workflow-runs/${id}`),
          200,
        );
        return detail.run.status;
      })
      .not.toMatch(/queued|running/);
    expect(detail.run.status, detail.run.error_message ?? undefined).toBe(
      "succeeded",
    );
    expect(detail.run.workflow_graph_record_id).toBe(graph.id);
    expect(detail.run.graph_sha256).toBe(graph.graph_sha256);
    const artifact = detail.artifacts.find(
      (row) => row.data_type === "paired_growth_contrast",
    );
    expect(artifact?.producer_port_id).toBe("contrast");
    expect(artifact?.payload_json).toEqual(result);
    await download(
      page.getByRole("button", {
        name: "Download paired result JSON",
        exact: true,
      }),
      `saved-run-${index}.json`,
      result,
    );
    return { id, payload_sha256: artifact?.payload_sha256 };
  }

  const first = await replaySaved(1);
  const second = await replaySaved(2);
  expect(second.id).not.toBe(first.id);
  expect(first.payload_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(second.payload_sha256).toBe(first.payload_sha256);
  for (const image of sourceFiles) {
    const content = await page.request.get(
      `${api}/images/${image.image_id}/content`,
    );
    expect(content.status()).toBe(200);
    expect(sha256(await content.body())).toBe(image.image_sha256);
  }
  for (const recording of recordings) {
    const content = await page.request.get(
      `${api}/videos/${recording.id}/content`,
    );
    expect(content.status()).toBe(200);
    expect(sha256(await content.body())).toBe(recording.sha256);
  }
  await writeFile(
    info.outputPath("paired-growth-evidence.json"),
    JSON.stringify(
      {
        surface,
        project_id: projectId,
        reviewed_analysis_id: analysis.id,
        source_sha256: analysis.content_sha256,
        report_sha256: result.report_sha256,
        graph_record_id: graph.id,
        graph_sha256: graph.graph_sha256,
        runs: [first, second],
        original_files: sourceFiles,
        original_recordings: recordings,
        experimental_unit_type: unitType,
      },
      null,
      2,
    ),
  );
});
