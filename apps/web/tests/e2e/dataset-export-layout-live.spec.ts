import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { test } from "./spatialDesktop";

test("keeps YOLO export reachable while the project inspector is open", async ({
  desktop,
}) => {
  const { page, api, web, surface } = desktop;
  if (surface === "source-browser") {
    await page.setViewportSize({ width: 1440, height: 960 });
  }
  const name = `Synthetic export layout ${randomUUID().slice(0, 8)}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name, template: "blank" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { id } = (await created.json()) as { id: string };
  const project = `${api}/projects/${id}`;
  const imported = await page.request.post(`${project}/imports/images`, {
    multipart: {
      files: {
        name: "snapshot.png",
        mimeType: "image/png",
        buffer: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
          "base64",
        ),
      },
    },
  });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  expect((await imported.json()).successful).toHaveLength(1);
  const saved = await page.request.post(`${project}/dataset-versions`, {
    data: {
      name: "Frozen field images",
      eligible_annotation_statuses: ["unannotated"],
      split_method: "random",
      requested_ratios: { train: 1, validation: 0, test: 0 },
    },
  });
  expect(saved.status(), await saved.text()).toBe(201);

  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.9.0", "true"),
  );
  await page.goto(web);
  await page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  await page
    .getByRole("tab", { name: "Dataset versions", exact: true })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Workspace inspector" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Export YOLO dataset" }).click({
    trial: true,
    timeout: 5000,
  });
});
