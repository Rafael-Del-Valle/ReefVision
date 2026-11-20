import { createHash, randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

import { expect, type APIResponse, type Response } from "@playwright/test";

import type {
  DatasetVersionRecord,
  Project,
  ReviewQueueItem,
  ReviewQueueRecord,
} from "../../src/api/client";
import type {
  WorkflowGraphRecord,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import { test } from "./spatialDesktop";

async function checked<T>(response: APIResponse | Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

function sha256(bytes: Buffer) {
  return createHash("sha256").update(bytes).digest("hex");
}

test("coordinates frozen QC review and reopens two saved workflow runs", async ({
  desktop,
}, info) => {
  test.setTimeout(120_000);
  const { page, api, web, surface } = desktop;
  const name = `Frozen QC ${randomUUID().slice(0, 8)}`;
  const reviewer = "Fixture QC researcher";
  const assignee = "Fixture QC colleague";
  const note = "Recheck the annotated boundary against the frozen original.";
  const graphName = "QC review queue from a frozen dataset";
  const versionName = "Frozen QC source";
  const health = await checked<{ version: string }>(
    await page.request.get(`${api}/health`),
    200,
  );
  await page.addInitScript((version) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${version}`, "true");
  }, health.version);

  const project = await checked<Project>(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
    201,
  );
  const root = `${api}/projects/${project.id}`;
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
  const images: { id: string; original_sha256: string }[] = [];
  await page.goto(web);
  for (const width of [80, 81]) {
    const base64 = await page.evaluate((width) => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = 60;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#244f60";
      context.fillRect(0, 0, width, 60);
      context.fillStyle = "#b79870";
      context.fillRect(5, 5, 20, 20);
      return canvas.toDataURL("image/png").split(",")[1];
    }, width);
    const bytes = Buffer.from(base64, "base64");
    const filename = `frozen-qc-${width}.png`;
    const imported = await checked<{ successful: { image_id: string }[] }>(
      await page.request.post(`${root}/imports/images`, {
        multipart: {
          files: { name: filename, mimeType: "image/png", buffer: bytes },
          relative_paths: filename,
        },
      }),
      200,
    );
    const imageId = imported.successful[0].image_id;
    images.push({ id: imageId, original_sha256: sha256(bytes) });
    await checked(
      await page.request.put(`${api}/images/${imageId}/annotations`, {
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
  const version = await checked<DatasetVersionRecord>(
    await page.request.post(`${root}/dataset-versions`, {
      data: {
        name: versionName,
        eligible_annotation_statuses: ["reviewed"],
        split_method: "group_random",
        requested_ratios: { train: 0.7, validation: 0.2, test: 0.1 },
        split_seed: 11,
      },
    }),
    201,
  );

  const waitForPost = (url: string) =>
    page.waitForResponse(
      (response) =>
        response.url() === url && response.request().method() === "POST",
    );
  async function openProject() {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  }
  async function openReview() {
    await page.getByRole("tab", { name: "Review", exact: true }).click();
    await page.getByRole("tab", { name: "Review queue", exact: true }).click();
    await page
      .getByRole("combobox", { name: /^Scope/ })
      .selectOption("dataset_version");
    await page
      .getByRole("combobox", { name: /^Dataset version/ })
      .selectOption(version.id);
  }
  async function openWorkflows() {
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
  }
  async function queueItems(queueId: string) {
    const result = await checked<{ items: ReviewQueueItem[] }>(
      await page.request.get(`${api}/review-queues/${queueId}/items`),
      200,
    );
    return result.items;
  }
  function getRankedArticle(rank: number) {
    return page.locator("article.dashboard-row").filter({
      has: page.getByText(`Rank #${rank}`, { exact: true }),
    });
  }

  await openProject();
  await openReview();
  const generated = waitForPost(
    `${api}/dataset-versions/${version.id}/review-queues`,
  );
  await page
    .getByRole("button", { name: "Generate queue", exact: true })
    .click();
  const standalone = await checked<ReviewQueueRecord>(await generated, 201);
  await expect(
    page.getByText("Dataset-version review", { exact: true }),
  ).toBeVisible();
  const standaloneItems = await queueItems(standalone.id);
  expect(standaloneItems).toHaveLength(2);
  expect(standaloneItems.map((item) => item.image_id).sort()).toEqual(
    images.map((image) => image.id).sort(),
  );

  const coordination = page.getByRole("region", {
    name: "Review coordination",
  });
  const recordedNote = coordination
    .getByRole("listitem")
    .filter({ hasText: note });
  const openRankOne = () =>
    getRankedArticle(1)
      .getByRole("button", { name: "Comments & assignments" })
      .click();
  await openRankOne();
  await coordination.getByLabel("Your local reviewer label").fill(reviewer);
  await coordination.getByLabel("Reviewer to assign").fill(assignee);
  await coordination
    .getByRole("button", { name: "Assign reviewer", exact: true })
    .click();
  await expect(
    coordination.getByText(`Assigned reviewer: ${assignee}`),
  ).toBeVisible();
  await coordination.getByLabel("Review comment").fill(note);
  await coordination.getByRole("button", { name: "Add comment" }).click();
  await expect(recordedNote).toBeVisible();
  const blocked = page.waitForEvent("dialog").then(async (dialog) => {
    expect(dialog.message()).toContain("close reviewer coordination");
    await dialog.accept();
  });
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await blocked;
  await expect(recordedNote).toBeVisible();
  await coordination
    .getByRole("button", { name: "Close coordination" })
    .click();
  await expect(coordination).toBeHidden();

  const bulk = page.getByRole("region", { name: "Bulk QC triage" });
  const bulkRoute = `${api}/review-queues/${standalone.id}/items/bulk`;
  await bulk.getByLabel("Bulk triage reviewer label").fill(reviewer);
  await bulk
    .getByRole("button", { name: "Select eligible on page (2)" })
    .click();
  await bulk.getByLabel("Confirm manual triage").check();
  const bulkSubmitted = waitForPost(bulkRoute);
  await bulk.getByRole("button", { name: "Apply start to 2 items" }).click();
  const bulkResponse = await bulkSubmitted;
  const originalRequest = bulkResponse.request().postDataJSON();
  const firstTriage = await checked<{
    changed_count: number;
    requires_researcher_review: boolean;
    items: ReviewQueueItem[];
  }>(bulkResponse, 200);
  expect(firstTriage.changed_count).toBe(2);
  expect(firstTriage.requires_researcher_review).toBe(true);
  await expect(
    getRankedArticle(1).getByText("in_progress", { exact: true }),
  ).toBeVisible();

  await openProject();
  await openReview();
  await openRankOne();
  await expect(
    coordination.getByText(`Assigned reviewer: ${assignee}`),
  ).toBeVisible();
  await expect(recordedNote).toBeVisible();
  await coordination
    .getByRole("button", { name: "Close coordination" })
    .click();
  const retry = await checked<typeof firstTriage>(
    await page.request.post(bulkRoute, { data: originalRequest }),
    200,
  );
  expect(retry.changed_count).toBe(0);
  expect(
    retry.items.map((item) => [item.id, item.review_state]).sort(),
  ).toEqual(firstTriage.items.map((item) => [item.id, "in_progress"]).sort());
  expect(
    (
      await page.request.post(bulkRoute, {
        data: { ...originalRequest, actor: "Changed local label" },
      })
    ).status(),
  ).toBe(409);

  const firstItemId = standaloneItems.find(
    (item) => item.rank_position === 1,
  )!.id;
  const rankedState = async () =>
    (await queueItems(standalone.id)).find((item) => item.id === firstItemId)
      ?.review_state;
  await page.getByLabel("Single-item reviewer label").fill(reviewer);
  const complete = getRankedArticle(1).getByRole("button", {
    name: "Mark complete",
    exact: true,
  });
  await complete.click();
  const confirmation = page.getByRole("alertdialog", {
    name: "Complete QC review",
  });
  await expect(
    confirmation.getByRole("button", { name: "Cancel" }),
  ).toBeFocused();
  expect(await rankedState()).toBe("in_progress");
  await page.keyboard.press("Escape");
  await expect(confirmation).toHaveCount(0);
  await expect(complete).toBeFocused();
  expect(await rankedState()).toBe("in_progress");
  await complete.click();
  const completing = waitForPost(
    `${api}/review-queue-items/${firstItemId}/complete`,
  );
  await confirmation.getByRole("button", { name: "Complete review" }).click();
  expect(
    (await checked<ReviewQueueItem>(await completing, 200)).review_state,
  ).toBe("completed");
  await expect.poll(rankedState).toBe("completed");

  await openWorkflows();
  await page
    .getByRole("combobox", { name: /^Template/ })
    .selectOption({ label: graphName });
  await page
    .locator('[data-node-id="dataset"]')
    .getByRole("button", {
      name: "Configure",
      exact: true,
    })
    .click();
  await page
    .getByRole("combobox", { name: /^Frozen dataset version/ })
    .selectOption(version.id);
  const saved = waitForPost(`${root}/workflow-graphs`);
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  const graph = await checked<WorkflowGraphRecord>(await saved, 201);
  expect(graph.graph_json.nodes).toContainEqual(
    expect.objectContaining({
      node_type: "dataset_version_source",
      parameters: { dataset_version_id: version.id },
    }),
  );

  const comparable = (items: ReviewQueueItem[]) =>
    items
      .map((item) => ({
        image: item.image_id,
        score: item.score,
        input_sha256: item.input_checksum,
      }))
      .sort((left, right) => left.image.localeCompare(right.image));
  const expectedRanking = comparable(standaloneItems);
  const runReceipts = [];
  for (const attempt of [1, 2]) {
    await openProject();
    await openWorkflows();
    const revision = page.getByRole("listitem").filter({ hasText: graphName });
    await revision.getByRole("button", { name: "Load", exact: true }).click();
    const queued = waitForPost(`${root}/workflow-runs`);
    await revision
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const { id: runId } = await checked<{ id: string }>(await queued, 202);
    let detail!: WorkflowRunDetail;
    await expect
      .poll(
        async () => {
          detail = await checked<WorkflowRunDetail>(
            await page.request.get(`${api}/workflow-runs/${runId}`),
            200,
          );
          return detail.run.status;
        },
        { timeout: 30_000 },
      )
      .not.toMatch(/queued|running/);
    expect(detail.run.status, detail.run.error_message ?? undefined).toBe(
      "succeeded",
    );
    const artifact = detail.artifacts.find(
      (row) => row.data_type === "review_queue_reference",
    )!;
    expect(artifact.producer_port_id).toBe("queue");
    expect(artifact.payload_json).toEqual(
      expect.objectContaining({
        project_id: project.id,
        dataset_version_id: version.id,
        dataset_manifest_sha256: version.manifest_sha256,
        item_count: 2,
        priority_score_unit: "dimensionless",
        review_status: "requires_researcher_review",
        workflow_run_id: runId,
      }),
    );
    const generatedQueueId = String(artifact.payload_json.queue_id);
    expect(comparable(await queueItems(generatedQueueId))).toEqual(
      expectedRanking,
    );
    runReceipts.push({
      id: runId,
      queue_id: generatedQueueId,
      payload_sha256: artifact.payload_sha256,
    });
    if (attempt === 2) {
      const handoff = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname ===
          `/api/v1/review-queues/${generatedQueueId}/items`,
      );
      await page
        .getByRole("button", {
          name: "Open generated review queue",
          exact: true,
        })
        .click();
      await expect(
        page.getByRole("combobox", { name: /^Dataset version/ }),
      ).toHaveValue(version.id);
      expect((await handoff).ok()).toBe(true);
      await expect(getRankedArticle(1)).toBeVisible();
      await expect(
        page.getByText("Dataset-version review", { exact: true }),
      ).toBeVisible();
    }
  }
  expect(runReceipts[0].id).not.toBe(runReceipts[1].id);
  expect(runReceipts[0].queue_id).not.toBe(runReceipts[1].queue_id);
  for (const image of images) {
    const original = await page.request.get(
      `${api}/images/${image.id}/content`,
    );
    expect(original.ok()).toBe(true);
    expect(sha256(await original.body())).toBe(image.original_sha256);
  }
  await writeFile(
    info.outputPath("qc-review-workflow.json"),
    JSON.stringify(
      {
        surface,
        project_id: project.id,
        dataset_version_id: version.id,
        dataset_manifest_sha256: version.manifest_sha256,
        standalone_queue_id: standalone.id,
        explicit_completion_confirmed: true,
        bulk_request: originalRequest,
        graph_id: graph.id,
        graph_sha256: graph.graph_sha256,
        images,
        ranking: expectedRanking,
        runs: runReceipts,
      },
      null,
      2,
    ),
  );
});
