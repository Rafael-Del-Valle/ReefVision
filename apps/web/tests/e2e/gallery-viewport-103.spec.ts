import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

// Browser-generated JPEG bytes exercise the real camera-image decoder path
// without network fixtures or changing scientific source-image metadata.
test("initial image and gallery scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 820 });

  const makeJpeg = async (width: number, height: number): Promise<Buffer> => {
    const base64 = await page.evaluate(
      ({ width, height }) => {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas context unavailable");
        context.fillStyle = "#407e8c";
        context.fillRect(0, 0, width, height);
        return canvas.toDataURL("image/jpeg", 0.92).split(",")[1];
      },
      { width, height },
    );
    return Buffer.from(base64, "base64");
  };

  const standard = await makeJpeg(1600, 1200);
  const panoramic = await makeJpeg(6000, 400);
  // A mislabeled PNG can pass image-decoding assertions while hiding JPEG
  // compatibility bugs. Require JPEG SOI/EOI markers for both camera shapes.
  for (const jpeg of [standard, panoramic]) {
    expect(jpeg.readUInt16BE(0)).toBe(0xffd8);
    expect(jpeg.readUInt16BE(jpeg.length - 2)).toBe(0xffd9);
  }
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
    // Exercise real-world case-insensitive JPEG filename aliases in the
    // gallery, not just the canonical .JPEG extension.
    original_filename: `camera-${String(index + 1).padStart(2, "0")}.${
      ["JPE", "JFIF", "jfi", "jif"][index - 2] ?? "JPEG"
    }`,
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
  const imageTwoRetryValues: Array<string | null> = [];
  const imageSevenRetryValues: Array<string | null> = [];
  let imageTwoFailures = 0;
  let imageSevenFailures = 0;
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
        if (match[1] === "image-2") {
          imageTwoRetryValues.push(url.searchParams.get("rv_retry"));
          if (imageTwoFailures++ === 0) {
            // An intermittent camera-display endpoint must show a recoverable
            // error rather than an indefinitely obscured first preview.
            await route.fulfill({
              status: 503,
              contentType: "text/plain",
              body: "Camera rendition temporarily unavailable",
            });
            return;
          }
        }
        if (match[1] === "image-7") {
          imageSevenRetryValues.push(url.searchParams.get("rv_retry"));
          if (imageSevenFailures++ === 0) {
            // A server can return HTTP 200 with corrupt camera bytes. The
            // browser must reject the decode rather than report a loaded image.
            await route.fulfill({
              status: 200,
              contentType: "image/jpeg",
              body: Buffer.from("corrupted camera JPEG payload"),
            });
            return;
          }
        }
        await route.fulfill({
          status: 200,
          contentType: "image/jpeg",
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
  // Synthetic WheelEvent assertions below only prove that preventDefault was
  // called. Exercise real mouse-wheel input over the *first* loaded image to
  // catch compositor scrolling that partially displaces the camera preview.
  await focused.hover();
  const initialImageBounds = await focused.boundingBox();
  expect(initialImageBounds).not.toBeNull();
  const initialImageSource = await focused.getAttribute("src");
  const initialPageScroll = await page.evaluate(() => ({
    x: window.scrollX,
    y: window.scrollY,
  }));
  await page.mouse.wheel(0, 320);
  await page.mouse.wheel(220, 0);
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  expect(await focused.boundingBox()).toEqual(initialImageBounds);
  expect(await focused.getAttribute("src")).toBe(initialImageSource);
  expect(
    await page.evaluate(() => ({ x: window.scrollX, y: window.scrollY })),
  ).toEqual(initialPageScroll);
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

  // A WebView2 window may be resized after its first camera image loads.
  // Refit both a standard image and a panorama without stale transforms,
  // unexpected document scrolling, or a change to the focused image.
  await page.setViewportSize({ width: 1024, height: 720 });
  await assertDecodedAndContained(1600, 1200);
  await expect(
    workbench.getByRole("listitem", { name: "Focus camera-01.JPEG" }),
  ).toHaveAttribute("aria-current", "true");
  await focused.hover();
  const resizedImageBounds = await focused.boundingBox();
  const resizedImageSource = await focused.getAttribute("src");
  const resizedPageScroll = await page.evaluate(() => ({
    x: window.scrollX,
    y: window.scrollY,
  }));
  await page.mouse.wheel(0, 360);
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  expect(await focused.boundingBox()).toEqual(resizedImageBounds);
  expect(await focused.getAttribute("src")).toBe(resizedImageSource);
  expect(
    await page.evaluate(() => ({ x: window.scrollX, y: window.scrollY })),
  ).toEqual(resizedPageScroll);

  await lastImage.click();
  await assertDecodedAndContained(6000, 400);
  await page.setViewportSize({ width: 1440, height: 900 });
  await assertDecodedAndContained(6000, 400);
  await workbench.focus();
  await page.keyboard.press("Home");
  await assertDecodedAndContained(1600, 1200);
  await expect(
    workbench.getByRole("listitem", { name: "Focus camera-01.JPEG" }),
  ).toHaveAttribute("aria-current", "true");

  // The gallery must recover from a failed full-resolution JPEG request
  // without changing the selected image or mutating annotation data.
  // Retry must bypass a potentially cached failed WebView2 response.
  const secondImage = workbench.getByRole("listitem", {
    name: "Focus camera-02.JPEG",
  });
  await secondImage.click();
  await expect(workbench.getByRole("alert")).toContainText(
    "Image could not be displayed",
  );
  await expect(secondImage).toHaveAttribute("aria-current", "true");
  await workbench.getByRole("button", { name: "Retry image" }).click();
  await assertDecodedAndContained(1600, 1200);
  await expect(secondImage).toHaveAttribute("aria-current", "true");
  expect(imageTwoRetryValues).toEqual([null, "1"]);
  await expect(workbench.getByRole("alert")).toHaveCount(0);

  // Each accepted JPEG alias must remain selectable and decode genuine JPEG
  // bytes in Chromium, including mixed-case scientific camera filenames.
  for (const [number, extension] of [
    [3, "JPE"],
    [4, "JFIF"],
    [5, "jfi"],
    [6, "jif"],
  ] as const) {
    const aliasImage = workbench.getByRole("listitem", {
      name: `Focus camera-${String(number).padStart(2, "0")}.${extension}`,
    });
    await aliasImage.click();
    await assertDecodedAndContained(1600, 1200);
    await expect(aliasImage).toHaveAttribute("aria-current", "true");
    expect(displayRequests).toContain(`image-${number}`);
  }

  // A 200 response containing invalid camera JPEG bytes must not leave the
  // first preview in a false loaded state. Retry fetches the actual JPEG
  // without replacing or editing the scientific image record.
  const corruptImage = workbench.getByRole("listitem", {
    name: "Focus camera-07.JPEG",
  });
  await corruptImage.click();
  await expect(workbench.getByRole("alert")).toContainText(
    "Image could not be displayed",
  );
  await expect(focused).toHaveCount(0);
  await expect(corruptImage).toHaveAttribute("aria-current", "true");
  await workbench.getByRole("button", { name: "Retry image" }).click();
  await assertDecodedAndContained(1600, 1200);
  await expect(workbench.getByRole("alert")).toHaveCount(0);
  await expect(corruptImage).toHaveAttribute("aria-current", "true");
  expect(imageSevenRetryValues).toEqual([null, "1"]);

  expect(displayRequests).toContain("image-1");
  expect(displayRequests).toContain("image-12");
});
