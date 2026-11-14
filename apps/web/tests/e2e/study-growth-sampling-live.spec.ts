import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

test("reviews a study assignment and preserves wholly missing planned visits", async ({
  page,
}, testInfo) => {
  const api = process.env.REEFVISION_ECOLOGY_TEST_API;
  const web = process.env.REEFVISION_ECOLOGY_TEST_WEB;
  test.skip(!api || !web, "Requires an isolated ReefVision API and Vite.");

  const name = `Study ${randomUUID()}`;
  const project = await page.request.post(`${api}/projects`, {
    data: { name },
  });
  expect(project.ok(), await project.text()).toBeTruthy();
  const { id } = (await project.json()) as { id: string };
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
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await page
    .getByRole("tab", { name: "Organisms & ecology", exact: true })
    .click();

  const registration = page.getByRole("form", { name: "Register organism" });
  await registration.getByLabel("Organism ID").fill("SYNTHETIC-A");
  await registration.getByLabel("Organism type").selectOption("individual");
  await registration.getByText("Experimental unit", { exact: true }).click();
  await registration.getByLabel("Unit type").fill("tank");
  await registration.getByLabel("Unit ID", { exact: true }).fill("TANK-1");
  await registration
    .getByText("Reviewed study assignment", { exact: true })
    .click();
  await registration
    .getByLabel("Study assignment action")
    .selectOption("review");
  await registration.getByLabel("Tank ID", { exact: true }).fill("TANK-1");
  await registration.getByLabel("Site ID", { exact: true }).fill("SITE-1");
  await registration.getByLabel("Treatment ID").fill("SYNTHETIC-CONTROL");
  await registration
    .getByLabel("Sampling unit type")
    .selectOption("individual");
  await registration.getByLabel("Sampling unit ID").fill("SAMPLE-1");
  await registration.getByLabel("Study reviewer").fill("Synthetic reviewer");
  await registration
    .getByLabel("Study notes")
    .fill("Confirmed fixture assignment.");
  await registration.getByLabel("I reviewed these study assignments").check();
  await registration
    .getByLabel("Registration reason")
    .fill("Synthetic study enrolment.");
  await registration.getByRole("button", { name: "Register organism" }).click();
  await expect(
    page.getByRole("heading", { name: "SYNTHETIC-A" }),
  ).toBeVisible();
  await expect(
    page
      .getByText("SYNTHETIC-CONTROL", { exact: true })
      .filter({ visible: true }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("reviewed-study-assignment.png"),
  });

  await page.getByRole("button", { name: "Reviewed analyses" }).click();
  const panel = page.getByRole("region", {
    name: "Reviewed ecological analyses",
  });
  await panel
    .getByLabel("Track missing measurements against planned visits")
    .check();
  await panel.getByLabel("Include TANK-1 in sampling plan").check();
  await panel.getByLabel("Expect SYNTHETIC-A in TANK-1").check();
  await panel
    .getByLabel("TANK-1 planned date 1 (UTC)", { exact: true })
    .fill("2026-11-01");
  await panel
    .getByLabel("TANK-1 planned date 2 (UTC)", { exact: true })
    .fill("2026-11-01");
  await panel.getByLabel("Reviewed by").fill("Synthetic reviewer");
  await panel
    .getByLabel("Review notes")
    .fill("Confirmed roster and planned UTC dates.");
  const confirm = panel.getByRole("checkbox", {
    name: /Confirm the selected observations/,
  });
  await confirm.check();
  const save = panel.getByRole("button", { name: "Review and save analysis" });
  await expect(save).toBeDisabled();
  await panel
    .getByLabel("TANK-1 planned date 2 (UTC)", { exact: true })
    .fill("2026-11-03");
  await expect(confirm).not.toBeChecked();
  await confirm.check();
  await save.click();

  const effort = panel.getByRole("table", { name: "Planned organism visits" });
  await expect(effort.getByRole("row", { name: "TANK-1 2 0 2" })).toBeVisible();
  await panel.getByText("Open planned-date coverage", { exact: true }).click();
  await expect(
    panel.getByRole("row", { name: "TANK-1 2026-11-03 None SYNTHETIC-A" }),
  ).toBeVisible();
  await expect(
    panel.getByText("Descriptive experimental-unit summaries"),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("scheduled-growth-missingness.png"),
  });
  const csv = await panel
    .getByRole("link", { name: "Download CSV" })
    .getAttribute("href");
  expect(await (await page.request.get(csv!)).text()).toContain(
    "scheduled_date,TANK-1,2026-11-03",
  );

  await page.getByRole("button", { name: "Identity registry" }).click();
  await page.getByRole("button", { name: "Reviewed analyses" }).click();
  await panel.getByRole("button", { name: /^Growth ·/ }).click();
  await expect(effort.getByRole("row", { name: "TANK-1 2 0 2" })).toBeVisible();

  await page.getByRole("button", { name: "Research reports" }).click();
  const reports = page.getByRole("region", {
    name: "Publication figures and research reports",
  });
  await reports.getByLabel("Saved source").selectOption({ index: 1 });
  await reports
    .getByRole("combobox")
    .filter({
      has: page.getByRole("option", {
        name: "Sampling coverage and missingness",
      }),
    })
    .selectOption("sample_coverage");
  await reports
    .getByLabel("Figure title")
    .fill("Synthetic planned visit coverage");
  await reports.getByRole("button", { name: "Save research figure" }).click();
  const coverage = reports.getByRole("img", {
    name: /Synthetic planned visit coverage/,
  });
  await expect(coverage).toBeVisible();
  await expect
    .poll(() =>
      coverage.evaluate((image) => (image as HTMLImageElement).naturalWidth),
    )
    .toBeGreaterThan(0);
  await page.screenshot({
    path: testInfo.outputPath("publication-planned-visit-coverage.png"),
  });

  const registry = await page.request.get(
    `${api}/projects/${id}/ecology/identity-registry`,
  );
  expect(registry.ok(), await registry.text()).toBeTruthy();
  expect(
    (await registry.json()).identity_history[0].study_assignment,
  ).toMatchObject({
    sampling_unit_id: "SAMPLE-1",
    treatment_code: "SYNTHETIC-CONTROL",
    review_status: "reviewed",
  });
});
