import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

// Browser-generated, decodable PNGs exercise the viewer without requiring
// network image fixtures or changing scientific source-image metadata.
test("initial image and gallery scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 820 });

  const makePng = async (width: number, height: number): Promise<Buffer> => {
    const base64 = await page.evaluate(
      ({ width, height }) => {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas context unavailable");
        context.fillStyle = "#407e8c";
        context.fillRect(0, 0, width, height);
        return canvas.toDataURL("image/png").split(",")[1];
      },
      { width, height },
    );
    return Buffer.from(base64, "base64");
  };

  const standard = await makePng(1600, 1200);
  const panoramic = await makePng(6000, 400);
  const project = {
    id: "project-1",
    name: "CPT Coral Study",
    slug: "cpt-coral-study",
    description: "Gallery rendering regression",
    storage_root: "projects/project-1",
    default_annotation_type: "bbox",
    label_classes: [],
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
    archived_at: null,
  };
  const images = Array.from({ length: 12 }, (_, index) => ({
    id: "image-" + (index + 1),
    project_id: project.id,
    original_filename: `camera-${String(index + 1).padStart(2, "0")}.JPEG`,
    managed_path: `projects/project-1/images/originals/camera-${index + 1}.jpg`,
    thumbnail_path: null,
    sha256: "a".repeat(64),
    width_px: index === 11 ? 6000 : 1600,
    height_px: index === 11 ? 400 : 1200,
    file_size_bytes: 1024,
    media_type: "image/jpeg",
    import_source: "camera",
    capture_timestamp: null,
    group_key: null,
    metadata_json: {},
    annotation_status: "unannotated",
    annotation_revision: 0,
    annotation_count: 0,
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
  }));

  const displayRequests: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.3" } });
    } else if (url.pathname.endsWith("/project-summaries")) {
      await route.fulfill({
        json: [
          {
            ...project,
            label_class_count: 0,
            active_label_class_count: 0,
          },
        ],
      });
    } else if (url.pathname.endsWith("/projects/" + project.id)) {
      await route.fulfill({ json: project });
    } else if (url.pathname.endsWith("/projects/" + project.id + "/images")) {
      await route.fulfill({
        json: { items: images, total: 12, page: 1, page_size: 24, pages: 1 },
      });
    } else {
      const match = url.pathname.match(/\/images\/(image-\d+)\/display$/);
      if (match) {
        displayRequests.push(match[1]);
        await route.fulfill({
          status: 200,
          contentType: "image/png",
          body: match[1] === "image-12" ? panoramic : standard,
        });
      } else {
        await route.abort();
      }
    }
  });

  const assetDirectory = path.resolve("dist/assets");
  const assets = await readdir(assetDirectory);
  const scriptName = assets.find(
    (name) => name.startsWith("index-") && name.endsWith(".js"),
  );
  const styleName = assets.find((name) => name.endsWith(".css"));
  if (!scriptName || !styleName) {
    throw new Error("Built Vite assets are missing");
  }

  const [script, style] = await Promise.all([
    readFile(path.join(assetDirectory, scriptName), "utf8"),
    readFile(path.join(assetDirectory, styleName), "utf8"),
  ]);
  await page.route("http://127.0.0.1:8000/", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<main id="root"></main>',
    }),
  );
  await page.goto("http://127.0.0.1:8000/");

  const packageJson = await readFile(path.resolve("package.json"), "utf8");
  const pkg: { version: string } = JSON.parse(packageJson);
  await page.evaluate((version) => {
    const onboardingKey = "reefvision.onboarding.dismissed." + version;
    window.localStorage.setItem(onboardingKey, "true");
  }, pkg.version);
  await page.addStyleTag({ content: style });
  await page.addScriptTag({ content: script, type: "module" });
  await page.getByRole("button", { name: /CPT Coral Study/ }).click();

  const workbench = page.getByRole("region", { name: "Image workbench" });
  const focused = workbench.locator(".rv-media-canvas img");
  const assertDecodedAndContained = async (width: number, height: number) => {
    await expect(focused).toBeVisible();
    const decodedImage = () =>
      focused.evaluate((img: HTMLImageElement) => ({
        complete: img.complete,
        width: img.naturalWidth,
        height: img.naturalHeight,
      }));
    await expect.poll(decodedImage).toEqual({ complete: true, width, height });
    await expect(
      workbench.getByText("Loading full-resolution image..."),
    ).toHaveCount(0);

    const bounds = await workbench.evaluate((element) => {
      const canvas = element
        .querySelector(".rv-media-canvas")!
        .getBoundingClientRect();
      const image = element
        .querySelector(".rv-media-canvas img")!
        .getBoundingClientRect();
      return {
        canvas: {
          left: canvas.left,
          right: canvas.right,
          top: canvas.top,
          bottom: canvas.bottom,
        },
        image: {
          left: image.left,
          right: image.right,
          top: image.top,
          bottom: image.bottom,
        },
      };
    });
    expect(bounds.image.left).toBeGreaterThanOrEqual(bounds.canvas.left - 1);
    expect(bounds.image.right).toBeLessThanOrEqual(bounds.canvas.right + 1);
    expect(bounds.image.top).toBeGreaterThanOrEqual(bounds.canvas.top - 1);
    expect(bounds.image.bottom).toBeLessThanOrEqual(bounds.canvas.bottom + 1);
  };

  await assertDecodedAndContained(1600, 1200);
  // Exercise the native non-passive listener in a real Chromium page, not just
  // jsdom. Prevent wheel-driven WebView2 page movement over the preview while
  // leaving browser zoom modifiers and zero-delta events untouched.
  const previewWheelPolicy = () =>
    workbench.locator(".rv-media-canvas").evaluate((canvas) => {
      const prevented = (init: WheelEventInit) => {
        const event = new WheelEvent("wheel", {
          bubbles: true,
          cancelable: true,
          ...init,
        });
        canvas.dispatchEvent(event);
        return event.defaultPrevented;
      };
      return {
        vertical: prevented({ deltaY: 160 }),
        horizontal: prevented({ deltaX: 160 }),
        ctrlZoom: prevented({ deltaY: 160, ctrlKey: true }),
        metaZoom: prevented({ deltaY: 160, metaKey: true }),
        zeroDelta: prevented({}),
      };
    });
  const expectedPreviewWheelPolicy = {
    vertical: true,
    horizontal: true,
    ctrlZoom: false,
    metaZoom: false,
    zeroDelta: false,
  };
  expect(await previewWheelPolicy()).toEqual(expectedPreviewWheelPolicy);
  const lastImage = workbench.getByRole("listitem", {
    name: "Focus camera-12.JPEG",
  });
  await lastImage.click();
  await assertDecodedAndContained(6000, 400);
  expect(await previewWheelPolicy()).toEqual(expectedPreviewWheelPolicy);
  const filmstrip = workbench.locator(".rv-media-filmstrip");
  // The strip converts ordinary wheel movement to horizontal browsing, but
  // must not intercept Ctrl/Meta browser zoom gestures.
  const filmstripWheelPolicy = () =>
    filmstrip.evaluate((element) => {
      const prevented = (init: WheelEventInit) => {
        const event = new WheelEvent("wheel", {
          bubbles: true,
          cancelable: true,
          ...init,
        });
        element.dispatchEvent(event);
        return event.defaultPrevented;
      };
      return {
        vertical: prevented({ deltaY: 160 }),
        horizontal: prevented({ deltaX: 160 }),
        ctrlZoom: prevented({ deltaY: 160, ctrlKey: true }),
        metaZoom: prevented({ deltaY: 160, metaKey: true }),
        zeroDelta: prevented({}),
      };
    });
  expect(await filmstripWheelPolicy()).toEqual({
    vertical: true,
    horizontal: true,
    ctrlZoom: false,
    metaZoom: false,
    zeroDelta: false,
  });
  const scrollOffset = () =>
    filmstrip.evaluate((element) => element.scrollLeft);
  // Keyboard navigation must not scroll the document or partially displace
  // the main image. Only the horizontal thumbnail filmstrip may move.
  await workbench.focus();
  const documentScrollBeforeNavigation = await page.evaluate(
    () => window.scrollY,
  );
  await page.keyboard.press("Home");
  await assertDecodedAndContained(1600, 1200);
  await expect(
    workbench.getByRole("listitem", { name: "Focus camera-01.JPEG" }),
  ).toHaveAttribute("aria-current", "true");
  expect(await page.evaluate(() => window.scrollY)).toBe(
    documentScrollBeforeNavigation,
  );
  await page.keyboard.press("End");
  await assertDecodedAndContained(6000, 400);
  expect(await page.evaluate(() => window.scrollY)).toBe(
    documentScrollBeforeNavigation,
  );
  await page.keyboard.press("Home");
  await assertDecodedAndContained(1600, 1200);
  expect(await page.evaluate(() => window.scrollY)).toBe(
    documentScrollBeforeNavigation,
  );
  // Mouse-wheel input over the filmstrip must scroll thumbnails horizontally
  // without moving the page or clipping the initial full-resolution image.
  await filmstrip.hover();
  // Hover may align a focused thumbnail a few pixels into view; verify
  // wheel-driven movement relative to the post-hover position.
  const scrollBeforeWheel = await scrollOffset();
  const documentScrollBeforeWheel = await page.evaluate(() => window.scrollY);
  await page.mouse.wheel(0, 280);
  await expect.poll(scrollOffset).toBeGreaterThan(scrollBeforeWheel);
  expect(await page.evaluate(() => window.scrollY)).toBe(
    documentScrollBeforeWheel,
  );
  await assertDecodedAndContained(1600, 1200);

  expect(displayRequests).toContain("image-1");
  expect(displayRequests).toContain("image-12");
});
