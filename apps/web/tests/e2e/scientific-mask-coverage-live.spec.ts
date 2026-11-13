import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("saves and reloads projected polygon coverage against the local API", async ({
  page,
}) => {
  test.skip(
    process.env.REEFVISION_SCIENCE_LIVE_ACCEPTANCE !== "1",
    "Requires an isolated ReefVision API and frontend.",
  );
  const api = "http://127.0.0.1:8000/api/v1";
  const name = `Synthetic ROI ${randomUUID()}`;
  const project = await page.request.post(`${api}/projects`, {
    data: { name, template: "blank" },
  });
  expect(project.status(), await project.text()).toBe(201);
  const projectId = (await project.json()).id;
  const base = `${api}/projects/${projectId}`;
  const label = await page.request.post(`${base}/classes`, {
    data: {
      class_index: 0,
      name: "Synthetic target",
      display_color: "#66aa88",
    },
  });
  expect(label.status(), await label.text()).toBe(201);
  const labelId = (await label.json()).id;

  await page.goto("http://127.0.0.1:5173/");
  const png = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 10;
    canvas.height = 10;
    return canvas.toDataURL("image/png").split(",")[1];
  });
  const imported = await page.request.post(`${base}/imports/images`, {
    multipart: {
      files: {
        name: "synthetic.png",
        mimeType: "image/png",
        buffer: Buffer.from(png, "base64"),
      },
      relative_paths: "synthetic.png",
    },
  });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const imageId = (await imported.json()).successful[0].image_id;
  const saved = await page.request.put(`${api}/images/${imageId}/annotations`, {
    data: {
      base_revision: 0,
      annotation_status: "reviewed",
      annotations: [],
      mask_annotations: [
        {
          id: randomUUID(),
          label_class_id: labelId,
          geometry_kind: "polygon",
          points: [
            { x: 0, y: 0 },
            { x: 2, y: 0 },
            { x: 2, y: 1 },
            { x: 0, y: 1 },
          ],
        },
      ],
    },
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  const calibration = await page.request.put(
    `${api}/images/${imageId}/measurement-calibration`,
    {
      data: {
        unit: "cm",
        distance_per_pixel: 10,
        perspective_homography: [
          [1, 0, 0],
          [0, 1, 0],
          [1, 0, 1],
        ],
      },
    },
  );
  expect(calibration.ok(), await calibration.text()).toBeTruthy();

  await page.evaluate(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.1.0", "true"),
  );
  await page.reload();
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await page.getByRole("tab", { name: "Computed Metrics" }).click();
  await page
    .getByRole("button", { name: "Open verified mask coverage" })
    .click();
  const coverage = page.getByRole("region", {
    name: "Verified mask area and coverage",
  });
  await coverage.getByLabel("Coverage name").fill("Calibrated transect");
  await coverage.getByLabel("Saved ROI polygons (JSON)").fill(
    JSON.stringify([
      {
        image_id: imageId,
        points: [
          [0, 0],
          [2, 0],
          [2, 2],
          [0, 2],
        ],
      },
    ]),
  );
  await coverage
    .getByLabel("Use reference-plane homography for physical values")
    .check();
  await coverage
    .getByRole("button", { name: "Save coverage definition" })
    .click();
  await expect(
    coverage.getByRole("option", { name: "Calibrated transect" }),
  ).toBeAttached();
  await coverage.getByLabel("Coverage image IDs").fill(imageId);
  await coverage.getByRole("button", { name: "Preview mask coverage" }).click();
  await expect(coverage.getByText("66.666667%").first()).toBeVisible();
  await expect(coverage.getByText("0.9375 cm²", { exact: true })).toBeVisible();
  await coverage
    .getByRole("button", { name: "Save immutable coverage" })
    .click();
  await expect(coverage.getByText("Evidence current")).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await page.getByRole("tab", { name: "Computed Metrics" }).click();
  await page
    .getByRole("button", { name: "Open verified mask coverage" })
    .click();
  await expect(coverage.getByText("Evidence current")).toBeVisible();
  const csv = await page.request.get(
    `${base}/computed-mask-coverage-results.csv`,
  );
  expect(csv.ok(), await csv.text()).toBeTruthy();
  expect(await csv.text()).toContain("projective_reference_plane");

  await page.getByRole("tab", { name: "Scientific Heatmaps" }).click();
  await page.getByLabel("Show scalar-calibrated density").check();
  await expect(page.getByText(/Physical density unavailable/)).toBeVisible();
  const scalar = await page.request.put(
    `${api}/images/${imageId}/measurement-calibration`,
    { data: { unit: "cm", distance_per_pixel: 0.5 } },
  );
  expect(scalar.ok(), await scalar.text()).toBeTruthy();
  await page.reload();
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await page.getByRole("tab", { name: "Scientific Heatmaps" }).click();
  await page.getByLabel("Show scalar-calibrated density").check();
  await expect(
    page.getByText(/Calibration uncertainty is unquantified/),
  ).toBeVisible();
  await expect(
    page.getByText(/Maximum density: .* objects\/cm2/).nth(1),
  ).toBeVisible();
});
