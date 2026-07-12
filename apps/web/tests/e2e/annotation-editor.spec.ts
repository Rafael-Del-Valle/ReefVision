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
  const scriptName = assets.find((name) => name.endsWith(".js"));
  const styleName = assets.find((name) => name.endsWith(".css"));
  if (!scriptName || !styleName) {
    throw new Error("Vite build assets are missing");
  }
  const [script, style] = await Promise.all([
    readFile(path.join(assetDirectory, scriptName), "utf8"),
    readFile(path.join(assetDirectory, styleName), "utf8"),
  ]);
  await page.setContent('<main id="root"></main>');
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
      await route.fulfill({ json: { status: "ok", version: "1.6.0" } });
      return;
    }
    if (url.pathname.endsWith("/projects") && request.method() === "GET") {
      await route.fulfill({ json: [project] });
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
    page.getByRole("heading", { name: "swiftia-frame.png" }),
  ).toBeVisible();

  const canvas = page.getByTestId("annotation-canvas");
  await canvas.hover();
  await page.mouse.wheel(0, -500);
  const imageBox = await page.locator("svg image").boundingBox();
  if (!imageBox) {
    throw new Error("The editor image did not render");
  }

  const start = {
    x: imageBox.x + imageBox.width * 0.2,
    y: imageBox.y + imageBox.height * 0.25,
  };
  const end = {
    x: imageBox.x + imageBox.width * 0.55,
    y: imageBox.y + imageBox.height * 0.65,
  };

  await page.getByRole("button", { name: "Box (B)" }).click();
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y);
  await page.mouse.up();
  await page.getByRole("button", { name: "Save now" }).click();
  await expect(page.getByTestId("annotation-save-state")).toHaveText("Saved");

  expect(lastSavePayload).not.toBeNull();
  const savedAnnotation = (
    lastSavePayload?.annotations as Array<Record<string, number | string>>
  )[0];
  expect(savedAnnotation.x_min as number).toBeCloseTo(
    ((start.x - imageBox.x) / imageBox.width) * baseImage.width_px,
    1,
  );
  expect(savedAnnotation.y_min as number).toBeCloseTo(
    ((start.y - imageBox.y) / imageBox.height) * baseImage.height_px,
    1,
  );
  expect(savedAnnotation.x_max as number).toBeCloseTo(
    ((end.x - imageBox.x) / imageBox.width) * baseImage.width_px,
    1,
  );
  expect(savedAnnotation.y_max as number).toBeCloseTo(
    ((end.y - imageBox.y) / imageBox.height) * baseImage.height_px,
    1,
  );

  const savedId = String(savedAnnotation.id);
  await page.getByRole("button", { name: "Back to gallery" }).click();
  await page.getByRole("button", { name: "Annotate" }).click();
  await expect(page.getByTestId(`annotation-${savedId}`)).toBeVisible();
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
      await route.fulfill({ json: { status: "ok", version: "1.6.0" } });
      return;
    }
    if (url.pathname.endsWith("/projects") && request.method() === "GET") {
      await route.fulfill({ json: [project] });
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
  await page.getByRole("button", { name: "Box (B)" }).click();

  const imageBox = await page.locator("svg image").boundingBox();
  if (!imageBox) {
    throw new Error("The editor image did not render");
  }
  const start = {
    x: imageBox.x + imageBox.width * 0.3,
    y: imageBox.y + imageBox.height * 0.3,
  };
  const end = {
    x: imageBox.x + imageBox.width * 0.5,
    y: imageBox.y + imageBox.height * 0.5,
  };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y);
  await page.mouse.up();
  await expect(page.locator("[data-testid^='annotation-']")).toHaveCount(1);

  await page.getByRole("button", { name: "Save now" }).click();
  await expect(page.getByTestId("annotation-save-state")).toHaveText(
    /Temporary save failure/,
  );
  await expect(page.locator("[data-testid^='annotation-']")).toHaveCount(1);

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
      await route.fulfill({ json: { status: "ok", version: "1.6.0" } });
      return;
    }
    if (url.pathname.endsWith("/projects") && request.method() === "GET") {
      await route.fulfill({ json: [project] });
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

  const allAnnotations = page.locator("[data-testid^='annotation-']");
  await expect(allAnnotations).toHaveCount(1500, { timeout: 15000 });
  await page.getByTestId("annotation-1").click();
  await expect(page.getByRole("heading", { name: "1 selected" })).toBeVisible();
});
