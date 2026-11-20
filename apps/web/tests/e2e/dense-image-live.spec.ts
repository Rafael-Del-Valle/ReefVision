import { expect, type APIResponse, type Response } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

import type {
  AnnotationSession,
  LabelClass,
  Project,
} from "../../src/api/client";
import { test } from "./spatialDesktop";

async function checked<T>(response: APIResponse | Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

function sha256(bytes: Buffer) {
  return createHash("sha256").update(bytes).digest("hex");
}

test("edits a dense image and reopens the same original and hidden boxes", async ({
  desktop,
}, info) => {
  test.setTimeout(90_000);
  const { api, web, page, surface } = desktop;
  const name = `Generated dense image ${randomUUID().slice(0, 8)}`;
  const project = await checked<Project>(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
    201,
  );
  const root = `${api}/projects/${project.id}`;
  const addClass = async (name: string, classIndex: number) =>
    checked<LabelClass>(
      await page.request.post(`${root}/classes`, {
        data: {
          name,
          class_index: classIndex,
          display_color: classIndex ? "#F5A44F" : "#48CA9E",
        },
      }),
      201,
    );
  const alpha = await addClass("Fixture Alpha", 0);
  const beta = await addClass("Fixture Beta", 1);
  const health = await checked<{ version: string }>(
    await page.request.get(`${api}/health`),
    200,
  );
  await page.addInitScript((version) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${version}`, "true");
  }, health.version);
  const openProject = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  };
  await openProject();
  const original = Buffer.from(
    await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 1200;
      canvas.height = 1000;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#324B5D";
      context.fillRect(0, 0, 1200, 1000);
      context.strokeStyle = "#DCDDB0";
      context.strokeRect(15, 15, 1170, 970);
      return canvas.toDataURL("image/png").split(",")[1];
    }),
    "base64",
  );
  const filename = "dense-original.png";
  const importResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${root}/imports/images`,
  );
  await page.getByLabel("Import files", { exact: true }).setInputFiles({
    name: filename,
    mimeType: "image/png",
    buffer: original,
  });
  const imported = await checked<{ successful: { image_id: string }[] }>(
    await importResponse,
    200,
  );
  expect(imported.successful).toHaveLength(1);
  const imageId = imported.successful[0].image_id;
  const imageApi = `${api}/images/${imageId}`;
  const session = () =>
    page.request
      .get(`${imageApi}/annotations`)
      .then((response) => checked<AnnotationSession>(response, 200));
  const annotations = Array.from({ length: 1500 }, (_, index) => {
    const x = (index % 50) * 22;
    const y = Math.floor(index / 50) * 24;
    return {
      id: randomUUID(),
      label_class_id: index % 2 ? beta.id : alpha.id,
      x_min: x,
      y_min: y,
      x_max: x + 16,
      y_max: y + 18,
    };
  });
  const seeded = await checked<AnnotationSession>(
    await page.request.put(`${imageApi}/annotations`, {
      data: {
        base_revision: (await session()).image.annotation_revision,
        annotation_status: "reviewed",
        annotations,
      },
    }),
    200,
  );
  expect(seeded.annotations).toHaveLength(1500);

  const annotate = () =>
    page
      .getByRole("article", { name: /dense-original\.png/ })
      .getByRole("button", { name: "Annotate", exact: true })
      .click();
  await annotate();
  const editor = page.getByTestId("annotation-editor");
  const canvas = editor.getByTestId("annotation-canvas");
  const boxes = canvas.locator("rect[data-testid^='annotation-']");
  const fit = editor.getByRole("button", { name: "Fit (F)", exact: true });
  await fit.click();
  await expect(boxes).toHaveCount(1500, { timeout: 25_000 });
  const objects = editor
    .getByRole("listbox", { name: "Objects" })
    .getByRole("option");
  await expect(objects).toHaveCount(200);
  await expect(objects.last()).toHaveAttribute("aria-setsize", "1500");
  await editor
    .getByRole("spinbutton", { name: "Jump to object position" })
    .fill("1500");
  await editor
    .getByRole("button", { name: "Jump to object", exact: true })
    .click();
  await expect(objects).toHaveCount(100);
  await expect(objects.last()).toHaveAttribute("aria-posinset", "1500");

  const alphaRow = editor
    .locator(".annotation-class-row")
    .filter({ hasText: alpha.name });
  const betaRow = editor
    .locator(".annotation-class-row")
    .filter({ hasText: beta.name });
  await betaRow.getByRole("checkbox", { name: "Visible" }).uncheck();
  await expect(boxes).toHaveCount(750);
  await alphaRow.getByRole("button", { name: "Solo", exact: true }).click();
  await expect(boxes).toHaveCount(750);
  await editor
    .getByRole("button", { name: "Actual Size (100%)", exact: true })
    .click();
  await canvas.scrollIntoViewIfNeeded();
  const canvasBox = (await canvas.boundingBox())!;
  await page.mouse.move(
    canvasBox.x + canvasBox.width / 2,
    canvasBox.y + canvasBox.height / 2,
  );
  for (let index = 0; index < 8; index += 1) await page.mouse.wheel(0, -70);
  await expect.poll(() => boxes.count()).toBeLessThan(750);
  const zoomRendered = await boxes.count();
  expect(zoomRendered).toBeGreaterThan(0);
  await fit.click();

  const target = annotations[204];
  const targetRect = canvas.getByTestId(`annotation-${target.id}`);
  await editor
    .getByRole("button", { name: "Select tool", exact: true })
    .click();
  const [start, end] = await targetRect.evaluate((box) => {
    const x = Number(box.getAttribute("x"));
    const y = Number(box.getAttribute("y"));
    const matrix = (box as SVGRectElement).getScreenCTM()!;
    const points = [
      new DOMPoint(x + 8, y + 9),
      new DOMPoint(x + 16, y + 14),
    ].map((point) => point.matrixTransform(matrix));
    if (document.elementFromPoint(points[0].x, points[0].y) !== box) {
      throw new Error("A visible annotation cannot receive its pointer edit");
    }
    return points.map((point) => ({ x: point.x, y: point.y }));
  });
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 5 });
  await page.mouse.up();
  const currentX = async () => Number(await targetRect.getAttribute("x"));
  await expect.poll(currentX).toBeGreaterThan(target.x_min + 6);
  await editor.getByRole("button", { name: "Undo", exact: true }).click();
  await expect.poll(currentX).toBe(target.x_min);
  await editor.getByRole("button", { name: "Redo", exact: true }).click();
  await expect.poll(currentX).toBeGreaterThan(target.x_min + 6);
  await editor.getByRole("button", { name: "Save now", exact: true }).click();
  await expect(editor.getByTestId("annotation-save-state")).toHaveText("Saved");
  await openProject();
  await annotate();
  await fit.click();
  await expect(boxes).toHaveCount(1500);
  const saved = await session();
  const final = new Map(saved.annotations.map((box) => [box.id, box]));
  expect(final.size).toBe(1500);
  for (const box of annotations) {
    if (box.id !== target.id) expect(final.get(box.id)).toMatchObject(box);
  }
  const moved = final.get(target.id)!;
  expect(moved.label_class_id).toBe(alpha.id);
  expect(Math.abs(moved.x_min - target.x_min - 8)).toBeLessThan(2);
  expect(Math.abs(moved.x_max - target.x_max - 8)).toBeLessThan(2);
  expect(Math.abs(moved.y_min - target.y_min - 5)).toBeLessThan(2);
  expect(Math.abs(moved.y_max - target.y_max - 5)).toBeLessThan(2);
  const content = await page.request.get(`${imageApi}/content`);
  expect(content.ok()).toBe(true);
  expect(sha256(await content.body())).toBe(sha256(original));
  await writeFile(
    info.outputPath("dense-image-evidence.json"),
    JSON.stringify(
      {
        surface,
        project_id: project.id,
        original_sha256: sha256(original),
        persisted_box_count: final.size,
        hidden_unchanged_count: 750,
        object_page_size: 200,
        last_object_position: 1500,
        rendered_at_zoom: zoomRendered,
        moved_box_id: moved.id,
        source_bbox_after: [moved.x_min, moved.y_min, moved.x_max, moved.y_max],
        editor_reopened: true,
        pointer_undo_redo_verified: true,
      },
      null,
      2,
    ),
  );
});
