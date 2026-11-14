import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

const image = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
  "base64",
);

test("reviews two dated coral graphs and saves and exports projected branch growth", async ({
  page,
}) => {
  const api = process.env.REEFVISION_BRANCH_PREVIEW_TEST_API;
  const web = process.env.REEFVISION_BRANCH_PREVIEW_TEST_WEB;
  test.skip(!api || !web, "Requires an isolated SQLite API and Vite.");
  const name = `Synthetic dated coral ${randomUUID()}`;
  const all = await page.request.post(`${api}/projects`, { data: { name } });
  expect(all.status(), await all.text()).toBe(201);
  const project = await all.json();
  const root = `${api}/projects/${project.id}`;
  const category = await page.request.post(`${root}/classes`, {
    data: {
      class_index: 0,
      name: "Synthetic colony",
      display_color: "#D48E33",
    },
  });
  expect(category.status(), await category.text()).toBe(201);
  const label = (await category.json()).id;
  const colony = await page.request.post(`${root}/ecology/organisms`, {
    data: {
      organism_key: "synthetic-colony",
      kind: "colony",
      reason: "Known fixture identity",
    },
  });
  expect(colony.status(), await colony.text()).toBe(201);
  const observationIds: string[] = [];
  for (const offset of [0, 4]) {
    const basename = `coral-date-${offset}.png`;
    // The fixture records distinct acquisition assets and retains its original bytes.
    const imported = await page.request.post(`${root}/imports/images`, {
      multipart: {
        files: {
          name: basename,
          mimeType: "image/png",
          buffer: Buffer.concat([image, Buffer.from([offset])]),
        },
        relative_paths: basename,
      },
    });
    expect(imported.status(), await imported.text()).toBe(200);
    const importedAssets = await imported.json();
    expect(
      importedAssets.successful,
      JSON.stringify(importedAssets),
    ).toHaveLength(1);
    const fid = importedAssets.successful[0].image_id;
    const maskId = randomUUID();
    const annotation = await page.request.put(
      `${api}/images/${fid}/annotations`,
      {
        data: {
          base_revision: 0,
          annotation_status: "reviewed",
          annotations: [],
          mask_annotations: [
            {
              id: maskId,
              label_class_id: label,
              geometry_kind: "polygon",
              points: [
                { x: 10, y: 20 },
                { x: 60 + offset, y: 20 },
                { x: 60 + offset, y: 30 },
                { x: 10, y: 30 },
              ],
            },
          ],
        },
      },
    );
    expect(annotation.ok(), await annotation.text()).toBeTruthy();
    const calibration = await page.request.put(
      `${api}/images/${fid}/measurement-calibration`,
      {
        data: {
          distance_per_pixel: 0.25,
          source: "manual_scale_bar",
          unit: "mm",
        },
      },
    );
    expect(calibration.ok(), await calibration.text()).toBeTruthy();
    const saved = await page.request.post(
      `${api}/mask-annotations/${maskId}/skeleton-analyses`,
      { data: {} },
    );
    expect(saved.ok(), await saved.text()).toBeTruthy();

    const { version } = JSON.parse(await readFile("package.json", "utf8"));
    await page.addInitScript(
      (v) =>
        localStorage.setItem(`reefvision.onboarding.dismissed.${v}`, "true"),
      version,
    );
    await page.goto(web!);
    await page.getByRole("button", { name: "Open " + name }).click();
    await page
      .getByRole("article", { name: new RegExp(basename) })
      .getByRole("button", { name: "Annotate" })
      .click();
    await page.getByTestId("open-polygon-tool").click();
    await page.getByTestId("move-polygon-nodes").click();
    await page.locator(`g[data-mask-id="${maskId}"] polygon`).click();
    const review = page.getByRole("region", { name: "Coral graph review" });
    await review
      .getByLabel("Registered colony")
      .selectOption((await colony.json()).id);
    await review
      .getByLabel("Observation time (UTC)")
      .fill(offset === 0 ? "2026-01-01T10:00" : "2026-01-03T10:00");
    await review
      .getByLabel("Graph reviewer")
      .fill("Synthetic fixture scientist");
    await review
      .getByLabel("Graph review reason")
      .fill("Verified the source colony and traced centerline");
    const savedReview = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith("/ecology/coral-graphs"),
    );
    await review.getByRole("button", { name: "Accept graph review" }).click();
    const response = await savedReview;
    expect(response.status(), await response.text()).toBe(201);
    observationIds.push((await response.json()).id);
    await expect(
      review.getByText(/Current reviewed graph revision/),
    ).toBeVisible();
    if (process.env.REEFVISION_BRANCH_EVIDENCE_DIR && offset === 0) {
      await page.screenshot({
        path: join(
          process.env.REEFVISION_BRANCH_EVIDENCE_DIR,
          "reviewed-coral-graph.png",
        ),
      });
    }
  }
  await page.goto(web!);
  await page.getByRole("button", { name: "Open " + name }).click();
  await page.getByRole("tab", { name: "Organisms & ecology" }).click();
  await page.getByRole("button", { name: "Coral branch growth" }).click();
  const panel = page.getByRole("region", { name: "Reviewed coral growth" });
  await panel
    .getByLabel("Earlier coral observation")
    .selectOption(observationIds[0]);
  await panel
    .getByLabel("Later coral observation")
    .selectOption(observationIds[1]);
  await panel.getByRole("button", { name: "Add correspondence row" }).click();
  await panel.getByLabel("Earlier branches").selectOption({ index: 0 });
  await panel.getByLabel("Later branches").selectOption({ index: 0 });
  await panel
    .getByLabel("Match rationale")
    .fill("Same stem and visible terminal endpoints");
  await panel
    .getByLabel("Correspondence reviewer")
    .fill("Synthetic fixture scientist");
  await panel
    .getByLabel("Correspondence review reason")
    .fill("Matched traced stem across the two known dates");
  await panel
    .getByRole("button", { name: "Save reviewed correspondence" })
    .click();
  await panel
    .getByRole("button", { name: "Calculate and save growth" })
    .click();
  const table = panel.getByRole("table", {
    name: "Projected branch length changes",
  });
  await expect(
    table.getByRole("row").filter({ hasText: "Unique-edge colony total" }),
  ).toContainText("1.000");
  await expect(
    table.getByRole("row").filter({ hasText: "Unique-edge colony total" }),
  ).toContainText("0.500");
  await expect(panel.getByRole("link", { name: "Growth CSV" })).toBeVisible();
  const csv = await page.request.get(
    (await panel
      .getByRole("link", { name: "Growth CSV" })
      .getAttribute("href"))!,
  );
  expect(csv.ok()).toBeTruthy();
  expect(await csv.text()).toContain("absolute_change");
  if (process.env.REEFVISION_BRANCH_EVIDENCE_DIR) {
    await page.screenshot({
      path: join(
        process.env.REEFVISION_BRANCH_EVIDENCE_DIR,
        "coral-growth.png",
      ),
      fullPage: true,
    });
  }
  await page.reload();
  await page.getByRole("button", { name: "Open " + name }).click();
  await page.getByRole("tab", { name: "Organisms & ecology" }).click();
  await page.getByRole("button", { name: "Coral branch growth" }).click();
  await expect(page.getByRole("link", { name: "Growth JSON" })).toBeVisible();
});
