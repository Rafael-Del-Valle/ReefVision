import { expect } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { test } from "./spatialDesktop";

test("imports an image and video, persists a reviewed edit, and exports YOLO", async ({
  desktop,
}, info) => {
  const { page, api, web } = desktop;
  const firstUse = process.env.REEFVISION_FIRST_USE_ACCEPTANCE === "1";
  const outsideLoopback = new Set<string>();
  page.setDefaultTimeout(15_000);
  if (desktop.surface === "source-browser") {
    await page.setViewportSize({ width: 1440, height: 960 });
  }
  const name = `Synthetic ordinary 2D ${randomUUID().slice(0, 8)}`;
  const basename = "field-still-fixture.png";
  const image = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
    "base64",
  );
  const hash = (bytes: Buffer) =>
    createHash("sha256").update(bytes).digest("hex");
  const post = (url: string) =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" && response.url() === url,
    );
  const json = async (url: string) => (await page.request.get(url)).json();
  const device = firstUse ? await page.context().newCDPSession(page) : null;
  const scale = 1.5;
  if (device) {
    const localOrigins = new Set([new URL(api).origin, new URL(web).origin]);
    await page.route(/^https?:\/\//, (route) => {
      const origin = new URL(route.request().url()).origin;
      if (localOrigins.has(origin)) return route.continue();
      outsideLoopback.add(origin);
      return route.abort("internetdisconnected");
    });
    await device.send("Emulation.setDeviceMetricsOverride", {
      width: 960,
      height: 640,
      deviceScaleFactor: scale,
      mobile: false,
    });
  } else {
    await page.addInitScript(() =>
      localStorage.setItem("reefvision.onboarding.dismissed.1.5.0", "true"),
    );
  }
  const openProject = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  };
  let project;
  let label;
  if (firstUse) {
    expect(await json(`${api}/project-summaries`)).toEqual([]);
    await page.goto(web);
    expect(await page.evaluate(() => window.devicePixelRatio)).toBe(scale);
    const welcome = page.getByRole("dialog", { name: /Welcome to ReefVision/ });
    await expect(welcome).toBeVisible();
    const close = welcome.getByRole("button", { name: "Close", exact: true });
    await expect(close).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(
      welcome.getByRole("button", { name: "Don't show on startup" }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(close).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(
      welcome.getByRole("button", { name: "Create a project" }),
    ).toBeFocused();
    await page.keyboard.press("Enter");
    const form = page.getByRole("dialog", { name: "Create project" });
    const projectName = form.getByRole("textbox", { name: "Project name" });
    await expect(projectName).toBeFocused();
    expect(await json(`${api}/project-summaries`)).toEqual([]);
    await page.keyboard.type(name);
    const creating = post(`${api}/projects`);
    await page.keyboard.press("Enter");
    const created = await creating;
    expect(created.status(), await created.text()).toBe(201);
    project = await created.json();
    await page.getByRole("tab", { name: "Classes", exact: true }).click();
    const newClass = page.locator("form").filter({
      has: page.getByRole("heading", { name: "Add annotation class" }),
    });
    await newClass
      .getByRole("textbox", { name: "Name", exact: true })
      .fill("Fixture animal");
    const adding = post(`${api}/projects/${project.id}/classes`);
    await newClass
      .getByRole("button", { name: "Add class", exact: true })
      .click();
    const category = await adding;
    expect(category.status(), await category.text()).toBe(201);
    label = await category.json();
    await page.getByRole("button", { name: "Help", exact: true }).click();
    await welcome
      .getByRole("button", { name: "Don't show on startup" })
      .click();
    await openProject();
    await expect(welcome).toHaveCount(0);
  } else {
    const created = await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    });
    expect(created.status()).toBe(201);
    project = await created.json();
    const category = await page.request.post(
      `${api}/projects/${project.id}/classes`,
      {
        data: {
          class_index: 0,
          name: "Fixture animal",
          display_color: "#28A95C",
        },
      },
    );
    expect(category.status()).toBe(201);
    label = await category.json();
    await openProject();
  }
  const root = `${api}/projects/${project.id}`;
  const importing = post(`${root}/imports/images`);
  await page
    .getByLabel("Import files", { exact: true })
    .setInputFiles({ name: basename, mimeType: "image/png", buffer: image });
  const imported = await importing;
  expect(imported.status(), await imported.text()).toBe(200);
  const images = await imported.json();
  expect(images.successful, JSON.stringify(images)).toHaveLength(1);
  const imageId = images.successful[0].image_id;
  const annotate = () =>
    page
      .getByRole("article", { name: new RegExp(basename) })
      .getByRole("button", { name: "Annotate" })
      .click();
  await annotate();
  const editor = page.getByTestId("annotation-editor");
  const canvas = editor.getByTestId("annotation-canvas");
  const boxes = canvas.locator("[data-testid^='annotation-']");
  await editor.getByRole("button", { name: "Box tool", exact: true }).click();
  await expect(canvas).toHaveClass(/tool-box/);
  await canvas.scrollIntoViewIfNeeded();
  const { start, end } = await canvas.evaluate((svg) => {
    const matrix = svg.querySelector("g")?.getScreenCTM();
    if (!matrix) throw new Error("No source pixel transform");
    const s = new DOMPoint(20, 15).matrixTransform(matrix);
    const e = new DOMPoint(55, 40).matrixTransform(matrix);
    return { start: { x: s.x, y: s.y }, end: { x: e.x, y: e.y } };
  });
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 8 });
  await page.mouse.up();
  await expect(boxes).toHaveCount(1);
  if (firstUse) {
    const undoButton = editor.getByRole("button", {
      name: "Undo",
      exact: true,
    });
    await undoButton.scrollIntoViewIfNeeded();
    const hit = await undoButton.evaluate((button) => {
      const box = button.getBoundingClientRect();
      const hit = document.elementFromPoint(
        box.x + box.width / 2,
        box.y + box.height / 2,
      );
      const selector = (element: Element | null) =>
        element ? `${element.tagName}.${element.className}` : null;
      const snapshot = (element: Element) => ({
        rect: element.getBoundingClientRect().toJSON(),
        position: getComputedStyle(element).position,
        overflow: getComputedStyle(element).overflow,
        zIndex: getComputedStyle(element).zIndex,
      });
      return {
        reachable: button === hit || button.contains(hit),
        hit: selector(hit),
        hitParent: selector(hit?.parentElement ?? null),
        button: snapshot(button),
        sidebar: snapshot(button.closest(".annotation-editor-sidebar")!),
        body: snapshot(document.querySelector(".annotation-editor-body")!),
        inspector: snapshot(
          document.querySelector(".annotation-inspector-heading")!,
        ),
      };
    });
    await writeFile(
      info.outputPath("compact-editor-hit.json"),
      JSON.stringify(hit, null, 2),
    );
    expect(hit.reachable).toBe(true);
  }
  await editor.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(boxes).toHaveCount(0);
  await editor.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(boxes).toHaveCount(1);
  await editor.getByLabel("Annotation status").selectOption("reviewed");
  await editor.getByRole("button", { name: "Save now" }).click();
  await expect(editor.getByTestId("annotation-save-state")).toHaveText("Saved");
  const saved = await json(`${api}/images/${imageId}/annotations`);
  expect(saved.image.annotation_status).toBe("reviewed");
  expect(saved.image.sha256).toBe(hash(image));
  expect(saved.annotations).toHaveLength(1);
  const box = saved.annotations[0];
  expect(box.label_class_id).toBe(label.id);
  expect(box.x_min).toBeCloseTo(20, 0);
  expect(box.x_max).toBeCloseTo(55, 0);
  expect(box.y_min).toBeCloseTo(15, 0);
  expect(box.y_max).toBeCloseTo(40, 0);
  await openProject();
  await annotate();
  await expect(canvas.getByTestId(`annotation-${box.id}`)).toBeVisible();
  await expect(editor.getByLabel("Annotation status")).toHaveValue("reviewed");
  await openProject();
  await page
    .getByRole("tab", { name: "Dataset versions", exact: true })
    .click();
  await page.getByLabel("Version name").fill("Frozen ordinary fixture");
  await page.getByLabel("Split method").selectOption("random");
  await page.getByLabel("Train ratio").fill("1");
  await page.getByLabel("Validation ratio").fill("0");
  await page.getByLabel("Test ratio").fill("0");
  const freezing = post(`${root}/dataset-versions`);
  await page.getByRole("button", { name: "Create immutable version" }).click();
  const frozen = await freezing;
  expect(frozen.ok(), await frozen.text()).toBeTruthy();
  const snapshot = await frozen.json();
  expect(snapshot.manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
  const exportButton = page.getByRole("button", {
    name: "Export YOLO dataset",
  });
  const inspector = page.getByRole("complementary", {
    name: "Workspace inspector",
  });
  await expect(inspector).toBeVisible();
  if (desktop.surface === "source-browser") {
    for (const width of [1440, 1056]) {
      await page.setViewportSize({ width, height: 760 });
      await expect(inspector).toBeVisible();
      await exportButton.scrollIntoViewIfNeeded();
      const layout = await exportButton.evaluate((button) => {
        const stage = button.closest(".rv-workbench-stage")!;
        const versions = button.closest(".versions-layout")!;
        const inspector = document.getElementById(
          "reefvision-workspace-inspector",
        )!;
        const buttonBounds = button.getBoundingClientRect();
        const hitTarget = document.elementFromPoint(
          buttonBounds.x + buttonBounds.width / 2,
          buttonBounds.y + buttonBounds.height / 2,
        );
        return {
          viewport: { width: window.innerWidth, height: window.innerHeight },
          columnWidths: getComputedStyle(versions).gridTemplateColumns,
          stageRight: stage.getBoundingClientRect().right,
          inspectorLeft: inspector.getBoundingClientRect().left,
          buttonLeft: buttonBounds.left,
          buttonRight: buttonBounds.right,
          pointerReachesExport: button.contains(hitTarget),
          pointerRecipient:
            hitTarget?.closest("aside")?.className ?? hitTarget?.tagName,
        };
      });
      await writeFile(
        info.outputPath(`dataset-layout-${width}.json`),
        JSON.stringify(layout, null, 2),
      );
      expect(layout.buttonRight).toBeLessThanOrEqual(layout.stageRight);
      expect(layout.pointerReachesExport, JSON.stringify(layout)).toBe(true);
    }
  }
  const exporting = post(`${api}/dataset-versions/${snapshot.id}/exports`);
  await exportButton.click();
  const exported = await exporting;
  expect(exported.ok(), await exported.text()).toBeTruthy();
  const { export: record, job } = await exported.json();
  await expect
    .poll(
      async () => {
        const current = await json(`${api}/jobs/${job.id}`);
        expect(current.status, current.error_message).not.toBe("failed");
        return current.status;
      },
      { timeout: 20_000 },
    )
    .toBe("succeeded");
  const manifest = await json(`${api}/exports/${record.id}/manifest`);
  expect(manifest).toMatchObject({
    export_id: record.id,
    dataset_version_id: snapshot.id,
    dataset_version_manifest_sha256: snapshot.manifest_sha256,
    class_map: [{ id: label.id, class_index: 0, name: label.name }],
    items: [
      {
        image_id: imageId,
        image_sha256: hash(image),
        annotation_count: 1,
        split: "train",
      },
    ],
  });
  const archive = await page.request.get(
    `${api}/exports/${record.id}/download`,
  );
  expect(archive.ok()).toBeTruthy();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download zip", exact: true }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toMatch(/\.zip$/i);
  const exportedZip = info.outputPath("ordinary-2d-export.zip");
  await download.saveAs(exportedZip);
  const bytes = await readFile(exportedZip);
  expect(hash(bytes)).toBe(hash(await archive.body()));
  expect(bytes.subarray(0, 2).toString()).toBe("PK");
  // Twelve synthetic frames generated by scripts/seed_temporal_reefpose_live.py.
  const video = await readFile(
    new URL("./fixtures/synthetic-ordinary-clip.mp4", import.meta.url),
  );
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Video & tracking", exact: true })
    .click();
  await page.getByLabel("Video file", { exact: true }).setInputFiles({
    name: "field-clip-fixture.mp4",
    mimeType: "video/mp4",
    buffer: video,
  });
  const videoPosted = post(`${root}/imports/videos`);
  await page.getByRole("button", { name: "Import video", exact: true }).click();
  const videoResponse = await videoPosted;
  expect(videoResponse.ok(), await videoResponse.text()).toBeTruthy();
  const recording = await videoResponse.json();
  expect(recording.sha256).toBe(hash(video));
  const videoContent = await page.request.get(
    `${api}/videos/${recording.id}/content`,
  );
  expect(videoContent.ok()).toBeTruthy();
  expect(hash(await videoContent.body())).toBe(hash(video));
  await expect(
    page
      .getByTestId("video-tracking-workspace")
      .getByRole("option", { name: /field-clip-fixture/ }),
  ).toHaveAttribute("value", recording.id);
  await writeFile(
    info.outputPath("ordinary-2d-webview2.json"),
    JSON.stringify(
      {
        surface: desktop.surface,
        project_id: project.id,
        image_id: imageId,
        image_sha256: saved.image.sha256,
        annotation: box,
        dataset_version_id: snapshot.id,
        manifest_sha256: snapshot.manifest_sha256,
        export_id: record.id,
        export_sha256: hash(bytes),
        class_map: manifest.class_map,
        video_id: recording.id,
        video_sha256: hash(video),
      },
      null,
      2,
    ),
  );
  if (device) {
    expect([...outsideLoopback]).toEqual([]);
    await writeFile(
      info.outputPath("first-use-evidence.json"),
      JSON.stringify(
        {
          surface: desktop.surface,
          application_version: (await json(`${api}/system/version`))
            .application_version,
          empty_before_project_submission: true,
          welcome_focus_handoff: true,
          startup_dismissal_persisted: true,
          emulated_device_scale_factor: scale,
          emulated_viewport_css_px: [960, 640],
          nonlocal_browser_http_blocked: true,
          external_http_attempt_count: outsideLoopback.size,
          project_id: project.id,
          image_sha256: saved.image.sha256,
          annotation_status: saved.image.annotation_status,
          export_sha256: hash(bytes),
        },
        null,
        2,
      ),
    );
    await device.send("Emulation.clearDeviceMetricsOverride");
    await device.detach();
    await page.unroute(/^https?:\/\//);
  }
});
