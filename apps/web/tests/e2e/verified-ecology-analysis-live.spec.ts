import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

const image = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
  "base64",
);

test("reviews a surveyed sample, saves abundance, and reloads the historical result", async ({
  page,
}) => {
  const api = process.env.REEFVISION_ECOLOGY_TEST_API;
  const web = process.env.REEFVISION_ECOLOGY_TEST_WEB;
  test.skip(!api || !web, "Requires an isolated ReefVision API and Vite.");
  const projectName = `Survey ${randomUUID()}`;
  const projectResponse = await page.request.post(`${api}/projects`, {
    data: { name: projectName },
  });
  expect(projectResponse.ok(), await projectResponse.text()).toBeTruthy();
  const { id: projectId } = (await projectResponse.json()) as { id: string };
  const labelResponse = await page.request.post(
    `${api}/projects/${projectId}/classes`,
    {
      data: {
        class_index: 0,
        name: "Synthetic polyp",
        display_color: "#E76F51",
      },
    },
  );
  expect(labelResponse.ok(), await labelResponse.text()).toBeTruthy();
  const { id: labelId } = (await labelResponse.json()) as { id: string };
  const imported = await page.request.post(
    `${api}/projects/${projectId}/imports/images`,
    {
      multipart: {
        files: { name: "quadrat.png", mimeType: "image/png", buffer: image },
      },
    },
  );
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const { successful } = (await imported.json()) as {
    successful: { image_id: string }[];
  };
  expect(successful).toHaveLength(1);
  const response = await page.request.put(
    `${api}/images/${successful[0].image_id}/annotations`,
    {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [
          {
            id: randomUUID(),
            label_class_id: labelId,
            x_min: 0,
            y_min: 0,
            x_max: 1,
            y_max: 1,
          },
        ],
      },
    },
  );
  expect(response.ok(), await response.text()).toBeTruthy();
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
  await page
    .getByRole("tab", { name: "Organisms & ecology", exact: true })
    .click();
  await page.getByRole("button", { name: "Reviewed analyses" }).click();
  const panel = page.getByRole("region", {
    name: "Reviewed ecological analyses",
  });
  await panel
    .getByRole("combobox", { name: "Analysis", exact: true })
    .selectOption("abundance");
  await panel
    .getByRole("combobox", { name: "Counted class" })
    .selectOption({ label: "Synthetic polyp" });
  await panel
    .getByRole("combobox", { name: "Reviewed image" })
    .selectOption({ label: "quadrat.png" });
  await panel.getByLabel("Sample ID").fill("QUAD-1");
  await panel.getByLabel("Experimental unit ID").fill("SITE-1");
  await panel
    .getByLabel("Survey time with offset")
    .fill("2026-11-14T12:00:00Z");
  await panel.getByLabel("Surveyed area (m²)").fill("0.25");
  await panel.getByLabel("Reviewed by").fill("Scientist");
  await panel
    .getByLabel("Review notes")
    .fill("Confirmed count and measured quadrat area.");
  const save = panel.getByRole("button", { name: "Review and save analysis" });
  await expect(save).toBeDisabled();
  await panel
    .getByRole("checkbox", { name: /Confirm the selected observations/ })
    .check();
  await save.click();
  const results = panel.getByRole("table", {
    name: "Synthetic polyp survey detections",
  });
  await expect(results.getByRole("cell", { name: "4.000" })).toBeVisible();
  const download = panel.getByRole("link", { name: "Download JSON" });
  const url = await download.getAttribute("href");
  if (!url) throw new Error("Ecology export URL is missing");
  const snapshot = await (await page.request.get(url)).json();
  expect(snapshot.result.visits[0]).toMatchObject({
    count: 1,
    density_per_m2: 4,
  });
  await page.getByRole("button", { name: "Longitudinal candidates" }).click();
  await page.getByRole("button", { name: "Reviewed analyses" }).click();
  await panel.getByRole("button", { name: /^Abundance ·/ }).click();
  await expect(results.getByRole("cell", { name: "4.000" })).toBeVisible();
  await panel.getByRole("button", { name: "Prepare recalculation" }).click();
  await expect(
    panel.getByRole("button", { name: "Review and save recalculation" }),
  ).toBeDisabled();
});
