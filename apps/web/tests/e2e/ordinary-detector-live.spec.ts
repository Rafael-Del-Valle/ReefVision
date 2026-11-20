import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import type {
  AnnotationSaveResponse,
  DatasetVersionRecord,
  ExportRecord,
  ImageImportReport,
  JobRecord,
  LabelClass,
  ModelRegistration,
  PredictionProposal,
  Project,
  ProjectImage,
  TrainingRun,
} from "../../src/api/client";
import type {
  VideoAssetRecord,
  VideoTrackRecord,
} from "../../src/features/video/videoApi";
import { detectorStill } from "./ordinaryDetectorFixture";
import { test } from "./spatialDesktop";

type VersionItem = { image_id: string; split: string; image_sha256: string };
type SavedExport = { export: ExportRecord; job: JobRecord };
type ReviewedPrediction = {
  annotation: AnnotationSaveResponse["annotations"][number];
  proposal: PredictionProposal;
};

const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
const boxKeys = ["x_min", "y_min", "x_max", "y_max"] as const;

async function json<T>(response: APIResponse | Response): Promise<T> {
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as T;
}

function writing(page: Page, url: string, method = "POST") {
  return page.waitForResponse(
    (response) =>
      response.request().method() === method && response.url() === url,
    { timeout: 30_000 },
  );
}

async function completed<
  T extends { status: string; error_message?: string | null },
>(read: () => Promise<T>, success: string) {
  let last: T | undefined;
  await expect
    .poll(
      async () => {
        last = await read();
        expect(last.status, last.error_message ?? undefined).not.toBe("failed");
        return last.status;
      },
      { timeout: 110_000, intervals: [500, 1000, 2000, 3000] },
    )
    .toBe(success);
  return last!;
}

test.skip(
  process.env.REEFVISION_ORDINARY_DETECTOR_ACCEPTANCE !== "1",
  "Opt in with an isolated local API and the CPU detector runtime",
);
test("runs the ordinary local detector from grouped stills through reviewed results and exports", async ({
  desktop,
}, info) => {
  test.setTimeout(240_000);
  const { page, api, web, surface } = desktop;
  page.setDefaultTimeout(20_000);
  if (surface === "source-browser")
    await page.setViewportSize({ width: 1440, height: 980 });
  const name = `Synthetic ordinary detector ${randomUUID().slice(0, 8)}`;
  const project = await json<Project>(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
  );
  const root = `${api}/projects/${project.id}`;
  const label = await json<LabelClass>(
    await page.request.post(`${root}/classes`, {
      data: {
        class_index: 0,
        name: "Fixture square",
        display_color: "#28A95C",
      },
    }),
  );
  const get = async <T>(url: string) => json<T>(await page.request.get(url));
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.5.0", "true"),
  );
  const openProject = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  };
  const importStills = async (
    files: ReturnType<typeof detectorStill>["file"][],
  ) => {
    const imported = writing(page, `${root}/imports/images`);
    await page.getByLabel("Import files", { exact: true }).setInputFiles(files);
    const response = await json<ImageImportReport>(await imported);
    expect(response.successful, JSON.stringify(response)).toHaveLength(
      files.length,
    );
    return response.successful;
  };

  const { dataset, frozenItems, groups } =
    await test.step("Import, group and freeze the synthetic stills", async () => {
      await openProject();
      const fixtures = Array.from({ length: 6 }, (_, index) =>
        detectorStill(index),
      );
      const imported = await importStills(fixtures.map(({ file }) => file));
      const groupMembers = new Map<string, string[]>();
      const expectedDigests = new Map<string, string>();
      for (const [index, { box, file }] of fixtures.entries()) {
        const imageId = imported.find(
          (row) => row.filename === file.name,
        )?.image_id;
        expect(imageId).toBeTruthy();
        const group = `fixture-colony-${Math.floor(index / 2) + 1}`;
        const imageUrl = `${api}/images/${imageId}`;
        const card = page.getByRole("article", { name: new RegExp(file.name) });
        await card.getByText("Image details", { exact: true }).click();
        await card.getByLabel("Group key", { exact: true }).fill(group);
        const grouping = writing(page, imageUrl, "PATCH");
        await card
          .getByRole("button", { name: "Save metadata", exact: true })
          .click();
        const grouped = await json<ProjectImage>(await grouping);
        expect(grouped.group_key).toBe(group);
        expect(grouped.sha256).toBe(sha256(file.buffer));
        // Fixture-authored training labels are independent of model predictions.
        const verified = await json<AnnotationSaveResponse>(
          await page.request.put(`${imageUrl}/annotations`, {
            data: {
              base_revision: grouped.annotation_revision,
              annotation_status: "reviewed",
              annotations: [
                { id: randomUUID(), label_class_id: label.id, ...box },
              ],
            },
          }),
        );
        expect(verified.image.annotation_status).toBe("reviewed");
        groupMembers.set(group, [
          ...(groupMembers.get(group) ?? []),
          grouped.id,
        ]);
        expectedDigests.set(grouped.id, grouped.sha256);
      }

      await page
        .getByRole("tab", { name: "Dataset versions", exact: true })
        .click();
      await page.getByLabel("Version name").fill("Grouped detector fixture");
      await page.getByLabel("Split method").selectOption("group_random");
      await page.getByLabel("Train ratio").fill("0.67");
      await page.getByLabel("Validation ratio").fill("0.33");
      await page.getByLabel("Test ratio").fill("0");
      const freezing = writing(page, `${root}/dataset-versions`);
      await page
        .getByRole("button", { name: "Create immutable version" })
        .click();
      const dataset = await json<DatasetVersionRecord>(await freezing);
      expect(dataset.manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
      const frozenItems = await get<VersionItem[]>(
        `${api}/dataset-versions/${dataset.id}/items`,
      );
      expect(frozenItems).toHaveLength(6);
      expect(frozenItems.map((row) => row.split).sort()).toEqual([
        "train",
        "train",
        "train",
        "train",
        "validation",
        "validation",
      ]);
      const groups = Object.fromEntries(
        [...groupMembers].map(([group, members]) => {
          const membersFrozen = frozenItems.filter((item) =>
            members.includes(item.image_id),
          );
          expect(membersFrozen).toHaveLength(2);
          const splits = new Set(membersFrozen.map((item) => item.split));
          expect(splits.size).toBe(1);
          return [group, { image_ids: members, split: [...splits][0] }];
        }),
      );
      for (const item of frozenItems)
        expect(item.image_sha256).toBe(expectedDigests.get(item.image_id));
      return { dataset, frozenItems, groups };
    });

  const { model, run } =
    await test.step("Train on CPU from a local architecture and register its checkpoint", async () => {
      await page.getByRole("tab", { name: "Models & AI", exact: true }).click();
      await page.getByRole("tab", { name: "Training", exact: true }).click();
      await page
        .getByRole("button", { name: "New draft", exact: true })
        .click();
      await page
        .getByLabel("Run name", { exact: true })
        .fill("Ordinary offline CPU detector");
      const modelSelection = page.locator("article").filter({
        has: page.getByRole("heading", {
          name: "Task-first model selection",
          exact: true,
        }),
      });
      await modelSelection.getByLabel(/^Task/).selectOption("detect");
      await modelSelection.getByLabel(/^Architecture/).selectOption("YOLO11");
      await modelSelection
        .getByLabel(/Model size or preset/)
        .selectOption("ultralytics/yolo11/detect/n");
      await expect(
        page.getByText("Random initialization — No trained weights are used."),
      ).toBeVisible();
      await page.getByLabel("Device").selectOption("cpu");
      await page.getByLabel("Precision").selectOption("fp32");
      await page
        .getByRole("tab", { name: "Dataset & Splits", exact: true })
        .click();
      await page.getByLabel("Dataset version").selectOption(dataset.id);
      await page
        .getByRole("tab", { name: "Hyperparameters", exact: true })
        .click();
      await page.getByLabel("Epochs", { exact: true }).fill("1");
      await page.getByLabel("Batch", { exact: true }).fill("2");
      await page.getByLabel("Image size", { exact: true }).fill("96");
      await page.getByLabel("Workers", { exact: true }).fill("0");
      await page.getByRole("tab", { name: "New Run", exact: true }).click();
      const queue = writing(page, `${root}/training-runs`);
      await page
        .getByRole("button", { name: "Start training", exact: true })
        .click();
      const queued = await json<TrainingRun>(await queue);
      expect(queued).toMatchObject({
        dataset_version_id: dataset.id,
        dataset_manifest_sha256: dataset.manifest_sha256,
        device: "cpu",
        precision: "fp32",
        architecture: "yolo11n.yaml",
        initial_checkpoint_source: "scratch",
        initial_checkpoint_model_id: null,
      });
      const run = await completed(
        () => get<TrainingRun>(`${api}/training-runs/${queued.id}`),
        "completed",
      );
      expect(run.artifact_manifest.pretrained).toBe(false);
      const register = page.getByRole("button", {
        name: "Register best detector",
        exact: true,
      });
      await expect(register).toBeEnabled({ timeout: 25_000 });
      const registering = writing(page, `${root}/models/register-from-run`);
      await register.click();
      const model = await json<ModelRegistration>(await registering);
      expect(model.metadata_json).toMatchObject({
        source_training_run_id: run.id,
        source_dataset_version_id: dataset.id,
        source_dataset_manifest_sha256: dataset.manifest_sha256,
        source_split_manifest_sha256: run.split_manifest_sha256,
        source_resolved_model_checksum: null,
      });
      const artifacts = run.artifact_manifest.artifacts as Array<{
        relative_path: string;
      }>;
      const checkpointIndex = artifacts.findIndex(
        (row) => row.relative_path === run.result_checkpoint_path,
      );
      expect(checkpointIndex).toBeGreaterThanOrEqual(0);
      const checkpoint = await page.request.get(
        `${api}/training-runs/${run.id}/artifacts/${checkpointIndex}`,
      );
      expect(checkpoint.ok()).toBeTruthy();
      expect(sha256(await checkpoint.body())).toBe(model.sha256);
      return { model, run };
    });

  const reviewedRuntime =
    await test.step("Confirm a Model Hub runtime, infer and reopen the same saved workflow", async () => {
      const openHub = async () => {
        await openProject();
        await page
          .getByRole("tab", { name: "Models & AI", exact: true })
          .click();
        await page.getByRole("tab", { name: "Model Hub", exact: true }).click();
      };
      await openHub();
      const hub = page.getByRole("region", { name: "Local model runtime" });
      await hub.getByLabel("Registered checkpoint").selectOption(model.id);
      const device =
        process.env.REEFVISION_REVIEWED_RUNTIME_DEVICE === "cuda"
          ? "cuda"
          : "cpu";
      await hub.getByLabel("Inference device").selectOption(device);
      await hub
        .getByLabel("Configuration request (optional)")
        .fill("confidence 0, iou 0.45");
      await hub
        .getByRole("button", { name: "Preview local configuration" })
        .click();
      await expect(hub.getByText(model.sha256, { exact: true })).toBeVisible();
      const saving = writing(page, root + "/model-runtime-selections");
      await hub
        .getByRole("button", { name: "Confirm reviewed configuration" })
        .click();
      const selection = await json<{
        id: string;
        content_sha256: string;
        snapshot: { settings: Record<string, unknown> };
      }>(await saving);
      expect(selection.snapshot.settings).toEqual({
        confidence_threshold: 0,
        iou_threshold: 0.45,
        device,
      });
      await openHub();
      await hub
        .getByLabel("Reviewed model configuration")
        .selectOption(selection.id);
      const imageId = frozenItems.find(
        (item) => item.split === "validation",
      )!.image_id;
      await hub.getByLabel("Inference image").selectOption(imageId);
      const queue = writing(page, root + "/inference-jobs");
      await hub.getByRole("button", { name: "Run reviewed inference" }).click();
      const queued = await json<JobRecord>(await queue);
      const job = await completed(
        () => get<JobRecord>(api + "/jobs/" + queued.id),
        "succeeded",
      );
      expect(job.request_json).toMatchObject({
        runtime_selection_id: selection.id,
        runtime_selection_sha256: selection.content_sha256,
        device,
        model_id: model.id,
      });
      await expect(
        hub.getByRole("button", { name: "Review image predictions" }),
      ).toBeVisible();
      const openWorkflow = async () => {
        await openProject();
        await page
          .getByRole("tab", { name: "Video & automation", exact: true })
          .click();
        await page
          .getByRole("tab", { name: "Workflow builder", exact: true })
          .click();
      };
      await openWorkflow();
      await page
        .getByRole("combobox")
        .filter({
          has: page.getByRole("option", {
            name: "Project images",
            exact: true,
          }),
        })
        .selectOption("project-images");
      await page.getByLabel("Add node").selectOption("reviewed_model_runtime");
      const node = page.locator("[data-node-id^='reviewed_model_runtime-']");
      await node
        .getByRole("button", { name: "Configure", exact: true })
        .click();
      await page
        .getByLabel("Reviewed model configuration")
        .selectOption(selection.id);
      await page
        .locator("[data-node-id='project']")
        .getByRole("button", { name: /Project.*▶/i })
        .click();
      await node.getByRole("button", { name: /◀.*Project/i }).click();
      await page.getByLabel("Add node").selectOption("detection_inference");
      const inferNode = page.locator("[data-node-id^='detection_inference-']");
      await page
        .locator("[data-node-id='images']")
        .getByRole("button", { name: /Images.*▶/i })
        .click();
      await inferNode.getByRole("button", { name: /◀.*Images/i }).click();
      await node.getByRole("button", { name: /Reviewed model.*▶/i }).click();
      await inferNode.getByRole("button", { name: /◀.*Detector/i }).click();
      const proposalPage = await get<{ items: PredictionProposal[] }>(
        api + "/images/" + imageId + "/prediction-proposals",
      );
      const direct = proposalPage.items.filter(
        (row) => row.inference_job_id === job.id,
      );
      expect(direct.length).toBeGreaterThan(0);
      const runs: {
        id: string;
        digest: string;
        child_job_id: string;
        matched_proposals: number;
      }[] = [];
      for (let i = 0; i < 2; i++) {
        if (i) {
          await openWorkflow();
          await page
            .getByRole("button", { name: "Load", exact: true })
            .first()
            .click();
        }
        const queueRun = writing(page, root + "/workflow-runs");
        await page
          .getByRole("button", { name: "Save & run", exact: true })
          .click();
        const queuedRun = await json<{ id: string }>(await queueRun);
        type Detail = {
          run: { status: string; error_message?: string };
          artifacts: {
            data_type: string;
            payload_sha256: string;
            payload_json: Record<string, unknown>;
          }[];
        };
        const detailUrl = api + "/workflow-runs/" + queuedRun.id;
        await completed(
          async () => (await get<Detail>(detailUrl)).run,
          "succeeded",
        );
        const artifacts = (await get<Detail>(detailUrl)).artifacts;
        const artifact = artifacts.find(
          (x) => x.data_type === "reviewed_model_reference",
        )!;
        expect(artifact.payload_json).toMatchObject({
          runtime_selection_sha256: selection.content_sha256,
          model_sha256: model.sha256,
          device,
        });
        const output = artifacts.find(
          (x) => x.data_type === "detection_proposals",
        )!.payload_json;
        const child = await get<JobRecord>(
          api + "/jobs/" + String(output.inference_job_id),
        );
        expect(child.request_json).toMatchObject({
          runtime_selection_sha256: selection.content_sha256,
          device,
          confidence_threshold: 0,
          iou_threshold: 0.45,
        });
        const detections = (
          output.detections as Array<{
            image_id: string;
            predicted_label: string;
            confidence: number;
            box: { x_min: number; y_min: number; x_max: number; y_max: number };
          }>
        ).filter((x) => x.image_id === imageId);
        expect(detections.length).toBe(direct.length);
        const sortKey = (x: {
          confidence: number;
          x_min: number;
          y_min: number;
        }) => [x.confidence, x.x_min, x.y_min].join("/");
        const sortedDirect = [...direct].sort((a, b) =>
          sortKey(a).localeCompare(sortKey(b)),
        );
        const sortedGraph = detections
          .map((x) => ({
            ...x.box,
            confidence: x.confidence,
            predicted_label: x.predicted_label,
          }))
          .sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
        for (const [i, row] of sortedGraph.entries()) {
          expect(row.predicted_label).toBe(sortedDirect[i].predicted_label);
          for (const key of [
            "confidence",
            "x_min",
            "y_min",
            "x_max",
            "y_max",
          ] as const)
            expect(row[key]).toBeCloseTo(sortedDirect[i][key], 6);
        }
        runs.push({
          id: queuedRun.id,
          digest: artifact.payload_sha256,
          child_job_id: child.id,
          matched_proposals: direct.length,
        });
      }
      expect(runs[0].digest).toBe(runs[1].digest);
      return { selection, job_id: job.id, image_id: imageId, runs };
    });

  const still =
    await test.step("Run the detector on a held-out still and reopen a corrected review", async () => {
      await openProject();
      const holdout = detectorStill(8);
      const [imported] = await importStills([holdout.file]);
      const imageUrl = `${api}/images/${imported.image_id}`;
      const image = await get<ProjectImage>(imageUrl);
      expect(image.sha256).toBe(sha256(holdout.file.buffer));
      expect(
        frozenItems.some((item) => item.image_sha256 === image.sha256),
      ).toBe(false);
      const openEditor = () =>
        page
          .getByRole("article", { name: new RegExp(holdout.file.name) })
          .getByRole("button", { name: "Annotate" })
          .click();
      await openEditor();
      const editor = page.getByTestId("annotation-editor");
      await editor
        .getByLabel("Trained or imported model")
        .selectOption(model.id);
      // Lower the threshold to exercise review of provisional toy-model output.
      await editor.getByLabel("Deployment confidence").fill("0");
      await editor.getByLabel("Deployment device").selectOption("cpu");
      const starting = writing(page, `${root}/inference-jobs`);
      await editor
        .getByRole("button", { name: "Run model on this image" })
        .click();
      const job = await json<JobRecord>(await starting);
      await completed(
        () => get<JobRecord>(`${api}/jobs/${job.id}`),
        "succeeded",
      );
      const { items } = await get<{ items: PredictionProposal[] }>(
        `${imageUrl}/prediction-proposals`,
      );
      const prediction = items.find((row) => row.inference_job_id === job.id);
      expect(prediction).toMatchObject({
        review_status: "pending",
        model_checksum: model.sha256,
      });
      const before = await get<AnnotationSaveResponse>(
        `${imageUrl}/annotations`,
      );
      expect(before.annotations).toHaveLength(0);
      await editor.getByTestId(`prediction-row-${prediction!.id}`).click();
      await page
        .getByRole("button", { name: "Edit geometry", exact: true })
        .click();
      for (const [index, label] of [
        "X Min",
        "Y Min",
        "X Max",
        "Y Max",
      ].entries()) {
        await page
          .getByLabel(label, { exact: true })
          .fill(String(holdout.box[boxKeys[index]]));
      }
      const accepting = writing(
        page,
        `${api}/prediction-proposals/${prediction!.id}/accept`,
      );
      await page
        .getByRole("button", { name: "Accept reviewed result", exact: true })
        .click();
      const reviewed = await json<ReviewedPrediction>(await accepting);
      expect(reviewed.annotation).toMatchObject({
        ...holdout.box,
        source_prediction_id: prediction!.id,
      });
      expect(reviewed.proposal.was_edited).toBe(true);
      expect(boxKeys.map((key) => reviewed.proposal[key])).toEqual(
        boxKeys.map((key) => prediction![key]),
      );
      await editor.getByLabel("Annotation status").selectOption("reviewed");
      const saving = writing(page, `${imageUrl}/annotations`, "PUT");
      await editor.getByRole("button", { name: "Save now" }).click();
      const save = await saving;
      const saved = await json<AnnotationSaveResponse>(save);
      expect(save.request().postDataJSON().base_revision).toBe(
        before.image.annotation_revision + 1,
      );
      expect(saved.image.annotation_status).toBe("reviewed");

      await openProject();
      await openEditor();
      await expect(
        editor.getByTestId(`annotation-${reviewed.annotation.id}`),
      ).toBeVisible();
      await expect(editor.getByLabel("Annotation status")).toHaveValue(
        "reviewed",
      );
      const reopened = await get<AnnotationSaveResponse>(
        `${imageUrl}/annotations`,
      );
      expect(reopened.annotations).toEqual(saved.annotations);
      expect(reopened.image.sha256).toBe(image.sha256);
      await page.screenshot({
        path: info.outputPath("detector-reviewed-still.png"),
      });
      return {
        image_id: image.id,
        image_sha256: image.sha256,
        job_id: job.id,
        prediction_id: prediction!.id,
        proposal_count: items.length,
        original_box: boxKeys.map((key) => prediction![key]),
        annotation_id: reviewed.annotation.id,
        corrected_box: holdout.box,
        accepted_revision: save.request().postDataJSON().base_revision,
        reopened_revision: reopened.image.annotation_revision,
        reopened_status: reopened.image.annotation_status,
      };
    });

  const videoEvidence =
    await test.step("Infer on an imported clip and reopen its lossless export", async () => {
      const openVideo = async () => {
        await page
          .getByRole("tab", { name: "Video & automation", exact: true })
          .click();
        await page
          .getByRole("tab", { name: "Video & tracking", exact: true })
          .click();
      };
      await openProject();
      await openVideo();
      const videoBytes = await readFile(
        new URL("./fixtures/synthetic-ordinary-clip.mp4", import.meta.url),
      );
      const videoName = "detector-ordinary-clip.mp4";
      await page.getByLabel("Video file", { exact: true }).setInputFiles({
        name: videoName,
        mimeType: "video/mp4",
        buffer: videoBytes,
      });
      const importing = writing(page, `${root}/imports/videos`);
      await page
        .getByRole("button", { name: "Import video", exact: true })
        .click();
      const video = await json<VideoAssetRecord>(await importing);
      expect(video.sha256).toBe(sha256(videoBytes));
      const card = page
        .getByRole("heading", {
          name: "Detection / segmentation / hybrid video tracking",
          exact: true,
        })
        .locator("..");
      await card.getByRole("combobox").nth(0).selectOption("detect");
      await card.getByRole("combobox").nth(1).selectOption(model.id);
      await card.getByLabel("Detection confidence").fill("0");
      await card.getByLabel("Device").selectOption("cpu");
      await card
        .getByRole("checkbox", { name: /Link detections across frames/ })
        .uncheck();
      const running = writing(page, `${api}/videos/${video.id}/tracking-jobs`);
      await card
        .getByRole("button", { name: "Run instance detection", exact: true })
        .click();
      const job = await json<JobRecord>(await running);
      await completed(
        () => get<JobRecord>(`${api}/jobs/${job.id}`),
        "succeeded",
      );
      const tracksUrl = `${api}/videos/${video.id}/tracks`;
      const tracks = (await get<VideoTrackRecord[]>(tracksUrl)).filter(
        (row) => row.source_job_id === job.id,
      );
      expect(tracks.length).toBeGreaterThan(0);
      expect(
        tracks.every(
          (row) =>
            row.status === "machine_generated" &&
            row.source_model_id === model.id,
        ),
      ).toBe(true);
      await page.getByLabel("Existing track").selectOption(tracks[0].id);

      const exchange = page.getByTestId("video-track-exchange-panel");
      await exchange.getByLabel("Video").selectOption(video.id);
      await exchange.getByLabel("Format").selectOption("reefvision_json");
      const getFile = page.waitForEvent("download");
      await exchange
        .getByRole("link", { name: "Export active tracks", exact: true })
        .click();
      const path = info.outputPath("detector-video-tracks.json");
      await (await getFile).saveAs(path);
      const bytes = await readFile(path);
      const exported = JSON.parse(bytes.toString("utf8")) as {
        source_video_sha256: string;
        tracks: {
          original_track_id: string;
          original_source_job_id: string;
          original_source_model_id: string;
        }[];
      };
      expect(exported.source_video_sha256).toBe(video.sha256);
      expect(exported.tracks).toContainEqual(
        expect.objectContaining({
          original_track_id: tracks[0].id,
          original_source_job_id: job.id,
          original_source_model_id: model.id,
        }),
      );
      await openProject();
      await openVideo();
      await expect(
        page.getByTestId("video-tracking-workspace").getByRole("option", {
          name: new RegExp(videoName),
        }),
      ).toHaveAttribute("value", video.id);
      await page.getByLabel("Existing track").selectOption(tracks[0].id);
      const reopened = await get<VideoTrackRecord[]>(tracksUrl);
      expect(reopened.find((row) => row.id === tracks[0].id)).toEqual(
        tracks[0],
      );
      return {
        video_id: video.id,
        video_sha256: video.sha256,
        frame_count: video.frame_count,
        job_id: job.id,
        machine_generated_count: tracks.length,
        export_sha256: sha256(bytes),
        selected_track_id: tracks[0].id,
      };
    });

  const yolo =
    await test.step("Download the same frozen grouped dataset", async () => {
      await openProject();
      await page
        .getByRole("tab", { name: "Dataset versions", exact: true })
        .click();
      const exporting = writing(
        page,
        `${api}/dataset-versions/${dataset.id}/exports`,
      );
      await page
        .getByRole("button", { name: "Export YOLO dataset", exact: true })
        .click();
      const { export: record, job } = await json<SavedExport>(await exporting);
      await completed(
        () => get<JobRecord>(`${api}/jobs/${job.id}`),
        "succeeded",
      );
      const manifest = await get<{
        dataset_version_manifest_sha256: string;
        items: VersionItem[];
      }>(`${api}/exports/${record.id}/manifest`);
      expect(manifest.dataset_version_manifest_sha256).toBe(
        dataset.manifest_sha256,
      );
      expect(manifest.items).toHaveLength(6);
      for (const row of frozenItems) {
        expect(manifest.items).toContainEqual(
          expect.objectContaining({
            image_id: row.image_id,
            image_sha256: row.image_sha256,
            split: row.split,
          }),
        );
      }
      const downloading = page.waitForEvent("download");
      await page
        .getByRole("link", { name: "Download zip", exact: true })
        .click();
      const zip = info.outputPath("detector-grouped-yolo.zip");
      await (await downloading).saveAs(zip);
      const direct = await page.request.get(
        `${api}/exports/${record.id}/download`,
      );
      expect(direct.ok()).toBeTruthy();
      const zipDigest = sha256(await readFile(zip));
      expect(zipDigest).toBe(sha256(await direct.body()));
      return { export_id: record.id, job_id: job.id, zip_sha256: zipDigest };
    });

  await writeFile(
    info.outputPath("ordinary-detector-evidence.json"),
    JSON.stringify(
      {
        surface,
        project_id: project.id,
        class_id: label.id,
        groups,
        dataset_id: dataset.id,
        dataset_manifest_sha256: dataset.manifest_sha256,
        training_run_id: run.id,
        training_job_id: run.job_id,
        device: run.device,
        architecture: run.architecture,
        initializer: run.initial_checkpoint_source,
        split_manifest_sha256: run.split_manifest_sha256,
        model_id: model.id,
        checkpoint_sha256: model.sha256,
        validation_metrics: run.metrics,
        reviewed_runtime: reviewedRuntime,
        still,
        video: videoEvidence,
        yolo,
      },
      null,
      2,
    ),
  );
});
