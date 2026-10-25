import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const pngBytes = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WHdCkUAAAAASUVORK5CYII=",
  "base64",
);

const project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: "Octocoral imagery",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Muricea Closed",
      scientific_name: null,
      state_name: null,
      display_color: "#E76F51",
      is_active: true,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
    {
      id: "class-2",
      project_id: "project-1",
      class_index: 1,
      display_order: 1,
      name: "Muricea Open",
      scientific_name: null,
      state_name: null,
      display_color: "#2A9D8F",
      is_active: true,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
  ],
};

const baseImage = {
  id: "image-1",
  project_id: project.id,
  original_filename: "swiftia-frame.png",
  managed_path: "projects/project-1/images/originals/image-1.png",
  thumbnail_path: null,
  sha256: "a".repeat(64),
  width_px: 1600,
  height_px: 1200,
  file_size_bytes: 2048,
  media_type: "image/png",
  import_source: "trial/swiftia-frame.png",
  capture_timestamp: null,
  group_key: null,
  metadata_json: {},
  annotation_status: "unannotated",
  annotation_revision: 0,
  annotation_count: 0,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
};

async function mountBuiltApp(page: Parameters<typeof test>[0]["page"]) {
  const assetDirectory = path.resolve("dist/assets");
  const assets = await readdir(assetDirectory);
  const scriptName = assets.find(
    (name) => name.startsWith("index-") && name.endsWith(".js"),
  );
  const styleName = assets.find((name) => name.endsWith(".css"));
  if (!scriptName || !styleName) {
    throw new Error("Vite build assets are missing");
  }
  const [script, style] = await Promise.all([
    readFile(path.join(assetDirectory, scriptName), "utf8"),
    readFile(path.join(assetDirectory, styleName), "utf8"),
  ]);
  await page.route("http://127.0.0.1:8000/", async (route) => {
    await route.fulfill({
      contentType: "text/html",
      body: '<main id="root"></main>',
    });
  });
  await page.goto("http://127.0.0.1:8000/");
  const packageMetadata = JSON.parse(
    await readFile(path.resolve("package.json"), "utf8"),
  ) as { version: string };
  await page.evaluate((version) => {
    window.localStorage.setItem(
      `reefvision.onboarding.dismissed.${version}`,
      "true",
    );
  }, packageMetadata.version);
  await page.addStyleTag({ content: style });
  await page.addScriptTag({ content: script, type: "module" });
}

test("stores source-image coordinates correctly after zooming and reloads saved boxes", async ({
  page,
}) => {
  let lastSavePayload: Record<string, unknown> | null = null;
  let sessionState = {
    image: { ...baseImage },
    label_classes: project.label_classes,
    annotations: [] as Array<Record<string, unknown>>,
    counts_by_class: project.label_classes.map((labelClass) => ({
      label_class_id: labelClass.id,
      count: 0,
    })),
    previous_image_id: null,
    next_image_id: null,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.1" } });
      return;
    }
    if (
      url.pathname.endsWith("/project-summaries") &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: [
          {
            id: project.id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            storage_root: project.storage_root,
            default_annotation_type: project.default_annotation_type,
            created_at: project.created_at,
            updated_at: project.updated_at,
            archived_at: project.archived_at,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: project });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
      await route.fulfill({
        json: {
          items: [sessionState.image],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/annotations`)) {
      if (request.method() === "GET") {
        await route.fulfill({ json: sessionState });
        return;
      }
      const payload = request.postDataJSON() as {
        annotation_status: string;
        annotations: Array<{
          id: string;
          label_class_id: string;
          x_min: number;
          y_min: number;
          x_max: number;
          y_max: number;
        }>;
      };
      lastSavePayload = payload as unknown as Record<string, unknown>;
      sessionState = {
        ...sessionState,
        image: {
          ...sessionState.image,
          annotation_status: payload.annotation_status,
          annotation_revision: sessionState.image.annotation_revision + 1,
          annotation_count: payload.annotations.length,
        },
        annotations: payload.annotations.map((annotation) => ({
          ...annotation,
          image_id: baseImage.id,
          source_type: "human",
          source_model_id: null,
          source_prediction_id: null,
          created_by: "local_user",
          created_at: "2026-07-08T00:00:00Z",
          updated_at: "2026-07-08T00:00:00Z",
          deleted_at: null,
          revision: 1,
        })),
        counts_by_class: project.label_classes.map((labelClass) => ({
          label_class_id: labelClass.id,
          count: payload.annotations.filter(
            (annotation) => annotation.label_class_id === labelClass.id,
          ).length,
        })),
      };
      await route.fulfill({
        json: {
          image: sessionState.image,
          annotations: sessionState.annotations,
          counts_by_class: sessionState.counts_by_class,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/content`)) {
      await route.fulfill({
        body: pngBytes,
        contentType: "image/png",
      });
      return;
    }
    await route.abort();
  });

  await mountBuiltApp(page);
  await page.getByRole("button", { name: /CPT Coral Study/ }).click();
  await page.getByRole("button", { name: "Annotate" }).click();
  await expect(
    page
      .getByTestId("annotation-editor")
      .getByRole("heading", { name: "swiftia-frame.png" }),
  ).toBeVisible();

  const canvas = page.getByTestId("annotation-canvas");
  const viewportGroup = canvas.locator("g").first();
  const transformBeforeZoom = await viewportGroup.getAttribute("transform");

  await canvas.hover();
  await page.mouse.wheel(0, -500);

  await expect
    .poll(() => viewportGroup.getAttribute("transform"))
    .not.toBe(transformBeforeZoom);
  const geometry = await page
    .getByTestId("annotation-canvas")
    .evaluate((svg) => {
      if (!(svg instanceof SVGSVGElement)) {
        throw new Error("Annotation canvas is not an SVG element");
      }

      const viewportGroup = svg.querySelector<SVGGElement>("g");
      const canvasRect = svg.getBoundingClientRect();
      const matrix = viewportGroup?.transform.baseVal.consolidate()?.matrix;

      if (
        !viewportGroup ||
        !matrix ||
        canvasRect.width <= 0 ||
        canvasRect.height <= 0
      ) {
        throw new Error("Annotation canvas geometry is unavailable");
      }

      const startLocal = {
        x: canvasRect.width * 0.35,
        y: canvasRect.height * 0.35,
      };
      const endLocal = {
        x: canvasRect.width * 0.65,
        y: canvasRect.height * 0.65,
      };

      const start = {
        x: canvasRect.left + startLocal.x,
        y: canvasRect.top + startLocal.y,
      };
      const end = {
        x: canvasRect.left + endLocal.x,
        y: canvasRect.top + endLocal.y,
      };

      const inverse = matrix.inverse();
      const sourceStartPoint = new DOMPoint(
        startLocal.x,
        startLocal.y,
      ).matrixTransform(inverse);
      const sourceEndPoint = new DOMPoint(
        endLocal.x,
        endLocal.y,
      ).matrixTransform(inverse);

      return {
        start,
        end,
        sourceStart: {
          x: sourceStartPoint.x,
          y: sourceStartPoint.y,
        },
        sourceEnd: {
          x: sourceEndPoint.x,
          y: sourceEndPoint.y,
        },
      };
    });

  const { start, end, sourceStart, sourceEnd } = geometry;

  await page.getByRole("button", { name: "Box tool" }).click();
  await expect(page.getByTestId("annotation-canvas")).toHaveClass(/tool-box/);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 10 });

  await expect(
    page.getByTestId("annotation-canvas").locator("rect[stroke-dasharray]"),
  ).toHaveCount(1);

  await page.mouse.up();
  await expect(
    page
      .getByTestId("annotation-canvas")
      .locator("[data-testid^='annotation-']"),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "Save now" }).click();
  await expect(page.getByTestId("annotation-save-state")).toHaveText("Saved");

  expect(lastSavePayload).not.toBeNull();
  const savedAnnotation = (
    lastSavePayload?.annotations as Array<Record<string, number | string>>
  )[0];
  expect(savedAnnotation.x_min as number).toBeCloseTo(
    Math.min(sourceStart.x, sourceEnd.x),
    1,
  );
  expect(savedAnnotation.y_min as number).toBeCloseTo(
    Math.min(sourceStart.y, sourceEnd.y),
    1,
  );
  expect(savedAnnotation.x_max as number).toBeCloseTo(
    Math.max(sourceStart.x, sourceEnd.x),
    1,
  );
  expect(savedAnnotation.y_max as number).toBeCloseTo(
    Math.max(sourceStart.y, sourceEnd.y),
    1,
  );

  const savedId = String(savedAnnotation.id);
  const savedBox = canvas.getByTestId(`annotation-${savedId}`);
  await expect(savedBox).toBeVisible();

  // Acceptance coverage for Alt+drag panning: the viewport changes, while the
  // persisted source rectangle geometry remains identical.
  const sourceGeometryBeforePan = await savedBox.evaluate((element) => ({
    x: element.getAttribute("x"),
    y: element.getAttribute("y"),
    width: element.getAttribute("width"),
    height: element.getAttribute("height"),
  }));
  const transformBeforePan = await viewportGroup.getAttribute("transform");
  const canvasBounds = await canvas.boundingBox();
  if (!canvasBounds) {
    throw new Error("Annotation canvas bounds unavailable for Alt+drag");
  }
  const panStart = {
    x: canvasBounds.x + canvasBounds.width * 0.25,
    y: canvasBounds.y + canvasBounds.height * 0.25,
  };
  await page.mouse.move(panStart.x, panStart.y);
  await page.keyboard.down("Alt");
  await page.mouse.down();
  await page.mouse.move(panStart.x + 32, panStart.y + 22, { steps: 5 });
  await page.mouse.up();
  await page.keyboard.up("Alt");
  await expect
    .poll(() => viewportGroup.getAttribute("transform"))
    .not.toBe(transformBeforePan);
  expect(
    await savedBox.evaluate((element) => ({
      x: element.getAttribute("x"),
      y: element.getAttribute("y"),
      width: element.getAttribute("width"),
      height: element.getAttribute("height"),
    })),
  ).toEqual(sourceGeometryBeforePan);

  // Acceptance coverage for clipboard/re-review on the real browser bundle.
  await page.getByRole("button", { name: "Select tool" }).click();
  await page.getByLabel("Annotation status").selectOption("reviewed");
  await expect(page.getByLabel("Annotation status")).toHaveValue("reviewed");
  await savedBox.dispatchEvent("pointerdown", {
    button: 0,
    buttons: 1,
    pointerId: 1,
    pointerType: "mouse",
  });
  // The status dropdown retains keyboard focus after selection, so blur it
  // before sending editor shortcuts; form controls must not capture Ctrl+C/V.
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  });
  await page.keyboard.press("Control+c");
  await page.keyboard.press("Control+v");
  await expect(canvas.locator("[data-testid^='annotation-']")).toHaveCount(2);
  await expect(page.getByLabel("Annotation status")).toHaveValue("in_progress");
  await page.getByRole("button", { name: "Save now" }).click();
  await expect(page.getByTestId("annotation-save-state")).toHaveText("Saved");
  expect(lastSavePayload?.annotation_status).toBe("in_progress");
  expect(lastSavePayload?.annotations).toHaveLength(2);

  await page.getByRole("button", { name: "Back to gallery" }).click();

  await mountBuiltApp(page);
  await page.getByRole("button", { name: /CPT Coral Study/ }).click();
  await page.getByRole("button", { name: "Annotate" }).click();

  await expect(
    page.getByTestId("annotation-canvas").getByTestId(`annotation-${savedId}`),
  ).toBeVisible();
});

test("keeps unsaved boxes visible after a failed save and allows retry", async ({
  page,
}) => {
  let failNextSave = true;
  let sessionState = {
    image: { ...baseImage },
    label_classes: project.label_classes,
    annotations: [] as Array<Record<string, unknown>>,
    counts_by_class: project.label_classes.map((labelClass) => ({
      label_class_id: labelClass.id,
      count: 0,
    })),
    previous_image_id: null,
    next_image_id: null,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.1" } });
      return;
    }
    if (
      url.pathname.endsWith("/project-summaries") &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: [
          {
            id: project.id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            storage_root: project.storage_root,
            default_annotation_type: project.default_annotation_type,
            created_at: project.created_at,
            updated_at: project.updated_at,
            archived_at: project.archived_at,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: project });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
      await route.fulfill({
        json: {
          items: [sessionState.image],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/annotations`)) {
      if (request.method() === "GET") {
        await route.fulfill({ json: sessionState });
        return;
      }
      if (failNextSave) {
        failNextSave = false;
        await route.fulfill({
          status: 500,
          json: { detail: "Temporary save failure" },
        });
        return;
      }
      const payload = request.postDataJSON() as {
        annotation_status: string;
        annotations: Array<{
          id: string;
          label_class_id: string;
          x_min: number;
          y_min: number;
          x_max: number;
          y_max: number;
        }>;
      };
      sessionState = {
        ...sessionState,
        image: {
          ...sessionState.image,
          annotation_status: payload.annotation_status,
          annotation_revision: sessionState.image.annotation_revision + 1,
          annotation_count: payload.annotations.length,
        },
        annotations: payload.annotations.map((annotation) => ({
          ...annotation,
          image_id: baseImage.id,
          source_type: "human",
          source_model_id: null,
          source_prediction_id: null,
          created_by: "local_user",
          created_at: "2026-07-08T00:00:00Z",
          updated_at: "2026-07-08T00:00:00Z",
          deleted_at: null,
          revision: 1,
        })),
        counts_by_class: project.label_classes.map((labelClass) => ({
          label_class_id: labelClass.id,
          count: payload.annotations.filter(
            (annotation) => annotation.label_class_id === labelClass.id,
          ).length,
        })),
      };
      await route.fulfill({
        json: {
          image: sessionState.image,
          annotations: sessionState.annotations,
          counts_by_class: sessionState.counts_by_class,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/content`)) {
      await route.fulfill({
        body: pngBytes,
        contentType: "image/png",
      });
      return;
    }
    await route.abort();
  });

  await mountBuiltApp(page);
  await page.getByRole("button", { name: /CPT Coral Study/ }).click();
  await page.getByRole("button", { name: "Annotate" }).click();
  await page.getByRole("button", { name: "Box tool" }).click();
  await expect(page.getByTestId("annotation-canvas")).toHaveClass(/tool-box/);

  const geometry = await page
    .getByTestId("annotation-canvas")
    .evaluate((svg) => {
      if (!(svg instanceof SVGSVGElement)) {
        throw new Error("Annotation canvas is not an SVG element");
      }

      const viewportGroup = svg.querySelector<SVGGElement>("g");
      const canvasRect = svg.getBoundingClientRect();
      const matrix = viewportGroup?.transform.baseVal.consolidate()?.matrix;

      if (
        !viewportGroup ||
        !matrix ||
        canvasRect.width <= 0 ||
        canvasRect.height <= 0
      ) {
        throw new Error("Annotation canvas geometry is unavailable");
      }

      const startLocal = {
        x: canvasRect.width * 0.35,
        y: canvasRect.height * 0.35,
      };
      const endLocal = {
        x: canvasRect.width * 0.65,
        y: canvasRect.height * 0.65,
      };

      const start = {
        x: canvasRect.left + startLocal.x,
        y: canvasRect.top + startLocal.y,
      };
      const end = {
        x: canvasRect.left + endLocal.x,
        y: canvasRect.top + endLocal.y,
      };

      const inverse = matrix.inverse();
      const sourceStartPoint = new DOMPoint(
        startLocal.x,
        startLocal.y,
      ).matrixTransform(inverse);
      const sourceEndPoint = new DOMPoint(
        endLocal.x,
        endLocal.y,
      ).matrixTransform(inverse);

      return {
        start,
        end,
        sourceStart: {
          x: sourceStartPoint.x,
          y: sourceStartPoint.y,
        },
        sourceEnd: {
          x: sourceEndPoint.x,
          y: sourceEndPoint.y,
        },
      };
    });

  const { start, end, sourceStart, sourceEnd } = geometry;
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 10 });

  await expect(
    page.getByTestId("annotation-canvas").locator("rect[stroke-dasharray]"),
  ).toHaveCount(1);

  await page.mouse.up();
  await expect(
    page
      .getByTestId("annotation-canvas")
      .locator("[data-testid^='annotation-']"),
  ).toHaveCount(1);

  await page.getByRole("button", { name: "Save now" }).click();
  await expect(page.getByTestId("annotation-save-state")).toHaveText(
    /Temporary save failure/,
  );
  await expect(
    page
      .getByTestId("annotation-canvas")
      .locator("[data-testid^='annotation-']"),
  ).toHaveCount(1);

  await page.getByRole("button", { name: "Retry save" }).click();
  await expect(page.getByTestId("annotation-save-state")).toHaveText("Saved");
});

test("renders and selects from a 1500-annotation image", async ({ page }) => {
  const annotations = Array.from({ length: 1500 }, (_, index) => ({
    id: `annotation-${index + 1}`,
    image_id: baseImage.id,
    label_class_id: index % 2 === 0 ? "class-1" : "class-2",
    x_min: (index % 30) * 40,
    y_min: Math.floor(index / 30) * 20,
    x_max: (index % 30) * 40 + 24,
    y_max: Math.floor(index / 30) * 20 + 16,
    source_type: "human",
    source_model_id: null,
    source_prediction_id: null,
    created_by: "local_user",
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
    deleted_at: null,
    revision: 1,
  }));

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.1" } });
      return;
    }
    if (
      url.pathname.endsWith("/project-summaries") &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: [
          {
            id: project.id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            storage_root: project.storage_root,
            default_annotation_type: project.default_annotation_type,
            created_at: project.created_at,
            updated_at: project.updated_at,
            archived_at: project.archived_at,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: project });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
      await route.fulfill({
        json: {
          items: [{ ...baseImage, annotation_count: annotations.length }],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/annotations`)) {
      await route.fulfill({
        json: {
          image: {
            ...baseImage,
            annotation_count: annotations.length,
          },
          label_classes: project.label_classes,
          annotations,
          counts_by_class: [
            { label_class_id: "class-1", count: 750 },
            { label_class_id: "class-2", count: 750 },
          ],
          previous_image_id: null,
          next_image_id: null,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/content`)) {
      await route.fulfill({
        body: pngBytes,
        contentType: "image/png",
      });
      return;
    }
    await route.abort();
  });

  await mountBuiltApp(page);
  await page.getByRole("button", { name: /CPT Coral Study/ }).click();
  await page.getByRole("button", { name: "Annotate" }).click();

  const allAnnotations = page
    .getByTestId("annotation-canvas")
    .locator("[data-testid^='annotation-']");
  // 1.6 viewport culling intentionally renders only in-view SVG boxes.
  // The complete 1,500-observation dataset must still be available for
  // selection, review and saving; never treat rendered SVG count as total.
  await expect
    .poll(() => allAnnotations.count(), { timeout: 15000 })
    .toBeGreaterThan(0);
  await expect
    .poll(() => allAnnotations.count(), { timeout: 15000 })
    .toBeLessThan(annotations.length);
  const objectOptions = page
    .getByRole("listbox", { name: "Objects" })
    .getByRole("option");
  await expect(objectOptions).toHaveCount(annotations.length);

  await allAnnotations.first().dispatchEvent("pointerdown", {
    button: 0,
    buttons: 1,
    clientX: 1,
    clientY: 1,
    pointerId: 1,
    pointerType: "mouse",
  });
  await expect(page.getByRole("heading", { name: "1 selected" })).toBeVisible();
  // A box omitted from the viewport SVG remains selectable from the full
  // object list. Display culling must never discard the source annotation.
  await objectOptions.last().click();
  await expect(objectOptions.last()).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "1 selected" })).toBeVisible();
});

test("renders the first opened image after a deliberately delayed display response", async ({
  page,
}) => {
  // Generate a real decodable image at source resolution inside Chromium.
  // This avoids hand-copied PNG fixtures with invalid pixel data.
  const sourceSizedPngBytes = Buffer.from(
    await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 1600;
      canvas.height = 1200;
      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error(
          "Unable to create a source image for the first-open test",
        );
      }
      context.fillStyle = "#dfdfdf";
      context.fillRect(0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/png").split(",")[1];
    }),
    "base64",
  );
  const gate: { release: () => void } = { release: () => undefined };
  const imageGate = new Promise<void>((resolve) => {
    gate.release = resolve;
  });
  let displayRequests = 0;
  const firstOpenBox = {
    id: "first-open-box",
    image_id: baseImage.id,
    label_class_id: "class-1",
    x_min: 160,
    y_min: 120,
    x_max: 320,
    y_max: 240,
    source_type: "human",
    source_model_id: null,
    source_prediction_id: null,
    created_by: "local_user",
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
    deleted_at: null,
    revision: 1,
  };
  const sessionState = {
    image: {
      ...baseImage,
      annotation_count: 1,
      annotation_status: "in_progress",
    },
    label_classes: project.label_classes,
    annotations: [firstOpenBox],
    counts_by_class: project.label_classes.map((labelClass) => ({
      label_class_id: labelClass.id,
      count: labelClass.id === "class-1" ? 1 : 0,
    })),
    previous_image_id: null,
    next_image_id: null,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.2" } });
      return;
    }
    if (
      url.pathname.endsWith("/project-summaries") &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: [
          {
            ...project,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: project });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
      await route.fulfill({
        json: {
          items: [sessionState.image],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        },
      });
      return;
    }
    if (
      url.pathname.endsWith(`/images/${baseImage.id}/annotations`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: sessionState });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/display`)) {
      displayRequests += 1;
      await imageGate;
      await route.fulfill({
        body: sourceSizedPngBytes,
        contentType: "image/png",
      });
      return;
    }
    await route.abort();
  });

  try {
    await mountBuiltApp(page);
    await page.getByRole("button", { name: /CPT Coral Study/ }).click();
    await page.getByRole("button", { name: "Annotate" }).click();

    const canvas = page.getByTestId("annotation-canvas");
    await expect(canvas).toBeVisible();
    const loading = page
      .getByTestId("annotation-editor")
      .getByText("Loading full-resolution image...");
    await expect(loading).toBeVisible();
    await expect(canvas.locator("image").first()).toHaveAttribute(
      "href",
      /\/images\/image-1\/display/,
    );
    await expect.poll(() => displayRequests).toBeGreaterThan(0);
    const initialViewport = await canvas.boundingBox();
    expect(initialViewport?.width).toBeGreaterThan(0);
    expect(initialViewport?.height).toBeGreaterThan(0);

    gate.release();
    await expect(loading).toBeHidden();
    await expect(
      page.getByText("Full-resolution image could not load"),
    ).toHaveCount(0);
    // Persisted annotation geometry must align on the first opened image,
    // without needing to leave the gallery and reenter the editor.
    await expect(canvas).toBeVisible();
    await expect(canvas.locator("image").first()).toHaveAttribute(
      "href",
      /\/images\/image-1\/display/,
    );
    const firstOpenOverlay = canvas.getByTestId("annotation-first-open-box");
    await expect(firstOpenOverlay).toBeVisible();
    await expect(firstOpenOverlay).toHaveAttribute("x", "160");
    await expect(firstOpenOverlay).toHaveAttribute("y", "120");
    await expect(firstOpenOverlay).toHaveAttribute("width", "160");
    await expect(firstOpenOverlay).toHaveAttribute("height", "120");
    const decodedDimensions = await page.evaluate(async () => {
      const image = document.querySelector(
        '[data-testid="annotation-canvas"] image',
      );
      const href = image?.getAttribute("href");
      if (!href) {
        throw new Error(
          "The source image is not attached to the annotation canvas",
        );
      }
      const response = await fetch(href);
      if (!response.ok) {
        throw new Error("The displayed source image could not be fetched");
      }
      const bitmap = await createImageBitmap(await response.blob());
      const dimensions = { width: bitmap.width, height: bitmap.height };
      bitmap.close();
      return dimensions;
    });
    expect(decodedDimensions).toEqual({ width: 1600, height: 1200 });
  } finally {
    gate.release();
  }
});
