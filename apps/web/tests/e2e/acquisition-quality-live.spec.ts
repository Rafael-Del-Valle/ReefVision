import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

const clippedFixture = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAACgAAAAgCAIAAADvz61XAAAASElEQVR4nO3NMQ6AQBDDwMX///NSh/KQTEGmt3zNC7t73DIfoWML2umhYw3eKnWswVuljjV4q9SxBm+VOtbgrVLHGrzV/Hx8A28sAz0qvNYaAAAAAElFTkSuQmCC",
  "base64",
);

test("uses persisted acquisition warnings to review a source image", async ({
  page,
}, testInfo) => {
  const api = process.env.REEFVISION_ECOLOGY_TEST_API;
  const web = process.env.REEFVISION_ECOLOGY_TEST_WEB;
  test.skip(!api || !web, "Requires an isolated ReefVision API and Vite.");

  const name = `Acquisition ${randomUUID()}`;
  const project = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(project.ok(), await project.text()).toBeTruthy();
  const { id } = (await project.json()) as { id: string };
  const imported = await page.request.post(
    `${api}/projects/${id}/imports/images`,
    {
      multipart: {
        files: {
          name: "clipped-synthetic.png",
          mimeType: "image/png",
          buffer: clippedFixture,
        },
      },
    },
  );
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const { successful } = (await imported.json()) as {
    successful: { image_id: string }[];
  };
  expect(successful).toHaveLength(1);

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
  await page.getByRole("button", { name: name }).click();
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  await page.getByRole("tab", { name: "Quality control", exact: true }).click();
  await page
    .getByRole("checkbox", { name: "Image acquisition checks" })
    .check();
  await page.getByLabel("Minimum width (px)", { exact: true }).fill("48");
  await page.getByLabel("Maximum fraction in each clipping band").fill(".20");
  await page.getByLabel("Require timezone-qualified capture time").check();
  await page.getByRole("button", { name: "Run quality control" }).click();

  const result = page.getByRole("region", {
    name: "Acquisition quality evidence",
  });
  await expect(result.getByText(/1 images checked/)).toBeVisible();
  await result.getByText("Image measurements", { exact: true }).click();
  const row = result.getByRole("row", {
    name: /clipped-synthetic.png.*40.*32/,
  });
  await expect(
    row.getByRole("cell", { name: "50.0%", exact: true }),
  ).toHaveCount(2);
  await page.screenshot({
    path: testInfo.outputPath("acquisition-review-evidence.png"),
  });

  const warning = page
    .locator("article")
    .filter({ hasText: "High dark clipping fraction" });
  await warning.getByRole("button", { name: "Acknowledge" }).click();
  await expect(
    warning.getByText("acknowledged", { exact: true }),
  ).toBeVisible();
  await warning.getByRole("button", { name: "Open image" }).click();
  await page.getByRole("button", { name: "Back to Quality Control" }).click();
  await expect(
    page.getByRole("heading", { name: "Quality Control", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("High dark clipping fraction")).toBeVisible();

  const source = await page.request.get(
    `${api}/images/${successful[0].image_id}/content`,
  );
  expect(source.ok()).toBeTruthy();
  expect(await source.body()).toEqual(clippedFixture);
});
