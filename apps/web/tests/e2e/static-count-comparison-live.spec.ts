import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

test.use({ viewport: { width: 1180, height: 820 }, deviceScaleFactor: 1.25 });

test("runs a registered detector against reviewed counts and reopens the saved figure source", async ({
  page,
}, info) => {
  const web = process.env.REEFVISION_STATIC_TEST_WEB;
  const api = process.env.REEFVISION_STATIC_TEST_API;
  const checkpoint = process.env.REEFVISION_STATIC_TEST_CHECKPOINT;
  test.skip(
    !web || !api || !checkpoint,
    "Requires an isolated app and a trusted synthetic local detector",
  );
  test.setTimeout(90_000);
  const name = `Synthetic count comparison ${randomUUID().slice(0, 8)}`;
  const project = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(project.status(), await project.text()).toBe(201);
  const projectId = (await project.json()).id as string;
  const base = `${api}/projects/${projectId}`;
  const registered = await page.request.post(`${base}/models/register`, {
    multipart: {
      file: {
        name: "synthetic-counts.pt",
        mimeType: "application/octet-stream",
        buffer: await readFile(checkpoint!),
      },
      purpose: "detector",
      provider_name: "ultralytics",
      display_name: "Synthetic local detector",
    },
  });
  expect(registered.ok(), await registered.text()).toBeTruthy();
  const model = await registered.json();
  const classId = Object.values(model.class_map_json.mapping)[0];
  const imageName = "reviewed-source.png";
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMCSDcQxmfFucD5Zga59LicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6XzwFAMWopKwAAAABJRU5ErkJggg==",
    "base64",
  );
  const upload = await page.request.post(`${base}/imports/images`, {
    multipart: {
      files: { name: imageName, mimeType: "image/png", buffer: png },
    },
  });
  expect(upload.ok(), await upload.text()).toBeTruthy();
  const imported = await upload.json();
  expect(imported.successful, JSON.stringify(imported)).toHaveLength(1);
  const imageId = imported.successful[0].image_id;
  const review = await page.request.put(
    `${api}/images/${imageId}/annotations`,
    {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [
          {
            id: randomUUID(),
            label_class_id: classId,
            x_min: 4,
            y_min: 5,
            x_max: 20,
            y_max: 24,
          },
        ],
      },
    },
  );
  expect(review.ok(), await review.text()).toBeTruthy();
  const group = await page.request.patch(`${api}/images/${imageId}`, {
    data: { group_key: "Synthetic tank A" },
  });
  expect(group.ok(), await group.text()).toBeTruthy();
  const dataset = await page.request.post(`${base}/dataset-versions`, {
    data: {
      name: "Reviewed comparison reference",
      eligible_annotation_statuses: ["reviewed"],
      split_method: "manual",
      manual_assignments: [{ image_id: imageId, split: "test" }],
    },
  });
  expect(dataset.status(), await dataset.text()).toBe(201);
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.3.0", "true"),
  );
  const openHub = async () => {
    await page.goto(web!);
    const open = page.getByRole("button", {
      name: `Open ${name}`,
      exact: true,
    });
    await open.click();
    await page.getByRole("tab", { name: "Models & AI", exact: true }).click();
    await page.getByRole("tab", { name: "Model Hub", exact: true }).click();
  };
  await openHub();
  const summary = page.getByText("Static-image human–model comparison", {
    exact: true,
  });
  const panel = summary.locator("..");
  await summary.click();
  await panel
    .getByLabel("Reviewed reference dataset")
    .selectOption((await dataset.json()).id);
  await panel.getByLabel("Primary detector").selectOption(model.id);
  await panel
    .getByText("Inference and agreement settings", { exact: true })
    .click();
  const device = process.env.REEFVISION_STATIC_TEST_DEVICE ?? "cpu";
  await panel.getByLabel("Device").selectOption(device);
  const queued = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${base}/static-comparisons`,
  );
  await panel.getByRole("button", { name: "Run count comparison" }).click();
  const started = await queued;
  expect(started.status(), await started.text()).toBe(202);
  const comparisonId = (await started.json()).id as string;
  const result = page.getByRole("region", {
    name: "Static count comparison result",
  });
  await expect(
    result.getByText("Exploratory · independence unverified").first(),
  ).toBeVisible({ timeout: 40_000 });
  await expect(
    result.getByRole("img", { name: /Reference against estimate/ }),
  ).toBeVisible();
  const stored = await (
    await page.request.get(`${base}/static-comparisons/${comparisonId}`)
  ).json();
  expect(stored.snapshot.results[0].images[0].status).toBe("inferred");
  expect(stored.snapshot.results[0].images[0].counts[0].reference).toBe(1);
  await result
    .getByText("Image counts and exclusions", { exact: true })
    .click();
  await result.getByRole("button", { name: imageName }).click();
  await expect(
    page.getByText("Static comparison source", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to count comparison" }).click();
  await expect(result).toBeVisible();
  await result.getByText("Publish count figure", { exact: true }).click();
  await result.getByLabel("Figure title").fill("Synthetic count agreement");
  await result.getByRole("button", { name: "Save publication figure" }).click();
  const svgPath = await result
    .getByRole("link", { name: "Open figure SVG" })
    .getAttribute("href");
  expect(await (await page.request.get(svgPath!)).text()).toContain(
    "Synthetic count agreement",
  );
  const csvPath = await result
    .getByRole("link", { name: "Download count CSV" })
    .getAttribute("href");
  expect(await (await page.request.get(csvPath!)).text()).toContain(imageName);
  await page.screenshot({
    path: info.outputPath("static-count-agreement.png"),
  });
  await openHub();
  await expect(result).toBeVisible();
  expect(
    await result
      .getByRole("link", { name: "Download evidence JSON" })
      .getAttribute("href"),
  ).toContain(comparisonId);
});
