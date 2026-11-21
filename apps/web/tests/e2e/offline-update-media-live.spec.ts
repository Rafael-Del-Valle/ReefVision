import { writeFile } from "node:fs/promises";
import { expect } from "@playwright/test";

import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

test("Help verifies the complete offline MSI and cabinets against the review digest", async ({
  desktop,
}, info) => {
  const directory = process.env.REEFVISION_TEST_INSTALLER_MEDIA;
  const pin = process.env.REEFVISION_TEST_INSTALLER_MANIFEST_SHA256;
  test.skip(
    !directory || !pin,
    "A separate review manifest digest and exact offline media are required.",
  );
  const { page, api, web, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${version}`,
        "true",
      ),
    runtime.application_version,
  );
  await page.goto(web);
  await page.getByRole("button", { name: "Help", exact: true }).click();
  await page
    .getByRole("button", { name: "Diagnostics / Updates", exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "Offline updates and recovery",
  });
  await expect(
    panel.getByRole("heading", { name: "Offline updates and recovery" }),
  ).toBeFocused();
  await panel.getByLabel("Installer folder").fill(directory!);
  const digest = panel.getByLabel("Expected manifest SHA-256");
  await digest.fill("0".repeat(64));
  await panel.getByRole("button", { name: "Verify offline media" }).click();
  await expect(panel.getByRole("alert")).toContainText(
    "manifest checksum differs",
  );
  await digest.fill(pin!);
  const inspected = page.waitForResponse(
    (r) => r.url().endsWith("/system/updates/inspect") && r.status() === 200,
    { timeout: 120_000 },
  );
  await panel.getByRole("button", { name: "Verify offline media" }).click();
  const report = await (await inspected).json();
  await expect(
    panel.getByRole("heading", { name: "Media checksums verified" }),
  ).toBeVisible();
  expect(report.manifest_sha256).toBe(pin);
  expect(
    report.files.every((f: { status: string }) => f.status === "matched"),
  ).toBe(true);
  expect(
    report.files.some((f: { name: string }) => f.name.endsWith(".cab")),
  ).toBe(true);
  await panel.getByRole("link", { name: "Go to Backups and restore" }).click();
  await expect(
    page.getByRole("heading", { name: "Backups and restore" }),
  ).toBeInViewport();
  await writeFile(
    info.outputPath("offline-media-inspection.json"),
    JSON.stringify(
      {
        surface,
        runtime,
        report,
        wrong_pin_refused: true,
        backup_navigation: true,
      },
      null,
      2,
    ),
  );
});
