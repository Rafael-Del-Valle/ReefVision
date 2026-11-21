import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("configures, runs, edits and replays acquisition QC through the visual workflow editor", async ({
  page,
}, info) => {
  const web = process.env.REEFVISION_GUIDED_TEST_WEB;
  const api = process.env.REEFVISION_GUIDED_TEST_API;
  test.skip(!web || !api, "Requires an isolated local ReefVision API and Vite");
  const name = `Synthetic guided workflow ${randomUUID().slice(0, 8)}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { id } = (await created.json()) as { id: string };
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT9sAAAAASUVORK5CYII=",
    "base64",
  );
  const imported = await page.request.post(
    `${api}/projects/${id}/imports/images`,
    {
      multipart: {
        files: { name: "synthetic.png", mimeType: "image/png", buffer: png },
      },
    },
  );
  expect(imported.ok(), await imported.text()).toBeTruthy();
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.2.0.0", "true"),
  );
  const open = async () => {
    await page.goto(web!);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
  };
  await open();
  await page
    .getByRole("combobox")
    .filter({
      has: page.getByRole("option", { name: "Project images", exact: true }),
    })
    .selectOption("project-images");
  await page.getByLabel("Add node").selectOption("image_acquisition_quality");
  const node = page.locator("[data-node-id^='image_acquisition_quality-']");
  await node.getByRole("button", { name: "Configure", exact: true }).click();
  await page.getByLabel("Minimum width (px)").fill("12");
  await page.getByLabel("Require camera make and model").check();
  await page
    .locator("[data-node-id='project']")
    .getByRole("button", { name: /Project.*▶/i })
    .click();
  await node.getByRole("button", { name: /◀.*Project/i }).click();
  const run = async () => {
    const queued = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith("/workflow-runs"),
    );
    await page.getByRole("button", { name: "Save & run", exact: true }).click();
    const response = await queued;
    expect(response.status(), await response.text()).toBe(202);
    const started = (await response.json()) as { id: string };
    await expect
      .poll(
        async () => {
          const current = await page.request.get(
            `${api}/workflow-runs/${started.id}`,
          );
          const detail = await current.json();
          return detail.run.status;
        },
        { timeout: 25000 },
      )
      .toBe("succeeded");
    return started.id;
  };
  const first = await run();
  await expect(
    page.getByText("acquisition_quality_result", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("guided-acquisition-first-run.png"),
  });
  await open();
  await page.getByRole("button", { name: "Load", exact: true }).first().click();
  await node.getByRole("button", { name: "Configure", exact: true }).click();
  await expect(page.getByLabel("Minimum width (px)")).toHaveValue("12");
  await page.getByLabel("Minimum width (px)").fill("15");
  const replay = await run();
  expect(replay).not.toBe(first);
  const detail = await (
    await page.request.get(`${api}/workflow-runs/${replay}`)
  ).json();
  const result = detail.artifacts.find(
    (item: { data_type: string }) =>
      item.data_type === "acquisition_quality_result",
  );
  expect(result.payload_json.report.thresholds.min_width_px).toBe(15);
});
