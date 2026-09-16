import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

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
  label_classes: [],
};

const image = {
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

test("imports an image and updates leakage-group metadata", async ({
  page,
}) => {
  let imported = false;
  let updated = false;

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
          items: imported
            ? [
                {
                  ...image,
                  ...(updated
                    ? {
                        group_key: "source-01",
                        annotation_status: "reviewed",
                        annotation_revision: 1,
                      }
                    : {}),
                },
              ]
            : [],
          total: imported ? 1 : 0,
          page: 1,
          page_size: 24,
          pages: imported ? 1 : 0,
        },
      });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}/imports/images`) &&
      request.method() === "POST"
    ) {
      imported = true;
      await route.fulfill({
        json: {
          project_id: project.id,
          successful: [
            {
              filename: "swiftia-frame.png",
              relative_path: "swiftia-frame.png",
              status: "successful",
              detail: null,
              image_id: image.id,
              duplicate_image_id: null,
              thumbnail_job_id: "job-1",
            },
          ],
          duplicates: [],
          unsupported: [],
          failed: [],
        },
      });
      return;
    }
    if (
      url.pathname.endsWith(`/images/${image.id}`) &&
      request.method() === "PATCH"
    ) {
      updated = true;
      await route.fulfill({
        json: {
          ...image,
          group_key: "source-01",
          annotation_status: "reviewed",
          annotation_revision: 1,
        },
      });
      return;
    }
    await route.abort();
  });

  const assetDirectory = path.resolve("dist/assets");
  const assets = await readdir(assetDirectory);
  const scriptName = assets.find((name) => name.endsWith(".js"));
  const styleName = assets.find((name) => name.endsWith(".css"));
  if (!scriptName || !styleName)
    throw new Error("Vite build assets are missing");
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

  await page.getByRole("button", { name: /CPT Coral Study/ }).click();
  await expect(
    page.getByRole("heading", { name: "Project gallery" }),
  ).toBeVisible();

  await page.getByLabel("Import files").setInputFiles({
    name: "swiftia-frame.png",
    mimeType: "image/png",
    buffer: Buffer.from("fixture image bytes"),
  });

  await expect(page.getByText("1 files processed")).toBeVisible();
  await expect(page.getByText("swiftia-frame.png")).toBeVisible();
  await page.getByText("Image details").click();
  await page.getByPlaceholder("e.g. source-image-001").fill("source-01");
  await page.getByLabel("Image status").selectOption("reviewed");
  await page.getByRole("button", { name: "Save metadata" }).click();
  await expect(page.getByPlaceholder("e.g. source-image-001")).toHaveValue(
    "source-01",
  );
});
