import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

test("exchanges and reopens a project with reviewed scientific history", async ({
  page,
}) => {
  const api = process.env.REEFVISION_BRANCH_PREVIEW_TEST_API;
  const web = process.env.REEFVISION_BRANCH_PREVIEW_TEST_WEB;
  test.skip(!api || !web, "Requires an isolated SQLite API and Vite.");
  const sourceName = "Exchange scientific " + randomUUID();
  const destinationName = sourceName + " imported";
  const created = await page.request.post(`${api}/projects`, {
    data: { name: sourceName },
  });
  expect(created.status(), await created.text()).toBe(201);
  const project = await created.json();
  const registration = await page.request.post(
    `${api}/projects/${project.id}/ecology/organisms`,
    {
      data: {
        organism_key: "exchange-colony",
        kind: "colony",
        reason: "Recorded from synthetic fixture",
      },
    },
  );
  expect(registration.status(), await registration.text()).toBe(201);
  const { version } = JSON.parse(await readFile("package.json", "utf8"));
  await page.addInitScript(
    (v) => localStorage.setItem(`reefvision.onboarding.dismissed.${v}`, "true"),
    version,
  );

  async function openExchange(name: string) {
    await page.goto(web!);
    await page
      .getByRole("button", { name: "Open " + name, exact: true })
      .click();
    await page.getByRole("tab", { name: "Data & annotation" }).click();
    await page.getByRole("tab", { name: "Interoperability" }).click();
  }

  await openExchange(sourceName);
  await page.getByRole("button", { name: "Create exchange ZIP" }).click();
  const download = page.getByRole("link", { name: "Download ZIP" }).first();
  const href = await download.getAttribute("href", { timeout: 20000 });
  const exported = await page.request.get(href!);
  expect(exported.ok()).toBeTruthy();
  await page.getByLabel("Project exchange ZIP").setInputFiles({
    name: "science.reefvision.zip",
    mimeType: "application/zip",
    buffer: await exported.body(),
  });
  await page.getByRole("button", { name: "Inspect safely" }).click();
  await expect(page.getByText("Format: 1.2", { exact: true })).toBeVisible();
  await page.getByText("Record inventory", { exact: true }).click();
  await expect(
    page.getByText("ecology identity revisions · 1", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Imported project name (optional)")
    .fill(destinationName);
  await page.getByRole("button", { name: "Import as new project" }).click();
  await expect(
    page.getByText("Imported project", { exact: true }),
  ).toBeVisible();
  if (process.env.REEFVISION_BRANCH_EVIDENCE_DIR) {
    await page.screenshot({
      path: join(
        process.env.REEFVISION_BRANCH_EVIDENCE_DIR,
        "scientific-exchange.png",
      ),
      fullPage: true,
    });
  }

  await page.goto(web!);
  await page
    .getByRole("button", { name: "Open " + destinationName, exact: true })
    .click();
  await page.getByRole("tab", { name: "Organisms & ecology" }).click();
  await expect(
    page.getByRole("heading", { name: "exchange-colony", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Data & annotation" }).click();
  await page.getByRole("tab", { name: "Interoperability" }).click();
  await page.getByRole("button", { name: "Create exchange ZIP" }).click();
  await expect(
    page.getByRole("link", { name: "Download ZIP" }).first(),
  ).toBeVisible({ timeout: 20000 });
});
