import { expect, test } from "@playwright/test";

const enabled = process.env.REEFPOSE_LIVE_ACCEPTANCE === "1";

test.describe("ReefPose Phase 2B live GUI", () => {
  test.skip(
    !enabled,
    "Set REEFPOSE_LIVE_ACCEPTANCE=1 with the isolated API and Vite UI running.",
  );

  test("trains, registers, runs, and reviews a native ReefPose model", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "reefvision.onboarding.dismissed.1.0.3",
        "true",
      );
    });
    await page.goto("http://127.0.0.1:5173/");

    await page
      .getByRole("button", { name: "Open Phase 9 verified pose dataset" })
      .click();
    await page.getByRole("tab", { name: "Video & automation" }).click();
    await page.getByRole("tab", { name: "Workflow builder" }).click();

    await page.getByLabel("Template").selectOption("reefpose-native-training");
    const datasetSelect = page
      .getByRole("heading", { name: "Verified pose training data" })
      .locator("..")
      .getByRole("combobox");
    const datasetId = await datasetSelect
      .locator("option")
      .filter({ hasText: "Phase 10B pose training" })
      .getAttribute("value");
    expect(datasetId).toBeTruthy();
    await datasetSelect.selectOption(datasetId!);

    const trainNode = page.locator('[data-node-id="train"]');
    await trainNode.getByRole("button", { name: "Configure" }).click();
    await expect(page.getByLabel("Training provider")).toHaveValue("reefpose");
    await expect(
      page.getByText(/CUDA ready: NVIDIA GeForce RTX 3090/),
    ).toBeVisible();
    await page.getByLabel("Device").selectOption("cuda");
    await page.getByLabel("Precision").selectOption("amp");
    await page.getByLabel("Epochs").fill("1");
    await page.getByLabel("Batch size").fill("1");
    await page.getByLabel("Input height").fill("64");
    await page.getByLabel("Input width").fill("64");

    const queuedWorkflow = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/projects\/[^/]+\/workflow-runs$/.test(
          new URL(response.url()).pathname,
        ),
    );
    await page.getByRole("button", { name: "Save & run" }).click();
    const workflowRunId = String((await (await queuedWorkflow).json()).id);
    const runInspection = page
      .getByRole("heading", { name: "Run inspection" })
      .locator("..");
    await expect(runInspection.getByText(/Status:/)).toHaveText(
      "Status: succeeded",
      { timeout: 120_000 },
    );
    const runDetail = await (
      await page.request.get(
        `http://127.0.0.1:8000/api/v1/workflow-runs/${workflowRunId}`,
      )
    ).json();
    const modelReference = runDetail.artifacts.find(
      (artifact: { data_type: string }) =>
        artifact.data_type === "model_reference",
    ).payload_json as { model_id: string; project_id: string };
    const modelHub = await (
      await page.request.get(
        `http://127.0.0.1:8000/api/v1/projects/${modelReference.project_id}/model-hub/bootstrap`,
      )
    ).json();
    const registeredModel = modelHub.models.find(
      (model: { id: string }) => model.id === modelReference.model_id,
    ) as { display_name: string };
    expect(registeredModel).toBeTruthy();

    await page.getByRole("tab", { name: "Models & AI" }).click();
    await page.getByRole("tab", { name: "Model Hub" }).click();
    const modelCard = page
      .getByRole("heading", {
        name: registeredModel.display_name,
        exact: true,
      })
      .last()
      .locator("xpath=ancestor::article");
    const reefPoseDetails = modelCard.getByText(
      "ReefPose anatomy and provenance",
    );
    await expect(reefPoseDetails).toBeVisible();
    await reefPoseDetails.click();
    await expect(modelCard.getByText(/2 anatomical keypoints/)).toBeVisible();
    await modelCard
      .getByRole("button", { name: "Use in Pose Tracking" })
      .click();

    await expect(page.getByTestId("video-tracking-workspace")).toBeVisible();
    await expect(page.getByLabel("Tracking model")).toHaveValue(/.+/);
    const automatedTracking = page
      .getByRole("heading", {
        name: "Detection / segmentation / hybrid video tracking",
      })
      .locator("..");
    await automatedTracking.getByLabel("Detection confidence").fill("0");
    await automatedTracking.getByLabel("Device").selectOption("0");
    const runPoseButton = automatedTracking.getByRole("button", {
      name: /Run pose/,
    });
    await expect(runPoseButton).toBeEnabled();
    const trackingResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/videos\/[^/]+\/tracking-jobs$/.test(
          new URL(response.url()).pathname,
        ),
    );
    await runPoseButton.click();
    const queuedTracking = await trackingResponse;
    expect(queuedTracking.request().postDataJSON().model_id).toBe(
      modelReference.model_id,
    );
    const trackingJobId = String((await queuedTracking.json()).id);
    await expect(
      automatedTracking
        .getByRole("row")
        .filter({ hasText: trackingJobId.slice(0, 8) }),
    ).toContainText("completed", { timeout: 120_000 });

    const trackingVideoId = new URL(queuedTracking.url()).pathname.split(
      "/",
    )[4];
    const videoTracks = await (
      await page.request.get(
        `http://127.0.0.1:8000/api/v1/videos/${trackingVideoId}/tracks`,
      )
    ).json();
    const generatedTrack = videoTracks.find(
      (track: { source_job_id: string | null }) =>
        track.source_job_id === trackingJobId,
    ) as { id: string };
    expect(generatedTrack).toBeTruthy();
    const trackSelect = page.getByLabel("Existing track");
    await trackSelect.selectOption(generatedTrack.id);
    await page.getByLabel("Enable source-coordinate overlay").check();
    await expect(
      page.getByText("Pose landmarks on this frame: 2"),
    ).toBeVisible();
    await expect(page.getByText("Landmark schema: tentacle × 2")).toBeVisible();
    await expect(page.getByLabel("Status")).toHaveValue("machine_generated");
  });
});
