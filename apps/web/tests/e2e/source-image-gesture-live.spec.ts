import { expect } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

test("keeps a box gesture in source coordinates when the original arrives", async ({
  desktop: { page, api, web, surface },
}, info) => {
  const runtime = await verifyResearchDesktop(page, api);
  page.setDefaultTimeout(10_000);
  if (surface === "source-browser") {
    await page.setViewportSize({ width: 880, height: 680 });
  }
  const name = "Synthetic source image gesture " + randomUUID().slice(0, 8);
  const filename = "source-gesture-fixture.png";
  const bytes = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
    "base64",
  );
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  const created = await page.request.post(api + "/projects", {
    data: { name, template: "blank" },
  });
  expect(created.status()).toBe(201);
  const project = await created.json();
  const projectApi = api + "/projects/" + project.id;
  const klass = await page.request.post(projectApi + "/classes", {
    data: { class_index: 0, name: "Fixture animal", display_color: "#28A95C" },
  });
  expect(klass.status()).toBe(201);
  const label = await klass.json();
  const importImage = async (name: string, buffer: Buffer) => {
    const imported = await page.request.post(projectApi + "/imports/images", {
      multipart: {
        files: { name, mimeType: "image/png", buffer },
        relative_paths: name,
      },
    });
    expect(imported.status()).toBe(200);
    const result = await imported.json();
    expect(result.successful).toHaveLength(1);
    return result.successful[0].image_id as string;
  };
  const imageId = await importImage(filename, bytes);
  const secondId = await importImage(
    "source-gesture-neighbor.png",
    await readFile(
      new URL("./fixtures/underwater-oriented-rgb.png", import.meta.url),
    ),
  );

  await page.addInitScript((appVersion) => {
    localStorage.setItem(
      "reefvision.onboarding.dismissed." + appVersion,
      "true",
    );
  }, runtime.application_version);
  const openEditor = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: "Open " + name, exact: true })
      .click();
    await page
      .getByRole("article", { name: /^source-gesture-fixture[.]png,/ })
      .getByRole("button", { name: "Annotate", exact: true })
      .click();
  };

  const original = api + "/images/" + imageId + "/display?retry=0";
  const secondOriginal = api + "/images/" + secondId + "/display";
  const secondError = secondOriginal + "?retry=0";
  const nativeDisplay =
    surface === "tauri-webview2"
      ? await page.context().newCDPSession(page)
      : null;
  let releaseOriginal!: () => void;
  const gate = new Promise<void>((release) => {
    releaseOriginal = release;
  });
  let originalRequested = false;
  await page.route(original, async (route) => {
    originalRequested = true;
    await gate;
    await route.continue();
  });

  try {
    if (nativeDisplay) {
      await nativeDisplay.send("Emulation.setDeviceMetricsOverride", {
        width: 960,
        height: 640,
        deviceScaleFactor: 1.5,
        mobile: false,
      });
    }
    await openEditor();
    const viewport = await page.evaluate(() => ({
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    }));
    if (nativeDisplay) {
      expect(viewport).toEqual({
        width: 960,
        height: 640,
        devicePixelRatio: 1.5,
      });
    }
    const editor = page.getByTestId("annotation-editor");
    const canvas = editor.getByTestId("annotation-canvas");
    const segmentation = editor.getByLabel("Segmentation model", {
      exact: true,
    });
    const status = editor.getByText("Loading full-resolution image...", {
      exact: true,
    });
    await editor.getByRole("button", { name: "Box tool", exact: true }).click();
    await expect(status).toBeVisible();
    await expect(
      editor.getByRole("button", {
        name: "Retry loading full-resolution image",
        exact: true,
      }),
    ).toBeEnabled();
    await expect.poll(() => originalRequested).toBe(true);
    await canvas.scrollIntoViewIfNeeded();

    const imagePoints = () =>
      canvas.evaluate(async (svg) => {
        await new Promise<void>((ready) =>
          requestAnimationFrame(() => requestAnimationFrame(() => ready())),
        );
        const group = svg.querySelector<SVGGElement>(
          '[data-testid="viewport-transform"]',
        );
        const matrix = group?.getScreenCTM();
        if (!matrix) throw new Error("No source coordinate transform");
        const start = new DOMPoint(20, 15).matrixTransform(matrix);
        const end = new DOMPoint(55, 40).matrixTransform(matrix);
        return {
          start: { x: start.x, y: start.y },
          end: { x: end.x, y: end.y },
        };
      });
    const before = await imagePoints();
    await page.mouse.move(before.start.x, before.start.y);
    await page.mouse.down();
    await page.mouse.move(before.start.x + 1, before.start.y + 1);
    releaseOriginal();
    await expect(status).toBeHidden();
    await expect(canvas.locator("image")).toHaveAttribute("href", original);
    const after = await imagePoints();
    await page.mouse.move(before.end.x, before.end.y, { steps: 8 });
    await page.mouse.up();

    const boxes = canvas.locator("[data-testid^='annotation-']");
    await expect(boxes).toHaveCount(1);
    await editor.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(boxes).toHaveCount(0);
    await editor.getByRole("button", { name: "Redo", exact: true }).click();
    await expect(boxes).toHaveCount(1);
    await editor.getByLabel("Annotation status").selectOption("reviewed");
    await editor.getByRole("button", { name: "Save now", exact: true }).click();
    await expect(editor.getByTestId("annotation-save-state")).toHaveText(
      "Saved",
    );

    const saved = await page.request.get(
      api + "/images/" + imageId + "/annotations",
    );
    expect(saved.ok()).toBe(true);
    const document = await saved.json();
    expect(document.annotations).toHaveLength(1);
    expect(document.image).toMatchObject({
      sha256,
      annotation_status: "reviewed",
    });
    const box = document.annotations[0];
    const output = {
      surface,
      imageId,
      sha256,
      application_version: runtime.application_version,
      schema_revision: runtime.schema_revision,
      viewport,
      before,
      after,
      box,
    };
    const receipt = info.outputPath("source-image-gesture-evidence.json");
    await writeFile(receipt, JSON.stringify(output, null, 2));
    expect(box.label_class_id).toBe(label.id);
    expect(box.x_min).toBeCloseTo(20, 0);
    expect(box.y_min).toBeCloseTo(15, 0);
    expect(box.x_max).toBeCloseTo(55, 0);
    expect(box.y_max).toBeCloseTo(40, 0);
    expect(after.start.x).toBeCloseTo(before.start.x, 0);
    expect(after.start.y).toBeCloseTo(before.start.y, 0);
    expect(after.end.x).toBeCloseTo(before.end.x, 0);
    expect(after.end.y).toBeCloseTo(before.end.y, 0);
    await expect(segmentation).toBeVisible();

    await openEditor();
    await expect(canvas.getByTestId("annotation-" + box.id)).toBeVisible();
    await expect(editor.getByLabel("Annotation status")).toHaveValue(
      "reviewed",
    );
    await expect(segmentation).toBeVisible();

    await page.route(secondError, (route) => route.fulfill({ status: 503 }));
    expect([document.previous_image_id, document.next_image_id]).toContain(
      secondId,
    );
    const direction =
      document.next_image_id === secondId
        ? "Next image (D)"
        : "Previous image (A)";
    await editor.getByRole("button", { name: direction, exact: true }).click();
    await expect(
      editor.getByRole("heading", { name: "source-gesture-neighbor.png" }),
    ).toBeVisible();
    const selectOnSecond = editor.locator(
      `[data-segmentation-image-id="${secondId}"]`,
    );
    await expect(selectOnSecond.getByLabel("Segmentation model")).toBeVisible();
    const retry = editor.getByRole("button", {
      name: "Retry full-resolution image",
      exact: true,
    });
    await expect(retry).toBeVisible();
    await retry.focus();
    await expect(retry).toBeFocused();
    await retry.press("Enter");
    await expect(canvas.locator("image")).toHaveAttribute(
      "href",
      secondOriginal + "?retry=1",
    );
    await expect(selectOnSecond.getByLabel("Segmentation model")).toBeVisible();

    await editor.getByRole("button", { name: "Box tool", exact: true }).click();
    await canvas.scrollIntoViewIfNeeded();
    const ready = await imagePoints();
    await page.mouse.move(ready.start.x, ready.start.y);
    await page.mouse.down();
    await page.mouse.move(ready.end.x, ready.end.y, { steps: 8 });
    await page.mouse.up();
    await expect(boxes).toHaveCount(1);
    const readyBox = await boxes
      .first()
      .evaluate((rect) =>
        Object.fromEntries(
          ["x", "y", "width", "height"].map((name) => [
            name,
            Number(rect.getAttribute(name)),
          ]),
        ),
      );
    expect(readyBox.x).toBeCloseTo(20, 0);
    expect(readyBox.y).toBeCloseTo(15, 0);
    expect(readyBox.width).toBeCloseTo(35, 0);
    expect(readyBox.height).toBeCloseTo(25, 0);
    await editor.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(boxes).toHaveCount(0);

    await editor.getByText("Image adjustments", { exact: true }).click();
    await editor.getByLabel("Red gain (%)", { exact: true }).fill("125");
    await editor
      .getByRole("button", { name: "Preview adjustment", exact: true })
      .click();
    await expect(canvas.locator("image").first()).toHaveAttribute(
      "href",
      /^blob:/,
    );
    await expect(selectOnSecond.getByLabel("Segmentation model")).toBeVisible();
    await editor
      .getByRole("button", { name: "Back to gallery", exact: true })
      .click();
    await expect(
      page.getByLabel("Segmentation model", { exact: true }),
    ).toHaveCount(0);

    await writeFile(
      receipt,
      JSON.stringify(
        {
          ...output,
          neighbor_image_id: secondId,
          ready_box: readyBox,
          reopened: true,
          keyboard_retry: true,
          adjustment_slot_stable: true,
          launcher_closed: true,
        },
        null,
        2,
      ),
    );
  } finally {
    releaseOriginal();
    try {
      if (!page.isClosed()) {
        await page.unroute(original);
        await page.unroute(secondError);
      }
    } finally {
      if (nativeDisplay && !page.isClosed()) {
        await nativeDisplay.send("Emulation.clearDeviceMetricsOverride");
        await nativeDisplay.detach();
      }
    }
  }
});
