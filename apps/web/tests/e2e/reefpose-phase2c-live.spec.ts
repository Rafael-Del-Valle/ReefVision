import { expect, test } from "@playwright/test";

const enabled = process.env.REEFPOSE_PHASE2C_LIVE_ACCEPTANCE === "1";
const apiBase = "http://127.0.0.1:8000/api/v1";

test.describe("ReefPose Phase 2C live GUI", () => {
  test.skip(
    !enabled,
    "Set REEFPOSE_PHASE2C_LIVE_ACCEPTANCE=1 with the isolated API and Vite UI running.",
  );

  test("designs, revises, and annotates a stable-ID custom skeleton", async ({
    page,
  }) => {
    test.setTimeout(120_000);
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
    await page.getByRole("tab", { name: "Video & tracking" }).click();

    const templateName = `Phase 2C jellyfish ${Date.now()}`;
    const designer = page.getByTestId("anatomy-skeleton-designer");
    await expect(designer).toBeVisible();
    await designer.getByLabel("Template name").fill(templateName);
    await designer.getByRole("button", { name: "Add landmark" }).click();
    await designer.getByRole("button", { name: "Add landmark" }).click();
    await designer.getByRole("button", { name: "Add landmark" }).click();

    const ids = designer.getByLabel("Stable landmark ID");
    const names = designer.getByLabel("Anatomical name");
    await ids.nth(0).fill("bell_center");
    await names.nth(0).fill("Bell center");
    await ids.nth(1).fill("tentacle_left");
    await names.nth(1).fill("Tentacle");
    await ids.nth(2).fill("tentacle_right");
    await names.nth(2).fill("Tentacle");

    const repeatGroups = designer.getByLabel("Repeated structure");
    const repeatIndices = designer.getByLabel("Repeat index");
    await repeatGroups.nth(1).fill("tentacle");
    await repeatIndices.nth(1).fill("0");
    await repeatGroups.nth(2).fill("tentacle");
    await repeatIndices.nth(2).fill("1");
    const symmetry = designer.getByLabel("Symmetric partner");
    await symmetry.nth(1).selectOption("tentacle_right");
    await symmetry.nth(2).selectOption("tentacle_left");
    await designer.getByLabel("Connection start").selectOption("bell_center");
    await designer.getByLabel("Connection end").selectOption("tentacle_left");
    await designer.getByRole("button", { name: "Add connection" }).click();
    await expect(
      designer.getByTestId("anatomy-edge-bell_center-tentacle_left"),
    ).toBeVisible();

    const createdResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/projects\/[^/]+\/pose-schemas$/.test(
          new URL(response.url()).pathname,
        ),
    );
    await designer.getByRole("button", { name: "Save template" }).click();
    const created = (await (await createdResponse).json()) as {
      id: string;
      revision: number;
      content_hash: string;
    };
    await expect(designer.getByRole("status")).toHaveText("Saved revision 1");

    await names.nth(0).fill("Bell centroid");
    const revisedResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith(
          `/pose-schemas/${created.id}/revisions`,
        ),
    );
    await designer.getByRole("button", { name: "Save new revision" }).click();
    const revised = (await (await revisedResponse).json()) as {
      id: string;
      revision: number;
      content_hash: string;
    };
    expect(revised.revision).toBe(2);
    await expect(designer.getByRole("status")).toHaveText("Saved revision 2");
    await designer.getByText("Revision history").click();
    await expect(designer.getByText(/Revision 1 · 3 landmarks/)).toBeVisible();
    await expect(designer.getByText(/Revision 2 · 3 landmarks/)).toBeVisible();

    const projects = (await (
      await page.request.get(`${apiBase}/projects`)
    ).json()) as Array<{
      id: string;
      name: string;
      label_classes: Array<{ id: string }>;
    }>;
    const project = projects.find(
      (item) => item.name === "Phase 9 verified pose dataset",
    );
    expect(project).toBeTruthy();
    const videos = (await (
      await page.request.get(`${apiBase}/projects/${project!.id}/videos`)
    ).json()) as Array<{ id: string }>;
    const videoId = videos[0].id;
    const manualTrackResponse = await page.request.post(
      `${apiBase}/videos/${videoId}/tracks`,
      {
        data: {
          label_class_id: project!.label_classes[0].id,
          geometry_kind: "bbox",
          keyframes: [{ frame: 0, bbox: [20, 20, 220, 180] }],
          interpolation: "linear",
          status: "draft",
        },
      },
    );
    expect(manualTrackResponse.ok()).toBeTruthy();
    const manualTrack = (await manualTrackResponse.json()) as { id: string };

    await page.reload();
    await page
      .getByRole("button", { name: "Open Phase 9 verified pose dataset" })
      .click();
    await page.getByRole("tab", { name: "Video & automation" }).click();
    await page.getByRole("tab", { name: "Video & tracking" }).click();
    await page.getByRole("button", { name: "Extract review frames" }).click();
    await expect
      .poll(
        async () => {
          const refreshed = (await (
            await page.request.get(`${apiBase}/projects/${project!.id}/videos`)
          ).json()) as Array<{
            id: string;
            frame_directory_path: string | null;
          }>;
          return refreshed.find((item) => item.id === videoId)
            ?.frame_directory_path;
        },
        { timeout: 30_000 },
      )
      .toBeTruthy();
    await page
      .getByTestId("anatomy-skeleton-designer")
      .getByLabel("Saved template")
      .selectOption(created.id);
    await page.getByLabel("Existing track").selectOption(manualTrack.id);
    await page.getByLabel("Enable source-coordinate overlay").check();

    const poseStage = page.getByTestId("pose-stage");
    await expect(poseStage).toBeVisible();
    await page.getByRole("button", { name: "Place Bell centroid" }).click();
    await poseStage.click({ position: { x: 250, y: 180 } });
    await page.getByRole("button", { name: "Place Tentacle" }).click();
    await poseStage.click({ position: { x: 180, y: 330 } });
    await poseStage.click({ position: { x: 340, y: 330 } });

    const savedResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname.endsWith(
          `/video-tracks/${manualTrack.id}`,
        ),
    );
    await page.getByRole("button", { name: "Save pose" }).click();
    const saved = (await (await savedResponse).json()) as {
      metadata_json: {
        pose_landmark_schema: {
          schema_id: string;
          schema_revision: number;
          content_hash: string;
        };
      };
      keyframes_json: Array<{
        pose_observations: Array<{ landmark_id?: string }>;
      }>;
    };
    expect(saved.metadata_json.pose_landmark_schema).toMatchObject({
      schema_id: created.id,
      schema_revision: revised.revision,
      content_hash: revised.content_hash,
    });
    expect(
      saved.keyframes_json[0].pose_observations.map((item) => item.landmark_id),
    ).toEqual(["bell_center", "tentacle_left", "tentacle_right"]);
    await expect(
      page.getByRole("status").filter({ hasText: /Saved/ }),
    ).toBeVisible();
  });
});
