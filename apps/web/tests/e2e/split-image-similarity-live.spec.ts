import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { expect } from "@playwright/test";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

test("flags a recompressed image in a different frozen split and records review", async ({
  desktop,
}, info) => {
  const { page, api, web, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  const name = `Image split review ${randomUUID().slice(0, 8)}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name, template: "blank" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const project = await created.json();
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${version}`,
        "true",
      ),
    runtime.application_version,
  );
  await page.goto(web);
  const images = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 240;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#495776";
    ctx.fillRect(0, 0, 320, 240);
    ctx.fillStyle = "#dfce81";
    ctx.fillRect(45, 15, 107, 30);
    ctx.fillStyle = "#f18572";
    ctx.fillRect(15, 85, 67, 112);
    const png = canvas.toDataURL("image/png").split(",")[1];
    const smaller = document.createElement("canvas");
    smaller.width = 160;
    smaller.height = 120;
    smaller.getContext("2d")!.drawImage(canvas, 0, 0, 160, 120);
    return [png, smaller.toDataURL("image/jpeg", 0.85).split(",")[1]];
  });
  const root = `${api}/projects/${project.id}`;
  const assignments = [];
  for (const [i, bytes] of images.entries()) {
    const uploaded = await page.request.post(`${root}/imports/images`, {
      multipart: {
        files: {
          name: i ? "renamed.jpg" : "source.png",
          mimeType: i ? "image/jpeg" : "image/png",
          buffer: Buffer.from(bytes, "base64"),
        },
      },
    });
    expect(uploaded.status(), await uploaded.text()).toBe(200);
    const id = (await uploaded.json()).successful[0].image_id;
    const reviewed = await page.request.put(`${api}/images/${id}/annotations`, {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [],
      },
    });
    expect(reviewed.status(), await reviewed.text()).toBe(200);
    assignments.push({ image_id: id, split: i ? "test" : "train" });
  }
  const frozen = await page.request.post(`${root}/dataset-versions`, {
    data: {
      name: "Frozen screening roster",
      eligible_annotation_statuses: ["reviewed"],
      split_method: "manual",
      manual_assignments: assignments,
    },
  });
  expect(frozen.status(), await frozen.text()).toBe(201);
  const version = await frozen.json();
  await page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  await page.getByRole("tab", { name: "Quality control", exact: true }).click();
  await page
    .getByRole("combobox", { name: /^Scope/ })
    .selectOption("dataset_version");
  await page
    .getByRole("combobox", { name: /^Dataset version/ })
    .selectOption(version.id);
  const waiting = page.waitForResponse(
    (response) =>
      response
        .url()
        .endsWith(`/dataset-versions/${version.id}/quality-control-runs`) &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Check for similar images across splits" })
    .click();
  const run = await (await waiting).json();
  const warning = page
    .locator("article")
    .filter({ hasText: "Similar images in different dataset splits" });
  await expect(warning).toContainText("source.png");
  await expect(warning).toContainText("renamed.jpg");
  await warning.getByRole("button", { name: "Acknowledge" }).click();
  await expect(
    warning.getByText("acknowledged", { exact: true }),
  ).toBeVisible();
  const issues = await (
    await page.request.get(`${api}/quality-control-runs/${run.id}/issues`)
  ).json();
  expect(issues.total).toBe(1);
  expect(issues.items[0].measured_values_json.manifest_sha256).toBe(
    version.manifest_sha256,
  );
  await writeFile(
    info.outputPath("split-screen.json"),
    JSON.stringify(
      {
        runtime,
        surface,
        version_id: version.id,
        run_id: run.id,
        issue: issues.items[0],
      },
      null,
      2,
    ),
  );
});
