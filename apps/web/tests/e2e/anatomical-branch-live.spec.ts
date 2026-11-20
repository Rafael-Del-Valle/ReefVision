import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

test("records and replays a provisional centerline from a selected project mesh", async ({
  page,
}) => {
  const api = process.env.REEFVISION_ANATOMICAL_TEST_API;
  const web = process.env.REEFVISION_ANATOMICAL_TEST_WEB;
  test.skip(!api || !web, "Requires an isolated ReefVision API and frontend.");
  const name = `Branch fixture ${randomUUID()}`;
  const project = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(project.status()).toBe(201);
  const { id } = await project.json();
  const imported = await page.request.post(
    `${api}/projects/${id}/spatial/assets`,
    {
      multipart: {
        file: {
          name: "reference-branch.obj",
          mimeType: "text/plain",
          buffer: Buffer.from("v 0 0 0\nv 4 0 0\nv 0 4 0\nf 1 2 3\n"),
        },
      },
    },
  );
  expect(imported.status(), await imported.text()).toBe(201);
  const source = await imported.json();
  const { version } = JSON.parse(await readFile("package.json", "utf8")) as {
    version: string;
  };
  await page.addInitScript((appVersion) => {
    localStorage.setItem(
      `reefvision.onboarding.dismissed.${appVersion}`,
      "true",
    );
  }, version);

  async function openSelectedMesh() {
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
    await page
      .getByLabel("Project 3D source", { exact: true })
      .selectOption(source.id);
  }
  await openSelectedMesh();
  const mesh = page.getByRole("region", { name: "Project 3D source assets" });
  await mesh
    .getByLabel("Calibration evidence (unverified)", { exact: true })
    .fill("Synthetic scale reference");
  await mesh
    .getByLabel("Relative scale uncertainty (0–1, optional)")
    .fill("0.1");
  const panel = page.getByRole("region", {
    name: "Anatomical branch measurements",
  });
  await expect(panel).toBeVisible();
  await panel.getByLabel("Source coordinate frame").fill("synthetic-frame");
  await panel.getByLabel("Base landmark").fill("Branch junction");
  await panel.getByLabel("Tip landmark").fill("Growth tip");
  await panel
    .getByLabel("Centerline selection method")
    .fill("Three manually digitized waypoints");
  await panel.getByLabel("Measurement operator").fill("fixture-operator");
  const points = panel.getByLabel("Ordered centerline coordinates");
  await points.fill("0 0 0\n0.3 0.4 5\n2.3 0.4 0");
  const save = panel.getByRole("button", {
    name: "Save and calculate centerline",
  });
  await save.click();
  await expect(panel.getByRole("alert")).toContainText(
    "source mesh coordinate bounds",
  );
  await points.fill("0 0 0\n0.3 0.4 0\n2.3 0.4 0");
  await save.click();
  await expect(panel.getByText("0.025 m", { exact: true })).toBeVisible();
  await expect(panel.getByText("Provisional evidence")).toBeVisible();

  await openSelectedMesh();
  await panel
    .getByLabel("Saved centerline workflow")
    .selectOption({ label: "Branch junction → Growth tip" });
  await expect(panel.getByText("0.025 m", { exact: true })).toBeVisible();
  const exportResult = async () => {
    const downloadPromise = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export centerline evidence" })
      .click();
    const file = await (await downloadPromise).path();
    return JSON.parse(await readFile(file, "utf8"));
  };
  const original = await exportResult();
  expect(original.measurement).toMatchObject({
    length_m: 0.025,
    source_payload_sha256: source.sha256,
    anatomical_claim_verified: false,
  });
  const queued = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/workflow-runs"),
  );
  await panel.getByRole("button", { name: "Replay saved centerline" }).click();
  expect((await queued).status()).toBe(202);
  await expect(panel.getByText("0.025 m", { exact: true })).toBeVisible();
  const replayed = await exportResult();
  expect(replayed.workflow_run_id).not.toBe(original.workflow_run_id);
  expect(replayed.workflow_payload_sha256).toBe(
    original.workflow_payload_sha256,
  );
  expect(replayed.measurement).toEqual(original.measurement);
});
