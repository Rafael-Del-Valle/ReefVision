import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

import { test } from "./spatialDesktop";

const image = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
  "base64",
);

test("native-safe editor decisions preserve drafts until explicit discard", async ({
  desktop,
}, info) => {
  const { page, api, web, surface } = desktop;
  const name = `Generated editing conflicts ${randomUUID().slice(0, 8)}`;
  async function json(response: Awaited<ReturnType<typeof page.request.get>>) {
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  }

  const { id: projectId } = await json(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
  );
  const { id: labelId } = await json(
    await page.request.post(`${api}/projects/${projectId}/classes`, {
      data: {
        class_index: 0,
        name: "Generated subject",
        display_color: "#28A95C",
      },
    }),
  );
  const imported = await json(
    await page.request.post(`${api}/projects/${projectId}/imports/images`, {
      multipart: {
        files: {
          name: "generated-conflict.png",
          mimeType: "image/png",
          buffer: image,
        },
      },
    }),
  );
  expect(imported.successful, JSON.stringify(imported)).toHaveLength(1);
  const imageId: string = imported.successful[0].image_id;
  const annotationUrl = `${api}/images/${imageId}/annotations`;
  const box = {
    id: randomUUID(),
    label_class_id: labelId,
    x_min: 5,
    y_min: 6,
    x_max: 20,
    y_max: 24,
  };
  const polygon = {
    id: randomUUID(),
    label_class_id: labelId,
    geometry_kind: "polygon",
    points: [
      { x: 25, y: 15 },
      { x: 50, y: 15 },
      { x: 40, y: 33 },
    ],
  };
  const independentBox = { ...box, x_min: 9 };
  const independentSave = async (
    revision: number,
    sourceBox: typeof box,
    annotationStatus = "in_progress",
  ) =>
    json(
      await page.request.put(annotationUrl, {
        data: {
          base_revision: revision,
          annotation_status: annotationStatus,
          annotations: [sourceBox],
          mask_annotations: [polygon],
        },
      }),
    );
  expect((await independentSave(0, box)).image.annotation_revision).toBe(1);

  const { version } = await json(await page.request.get(`${api}/health`));
  await page.addInitScript(
    (appVersion: string) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${appVersion}`,
        "true",
      ),
    version,
  );
  await page.goto(web);
  await page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  await page.getByRole("button", { name: "Annotate", exact: true }).click();
  const boxEditor = page.getByTestId("annotation-editor");
  const status = boxEditor.getByLabel("Annotation status");
  const svgBox = page.getByTestId(`annotation-${box.id}`);
  await expect(svgBox).toHaveAttribute("x", "5");
  expect(
    (await independentSave(1, independentBox)).image.annotation_revision,
  ).toBe(2);

  const saveConflict = () =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        response.url() === annotationUrl &&
        response.status() === 409,
    );
  const conflictedBox = saveConflict();
  await status.selectOption("reviewed");
  await boxEditor
    .getByRole("button", { name: "Save now", exact: true })
    .click();
  expect((await conflictedBox).request().postDataJSON().base_revision).toBe(1);
  const reload = boxEditor.getByRole("button", {
    name: "Reload latest",
    exact: true,
  });
  await reload.click();
  const confirmReload = page.getByRole("alertdialog", {
    name: "Reload the saved revision?",
  });
  await expect(
    confirmReload.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirmReload).toBeHidden();
  await expect(reload).toBeFocused();
  await expect(status).toHaveValue("reviewed");
  await expect(svgBox).toHaveAttribute("x", "5");
  await expect(boxEditor.getByRole("button", { name: /^Undo/ })).toBeEnabled();
  await reload.click();
  await confirmReload
    .getByRole("button", { name: "Discard and reload", exact: true })
    .click();
  await expect(svgBox).toHaveAttribute("x", "9");
  await expect(status).toHaveValue("in_progress");

  await page.getByTestId("open-polygon-tool").click();
  await page.getByTestId("move-polygon-nodes").click();
  const maskEditor = page.getByTestId("mask-workspace");
  const savedPolygon = maskEditor.locator(
    `g[data-mask-id="${polygon.id}"] polygon`,
  );
  await expect(savedPolygon).toBeVisible();
  expect(
    (await independentSave(2, independentBox, "reviewed")).image
      .annotation_revision,
  ).toBe(3);

  await savedPolygon.click();
  await maskEditor
    .getByRole("button", { name: "Delete selected masks", exact: true })
    .click();
  await expect(savedPolygon).toHaveCount(0);
  const conflictedMask = saveConflict();
  const close = maskEditor.getByRole("button", {
    name: "Close editor",
    exact: true,
  });
  await close.click();
  expect((await conflictedMask).request().postDataJSON().base_revision).toBe(2);
  const confirmMask = page.getByRole("alertdialog", {
    name: "Discard mask edits?",
  });
  const cancelMask = confirmMask.getByRole("button", {
    name: "Cancel",
    exact: true,
  });
  await expect(cancelMask).toBeFocused();
  await cancelMask.click();
  await expect(confirmMask).toBeHidden();
  await expect(close).toBeFocused();
  await expect(savedPolygon).toHaveCount(0);
  await maskEditor.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(savedPolygon).toBeVisible();
  await maskEditor.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(savedPolygon).toHaveCount(0);
  await close.click();
  await confirmMask
    .getByRole("button", { name: "Discard mask edits", exact: true })
    .click();
  await expect(maskEditor).toHaveCount(0);

  const reopened = await json(await page.request.get(annotationUrl));
  expect(reopened.image).toMatchObject({
    annotation_revision: 3,
    annotation_status: "reviewed",
  });
  expect(reopened.annotations[0]).toMatchObject({ id: box.id, x_min: 9 });
  expect(reopened.mask_annotations[0]).toMatchObject({
    id: polygon.id,
    polygon_json: [
      [25, 15],
      [50, 15],
      [40, 33],
    ],
  });
  await writeFile(
    info.outputPath("editor-confirmation-evidence.json"),
    JSON.stringify(
      {
        surface,
        image_id: imageId,
        persisted_revision: 3,
        conflicts: [409, 409],
        box_after_confirmed_reload: reopened.annotations[0].x_min,
        persisted_mask_id: polygon.id,
        canceled_preserved_drafts_and_undo: true,
      },
      null,
      2,
    ),
  );
});
