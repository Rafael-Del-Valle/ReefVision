import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

test("freezes reviewed tracks, trains, refines, reviews, measures, and evaluates temporal ReefPose", async ({
  page,
}, info) => {
  const web = process.env.REEFVISION_TEMPORAL_TEST_WEB;
  const api = process.env.REEFVISION_TEMPORAL_TEST_API;
  const seed = process.env.REEFVISION_TEMPORAL_TEST_SEED;
  test.skip(
    !web || !api || !seed,
    "Requires an isolated seeded project and a real ReefPose runtime",
  );
  test.setTimeout(120000);
  const fixture = JSON.parse(await readFile(seed!, "utf8")) as {
    project_id: string;
    sources: {
      video_id: string;
      frame_track_id: string;
      reviewed_track_id: string;
      split: string;
    }[];
  };
  const scope = `${api}/projects/${fixture.project_id}/temporal-reefpose`;
  const recording = fixture.sources[2];
  const name = `Temporal engineering ${randomUUID().slice(0, 8)}`;
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.8.0", "true"),
  );
  await page.goto(web!);
  await page
    .getByRole("button", {
      name: "Open Synthetic temporal ReefPose",
      exact: true,
    })
    .click();
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Video & tracking", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Video", exact: true })
    .first()
    .selectOption(recording.video_id);
  const panel = page.getByRole("region", { name: "Native temporal ReefPose" });
  const submit = async (label: string, endpoint: "datasets" | "runs") => {
    const completed = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url() === `${scope}/${endpoint}`,
    );
    await panel.getByRole("button", { name: label, exact: true }).click();
    const response = await completed;
    expect(response.status(), await response.text()).toBe(
      endpoint === "runs" ? 202 : 201,
    );
    return await response.json();
  };
  const run = async (label: string) => {
    const queued = await submit(label, "runs");
    await expect
      .poll(
        async () => {
          const response = await page.request.get(`${scope}/runs/${queued.id}`);
          const current = await response.json();
          expect(current.status, current.error).not.toBe("failed");
          return current.status;
        },
        { timeout: 35000 },
      )
      .toBe("succeeded");
    return await (await page.request.get(`${scope}/runs/${queued.id}`)).json();
  };
  await panel.getByLabel("Dataset name").fill(name);
  for (const [index, source] of fixture.sources.entries()) {
    await panel
      .getByRole("button", { name: "Add sequence", exact: true })
      .click();
    const sequence = panel.getByRole("group", {
      name: `Sequence ${index + 1}`,
    });
    await sequence
      .getByLabel("Frame-model track")
      .selectOption(source.frame_track_id);
    await sequence
      .getByLabel("Human-reviewed supervision track")
      .selectOption(source.reviewed_track_id);
    await sequence
      .getByLabel("I confirmed these two tracks represent the same animal")
      .check();
    await sequence.getByLabel("Sequence partition").selectOption(source.split);
  }
  const dataset = await submit("Freeze a sequence dataset", "datasets");
  expect(dataset.source_count).toBe(3);
  await panel.getByLabel("Checkpoint name").fill(name);
  await panel.getByLabel("Temporal context").selectOption("causal");
  await panel.getByLabel("Window length (frames)").fill("3");
  await panel.getByLabel("Epochs").fill("2");
  await panel
    .getByRole("combobox", { name: "Device", exact: true })
    .selectOption(process.env.REEFVISION_TEMPORAL_TEST_DEVICE ?? "cpu");
  const trained = await run("Train a temporal checkpoint");
  const modelId = trained.result.model_id;
  expect(modelId).toBeTruthy();
  const registered = await page.request.get(`${api}/models/${modelId}`);
  expect(registered.ok()).toBeTruthy();
  expect((await registered.json()).task).toBe("pose_temporal");
  await panel
    .getByRole("combobox", { name: "Operation", exact: true })
    .selectOption("inference");
  await panel
    .getByRole("combobox", { name: "Temporal checkpoint", exact: true })
    .selectOption(modelId);
  await panel
    .getByLabel("Frame-model track")
    .selectOption(recording.frame_track_id);
  await panel.getByLabel("Output chunk (frames)").fill("4");
  const refined = await run("Refine frame-model poses");
  const frames = await (
    await page.request.get(`${scope}/runs/${refined.id}/frames`)
  ).json();
  expect(frames.items.length).toBeGreaterThan(3);
  expect(
    frames.items.every(
      (row: { future_frames: number }) => row.future_frames === 0,
    ),
  ).toBeTruthy();
  for (const [index, row] of frames.items.slice(0, 6).entries()) {
    await panel
      .locator("summary")
      .filter({ hasText: new RegExp(`^Frame ${row.frame_index} ·`) })
      .click();
    await panel
      .getByRole("combobox", {
        name: `Review decision for frame ${row.frame_index}`,
        exact: true,
      })
      .selectOption(index % 2 === 0 ? "refined" : "frame");
  }
  await panel
    .getByLabel("I confirmed these pose choices against the recording")
    .check();
  const review = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith(`/${refined.id}/reviews`),
  );
  await panel
    .getByRole("button", { name: "Save pose review revision" })
    .click();
  const reviewed = await review;
  expect(reviewed.status(), await reviewed.text()).toBe(201);
  await page.screenshot({
    path: info.outputPath("temporal-refinement-review.png"),
  });
  const reviewedIdentity = await reviewed.json();
  await panel
    .getByRole("button", { name: "Open in biological measurements" })
    .click();
  const movement = page.getByRole("region", {
    name: "Biological movement analysis",
  });
  await expect(movement.getByLabel("Reviewed identity run")).toHaveValue(
    reviewedIdentity.identity_run_id,
  );
  await movement.getByLabel("Landmark 1").selectOption("jaw-a");
  await movement.getByLabel("Landmark 2").selectOption("jaw-b");
  await movement
    .getByRole("button", { name: "Calculate measurements" })
    .click();
  await expect(movement.getByTestId("measurement-status")).toContainText(
    "completed",
    { timeout: 20000 },
  );
  await movement.getByRole("button", { name: "Detect cycles" }).click();
  await expect(movement.getByTestId("event-status")).toContainText(
    "completed",
    { timeout: 20000 },
  );
  await page.screenshot({
    path: info.outputPath("temporal-reviewed-measurements.png"),
  });
  await panel
    .getByRole("combobox", { name: "Operation", exact: true })
    .selectOption("evaluation");
  await panel.getByLabel("Frozen temporal dataset").selectOption(dataset.id);
  await panel
    .getByRole("combobox", { name: "Temporal checkpoint", exact: true })
    .selectOption(modelId);
  const evaluationSettings = panel.getByText("Evaluation settings", {
    exact: true,
  });
  await evaluationSettings.click();
  await panel.getByLabel("Compare anatomical cycles").check();
  await panel
    .getByRole("combobox", { name: "Event landmark A", exact: true })
    .selectOption("jaw-a");
  await panel
    .getByRole("combobox", { name: "Event landmark B", exact: true })
    .selectOption("jaw-b");
  await panel.getByLabel("Event opening threshold (px)").fill("12");
  await panel.getByLabel("Event closing threshold (px)").fill("9");
  const evaluation = await run("Compare frame and temporal predictions");
  expect(evaluation.result.metrics.anatomical_events).toBeTruthy();
  await expect(panel.getByText("Temporal result and provenance")).toBeVisible();
  await page.screenshot({
    path: info.outputPath("temporal-scientific-evaluation.png"),
  });
});
