import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { expect, type Locator } from "@playwright/test";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

test("hands keyboard focus from Help to each available workspace", async ({
  desktop,
}, info) => {
  const { page, api, web } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  const projectName = `Help handoff ${randomUUID().slice(0, 8)}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name: projectName, template: "blank" },
  });
  expect(created.status(), await created.text()).toBe(201);

  const device = await page.context().newCDPSession(page);
  const help = page.getByRole("button", { name: "Help", exact: true });
  const guide = page.getByRole("dialog", { name: /Welcome to ReefVision/ });
  const globalSystem = page
    .locator(".rv-global-actions")
    .getByRole("button", { name: "System status", exact: true });
  const system = page.getByRole("region", { name: "System status workspace" });
  const actions = [
    { name: "Open class manager", tab: "Classes" },
    { name: "Open QC review", tab: "Review queue" },
    { name: "Open Workflow Builder", tab: "Workflow builder" },
  ];
  const action = (name: string) =>
    guide.getByRole("button", { name, exact: true });

  async function openHelp() {
    await help.focus();
    await page.keyboard.press("Enter");
    await expect(
      guide.getByRole("button", { name: "Close", exact: true }),
    ).toBeFocused();
  }

  async function activateAction(button: Locator) {
    await expect(button).toBeEnabled();
    for (let step = 0; step < 10; step++) {
      if (
        await button.evaluate((element) => element === document.activeElement)
      )
        break;
      await page.keyboard.press("Tab");
    }
    await expect(button).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(guide).toBeHidden();
  }

  try {
    await device.send("Emulation.setDeviceMetricsOverride", {
      width: 960,
      height: 640,
      deviceScaleFactor: 1.5,
      mobile: false,
    });
    await page.goto(web);
    await expect(help).toBeVisible();
    if (await guide.isVisible()) await page.keyboard.press("Escape");
    const home = page.getByRole("button", { name: "Home", exact: true });
    if (await home.isVisible()) await home.click();
    await openHelp();
    expect(await page.evaluate(() => window.devicePixelRatio)).toBe(1.5);
    await test.step("launcher supports System and explains project-only destinations", async () => {
      for (const { name } of actions) await expect(action(name)).toBeDisabled();
      await activateAction(action("Open System status"));
      await expect(system).toBeFocused();
      await expect(
        system.getByRole("heading", { name: "System status", exact: true }),
      ).toBeVisible();
      const reopen = system.getByRole("button", { name: "Reopen onboarding" });
      await reopen.focus();
      await page.keyboard.press("Enter");
      await expect(guide).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(guide).toBeHidden();
      await expect(reopen).toBeFocused();
    });

    await test.step("choosing a project hands focus to the launcher", async () => {
      await openHelp();
      await activateAction(action("Choose an existing project"));
      const openProject = page.getByRole("button", {
        name: `Open ${projectName}`,
        exact: true,
      });
      await expect(openProject).toBeVisible();
      const focusedProject = page.locator(".rv-project-launcher-open:focus");
      await expect(focusedProject).toBeVisible();
      await openProject.click();
    });

    await test.step("workspace actions focus the selected project tab", async () => {
      for (const { name, tab } of actions) {
        await openHelp();
        await activateAction(action(name));
        const destination = page.getByRole("tab", { name: tab, exact: true });
        await expect(destination).toHaveAttribute("aria-selected", "true");
        await expect(destination).toBeFocused();
      }
    });

    await test.step("a collapsed navigation rail retains a keyboard entry to the destination", async () => {
      await device.send("Emulation.setDeviceMetricsOverride", {
        width: 1440,
        height: 960,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await page.getByRole("button", { name: "Collapse navigation" }).click();
      await openHelp();
      await activateAction(action("Open class manager"));
      await expect(
        page.getByRole("button", { name: "Show project navigation" }),
      ).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(
        page.getByRole("tab", { name: "Classes", exact: true }),
      ).toHaveAttribute("aria-selected", "true");
    });

    await test.step("System works from an open project and the global control still works", async () => {
      await openHelp();
      await activateAction(action("Open System status"));
      await expect(system).toBeFocused();
      await expect(
        page.getByRole("heading", { name: projectName, exact: true }),
      ).toBeHidden();
      await page.getByRole("button", { name: "Home", exact: true }).click();
      await globalSystem.focus();
      await page.keyboard.press("Enter");
      await expect(
        system.getByRole("heading", { name: "System status", exact: true }),
      ).toBeVisible();
    });
    await writeFile(
      info.outputPath("help-handoff-evidence.json"),
      JSON.stringify({
        ...runtime,
        surface: desktop.surface,
        opened_project: projectName,
        selected_tabs: actions.map((action) => action.tab),
        system_keyboard_handoff: true,
        collapsed_rail_focus: true,
        device_scale_factor: 1.5,
      }),
    );
  } finally {
    await device.send("Emulation.clearDeviceMetricsOverride");
    await device.detach();
  }
});
