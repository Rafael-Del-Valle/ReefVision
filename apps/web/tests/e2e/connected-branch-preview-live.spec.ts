import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

import type { SkeletonAnalysisRevision } from "../../src/features/annotation-editor/skeletonAnalysisApi";

// An 80×60 synthetic image. The annotation below supplies the colony geometry.
const image = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
  "base64",
);

test("draws a connected branch in the mask editor and keeps it out of verified records", async ({
  page,
}) => {
  const api = process.env.REEFVISION_BRANCH_PREVIEW_TEST_API;
  const web = process.env.REEFVISION_BRANCH_PREVIEW_TEST_WEB;
  test.skip(!api || !web, "Requires an isolated SQLite API and Vite.");

  const projectName = `Connected branch preview ${randomUUID()}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name: projectName },
  });
  expect(created.status(), await created.text()).toBe(201);
  const project = (await created.json()) as { id: string };
  const createdClass = await page.request.post(
    `${api}/projects/${project.id}/classes`,
    {
      data: {
        class_index: 0,
        name: "Synthetic colony",
        display_color: "#E76F51",
      },
    },
  );
  expect(createdClass.status(), await createdClass.text()).toBe(201);
  const labelClass = (await createdClass.json()) as { id: string };
  const imported = await page.request.post(
    `${api}/projects/${project.id}/imports/images`,
    {
      multipart: {
        files: { name: "coral.png", mimeType: "image/png", buffer: image },
        relative_paths: "fixture/coral.png",
      },
    },
  );
  expect(imported.status(), await imported.text()).toBe(200);
  const { successful } = (await imported.json()) as {
    successful: { image_id: string }[];
  };
  expect(successful).toHaveLength(1);
  const maskId = randomUUID();
  const annotated = await page.request.put(
    `${api}/images/${successful[0].image_id}/annotations`,
    {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [],
        mask_annotations: [
          {
            id: maskId,
            label_class_id: labelClass.id,
            geometry_kind: "polygon",
            points: [
              { x: 10, y: 20 },
              { x: 60, y: 20 },
              { x: 60, y: 30 },
              { x: 10, y: 30 },
            ],
          },
        ],
      },
    },
  );
  expect(annotated.status(), await annotated.text()).toBe(200);
  const calibrated = await page.request.put(
    `${api}/images/${successful[0].image_id}/measurement-calibration`,
    {
      data: {
        distance_per_pixel: 0.25,
        source: "manual_scale_bar",
        unit: "mm",
      },
    },
  );
  expect(calibrated.status(), await calibrated.text()).toBe(200);
  const recorded = await page.request.post(
    `${api}/mask-annotations/${maskId}/skeleton-analyses`,
    { data: {} },
  );
  expect(recorded.ok(), await recorded.text()).toBeTruthy();
  const analysis = (await recorded.json()) as SkeletonAnalysisRevision;
  const pixels = analysis.result.final_skeleton_pixels;
  const junction = pixels[Math.floor(pixels.length / 2)];
  const tip = { x: junction.x, y: junction.y - 4 };

  const { version } = JSON.parse(await readFile("package.json", "utf8")) as {
    version: string;
  };
  await page.addInitScript((appVersion) => {
    localStorage.setItem(
      `reefvision.onboarding.dismissed.${appVersion}`,
      "true",
    );
  }, version);
  await page.goto(web!);
  await page.getByRole("button", { name: new RegExp(projectName) }).click();
  await page.getByRole("button", { name: "Annotate" }).click();
  await page.getByTestId("open-polygon-tool").click();
  await page.getByTestId("move-polygon-nodes").click();
  await page.locator(`g[data-mask-id="${maskId}"] polygon`).click();
  const panel = page.getByTestId("skeleton-analysis-panel");
  await panel.getByRole("button", { name: "Draw branch" }).click();
  const overlay = page.getByTestId("skeleton-overlay");
  const bounds = await overlay.boundingBox();
  if (!bounds) throw new Error("Skeleton canvas is not visible");
  for (const point of [junction, tip]) {
    await page.mouse.click(
      bounds.x + ((point.x + 0.5) * bounds.width) / 80,
      bounds.y + ((point.y + 0.5) * bounds.height) / 60,
    );
  }
  const previewButton = panel.getByRole("button", { name: "Preview branch" });
  await expect(previewButton).toBeEnabled();
  await panel.getByRole("button", { name: "Undo waypoint" }).click();
  await expect(previewButton).toBeDisabled();
  await panel.getByRole("button", { name: "Redo waypoint" }).click();

  const previewResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/${analysis.id}/branch-edits/preview`),
  );
  await previewButton.click();
  const preview = await previewResponse;
  expect(preview.ok(), await preview.text()).toBeTruthy();
  expect(await preview.json()).toMatchObject({
    added_length_pixels: 4,
    calibration: {
      added_length: 1,
      calibration_sha256: analysis.calibration_sha256,
      method: "scalar_distance_per_pixel",
      unit: "mm",
    },
    persistent_change_applied: false,
    review_gate: "scientist_review_required",
  });
  await expect(panel.getByText("Scientist review required")).toBeVisible();
  await expect(panel.getByText(/Image-scale calibration/)).toBeVisible();
  await expect(panel.getByText("4.00 px | 1.0000 mm").first()).toBeVisible();
  await expect(
    panel.getByText(/1 existing segment splits into 2/),
  ).toBeVisible();
  await panel.getByText("Scientific review").click();
  await expect(panel.getByRole("button", { name: "Approve" })).toBeDisabled();
  await panel.getByRole("button", { name: "Discard branch draft" }).click();
  await expect(panel.getByText("Scientist review required")).toHaveCount(0);
  const unchanged = await page.request.get(
    `${api}/skeleton-analyses/${analysis.id}`,
  );
  expect(await unchanged.json()).toEqual(analysis);
});
