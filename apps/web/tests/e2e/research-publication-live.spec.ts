import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

test("publishes and reopens a held-out agreement figure", async ({ page }) => {
  const api = process.env.REEFVISION_RESEARCH_REPORT_TEST_API;
  const web = process.env.REEFVISION_RESEARCH_REPORT_TEST_WEB;
  const seed = process.env.REEFVISION_RESEARCH_REPORT_TEST_SEED;
  test.skip(
    !api || !web || !seed,
    "Requires isolated API, Vite, and seeded synthetic held-out comparisons.",
  );

  const { project_id: project, report_ids: reports } = JSON.parse(
    await readFile(seed!, "utf-8"),
  ) as { project_id: string; report_ids: [string, string] };
  const base = `${api}/projects/${project}`;
  const projectResponse = await page.request.get(base);
  expect(projectResponse.ok()).toBeTruthy();
  const { name } = (await projectResponse.json()) as { name: string };
  const title = `Synthetic held-out agreement ${randomUUID().slice(0, 8)}`;

  await page.addInitScript(() => {
    localStorage.setItem("reefvision.onboarding.dismissed.1.4.0", "true");
  });
  const openProject = async () => {
    await page.goto(web!);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  };
  await openProject();
  await page.getByRole("tab", { name: "Models & AI" }).click();
  await page.getByRole("tab", { name: "Model Hub" }).click();
  await page
    .getByText("ReefPose scientific validation", { exact: true })
    .click();
  await page
    .getByText("Scientific human–model comparison", { exact: true })
    .click();
  await page.getByLabel("Primary held-out report").selectOption(reports[0]);
  await page.getByLabel("Second held-out report").selectOption(reports[1]);
  await page.getByLabel("Event label").fill("gape");
  const comparisonSaved = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${base}/scientific-comparisons`,
  );
  await page
    .getByRole("button", { name: "Save scientific comparison" })
    .click();
  const comparison = await comparisonSaved;
  expect(comparison.status(), await comparison.text()).toBe(201);
  const { id: comparisonId, content_sha256: sourceSha } =
    await comparison.json();
  const agreement = page.getByRole("region", {
    name: "Saved scientific comparison",
  });
  await expect(
    agreement.getByText("Synthetic engineering reference", { exact: false }),
  ).toBeVisible();
  await expect(
    agreement
      .getByRole("img", { name: /Bland–Altman difference plot/ })
      .first(),
  ).toBeVisible();

  const openReports = async () => {
    const ecology = page.getByRole("tab", {
      name: "Organisms & ecology",
      exact: true,
    });
    if (!(await ecology.isVisible())) {
      await page
        .getByRole("tab", { name: "Data & annotation", exact: true })
        .click();
    }
    await page
      .getByRole("tab", { name: "Organisms & ecology", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Research reports", exact: true })
      .click();
  };
  await openReports();
  const panel = page.getByRole("region", {
    name: "Publication figures and research reports",
  });
  await panel.getByLabel("Source type").selectOption("comparison");
  await panel.getByLabel("Saved source").selectOption(comparisonId);
  await panel
    .getByRole("combobox")
    .filter({ has: page.getByRole("option", { name: "Bland–Altman plot" }) })
    .selectOption("bland_altman");
  await panel.getByLabel("Figure title").fill(title);
  const reportSaved = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${base}/research-reports`,
  );
  await panel.getByRole("button", { name: "Save research figure" }).click();
  const report = await reportSaved;
  expect(report.status(), await report.text()).toBe(201);
  const { id: figureId, snapshot } = await report.json();
  expect(snapshot.source_sha256).toBe(sourceSha);
  const figure = panel.getByRole("img", { name: new RegExp(title) });
  await expect(figure).toBeVisible();
  await figure.evaluate((image: HTMLImageElement) => image.decode());
  const output = process.env.REEFVISION_RESEARCH_REPORT_TEST_SCREENSHOTS;
  if (output) {
    await figure.scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(output, "publication-agreement.png") });
  }

  await openProject();
  await openReports();
  await panel.getByLabel("Saved reports").selectOption(figureId);
  await expect(figure).toBeVisible();
  const svgUrl = await panel
    .getByRole("link", { name: "Download SVG" })
    .getAttribute("href");
  const svg = await page.request.get(svgUrl!);
  expect(svg.ok()).toBeTruthy();
  expect(await svg.text()).toContain("Model minus reference (count)");
  const csvUrl = await panel
    .getByRole("link", { name: "Download CSV" })
    .getAttribute("href");
  const csv = await page.request.get(csvUrl!);
  expect(csv.ok()).toBeTruthy();
  expect(await csv.text()).toContain("Fixture model");
});
