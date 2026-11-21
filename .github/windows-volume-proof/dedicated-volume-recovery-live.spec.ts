import { createHash, randomUUID } from "node:crypto";
import { access, readFile, rename, writeFile } from "node:fs/promises";
import { parse, resolve } from "node:path";
import { crc32, deflateSync } from "node:zlib";
import { expect, type APIResponse, type Response } from "@playwright/test";
import { test } from "./spatialDesktop";

const digest = (bytes: Buffer | string) =>
  createHash("sha256").update(bytes).digest("hex");

function fixtureImage() {
  const idat = (kind: string, body: Buffer) => {
    const name = Buffer.from(kind);
    const size = Buffer.alloc(4);
    size.writeUInt32BE(body.length);
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(crc32(Buffer.concat([name, body])));
    return Buffer.concat([size, name, body, checksum]);
  };
  const width = 960;
  const height = 720;
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const line = Buffer.alloc(1 + 3 * width, 80);
  line[0] = 0;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    idat("IHDR", header),
    idat("IDAT", deflateSync(Buffer.concat(Array.from({ length: height }, () => line)))),
    idat("IEND", Buffer.alloc(0)),
  ]);
}

test("the original installed editor preserves a draft on real full NTFS and retries it once", async ({ desktop }, info) => {
  test.setTimeout(110_000);
  const { api, web, page, surface } = desktop;
  expect(surface).toBe("tauri-webview2");
  const root = resolve(process.env.REEFVISION_STORAGE_PHASE_ROOT!);
  const profile = resolve(process.env.REEFVISION_STORAGE_PROFILE!);
  const owner = parse(profile).root;
  expect(owner.toLowerCase()).not.toBe(parse(root).root.toLowerCase());
  await access(resolve(profile, ".reefvision-clean-install-acceptance"));
  await access(resolve(owner, ".reefvision-volume-owner"));
  const data = async (response: Response | APIResponse, code: number) => {
    expect(response.status(), await response.text()).toBe(code);
    return response.json();
  };
  const get = async (path: string) => data(await page.request.get(api + path), 200);
  const version = await get("/system/version");
  expect(version).toMatchObject({
    application_version: process.env.REEFVISION_STORAGE_VERSION,
    current_schema_revision: process.env.REEFVISION_STORAGE_SCHEMA,
    expected_schema_revision: process.env.REEFVISION_STORAGE_SCHEMA,
    safe_mode: false,
  });
  expect(resolve(version.data_dir).toLowerCase()).toBe(profile.toLowerCase());

  async function transition(phase: "fill" | "release") {
    const token = process.env.REEFVISION_STORAGE_NONCE!;
    expect(token).toMatch(/^[a-f0-9-]+$/);
    const request = resolve(root, phase + ".request.json");
    await writeFile(request + ".tmp", JSON.stringify({ token, phase }), { flag: "wx" });
    await rename(request + ".tmp", request);
    let result: Record<string, unknown> | undefined;
    await expect.poll(async () => {
      const raw = await readFile(resolve(root, phase + ".ready.json"), "utf8").catch((error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") return null;
        throw error;
      });
      if (raw === null) return false;
      result = JSON.parse(raw);
      return result?.token === token;
    }, { timeout: 30_000, intervals: [150, 300, 500, 1000] }).toBe(true);
    return result!;
  }

  const projectName = "Generated original installer capacity fixture";
  const project = await data(await page.request.post(api + "/projects", {
    data: { name: projectName, template: "blank" },
  }), 201);
  const p = "/projects/" + project.id;
  const label = await data(await page.request.post(api + p + "/classes", {
    data: { name: "Quota fixture objects", class_index: 0, display_color: "#28a95c" },
  }), 201);
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false,
    });
    await page.addInitScript((v) => localStorage.setItem("reefvision.onboarding.dismissed." + v, "true"), version.application_version);
    await page.goto(web);
    const welcome = page.getByRole("dialog", { name: /Welcome to ReefVision/ });
    if (await welcome.isVisible()) await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Open " + projectName, exact: true }).click();
    const imported = page.waitForResponse((r) => r.url() === api + p + "/imports/images" && r.request().method() === "POST");
    const source = fixtureImage();
    const sourceSha = digest(source);
    await page.getByLabel("Import files", { exact: true }).setInputFiles({
      name: "capacity-witness.png", mimeType: "image/png", buffer: source,
    });
    const results = await data(await imported, 200);
    expect(results.successful).toHaveLength(1);
    const image = results.successful[0].image_id as string;
    const path = "/images/" + image + "/annotations";
    const initial = Array.from({ length: 96 }, (_, index) => {
      const x = 36 + (index % 12) * 74;
      const y = 40 + Math.floor(index / 12) * 78;
      return { id: randomUUID(), label_class_id: label.id, x_min: x, y_min: y, x_max: x + 26, y_max: y + 20 };
    });
    await data(await page.request.put(api + path, {
      data: { base_revision: 0, annotation_status: "in_progress", annotations: initial },
    }), 200);
    const seeded = await get(path);
    expect(seeded.image).toMatchObject({ annotation_revision: 1, sha256: sourceSha });
    expect(seeded.annotations).toHaveLength(96);

    const card = page.getByRole("article", { name: /capacity-witness\.png/ });
    await card.getByRole("button", { name: "Annotate", exact: true }).click();
    const editor = page.getByTestId("annotation-editor");
    const canvas = editor.getByTestId("annotation-canvas");
    const boxes = canvas.locator("rect[data-testid^='annotation-']");
    const status = editor.getByTestId("annotation-save-state");
    await expect(boxes).toHaveCount(96);
    await editor.getByRole("button", { name: "Select tool", exact: true }).click();
    await canvas.scrollIntoViewIfNeeded();
    await boxes.first().click();
    for (let index = 1; index < 96; index++) {
      await boxes.nth(index).click({ modifiers: ["Control"] });
    }
    await expect(editor.getByRole("listbox", { name: "Objects" }).getByRole("option", { selected: true })).toHaveCount(96);
    const save = editor.getByRole("button", { name: "Save now", exact: true });
    await expect(save).toBeEnabled();
    // Thumbnails arrive through the ordinary worker after import. Let that write finish
    // before capturing the annotation state and preparing real volume pressure.
    await expect.poll(async () => (await get(path)).image.thumbnail_path).toBeTruthy();
    const before = await get(path);
    expect(before.image).toMatchObject({ annotation_revision: 1, sha256: sourceSha });
    expect(before.annotations).toEqual(seeded.annotations);
    const writes: { status: number; body: string }[] = [];
    const relevant = (r: Response) => r.url() === api + path && r.request().method() === "PUT";
    page.on("response", (r) => {
      if (relevant(r)) writes.push({ status: r.status(), body: r.request().postData()! });
    });

    const pressure = await transition("fill");
    expect(pressure.pressured_bytes).toBeLessThanOrEqual(32 * 1024);
    const denied = page.waitForResponse(relevant);
    await editor.getByRole("button", { name: "Duplicate", exact: true }).click();
    await save.click();
    const response = await data(await denied, 507);
    expect(response.code).toBe("storage_full");
    expect(response.detail).toContain("Free space and retry");
    await expect(status).toHaveText(response.detail);
    await expect(boxes).toHaveCount(192);
    const retry = editor.getByRole("button", { name: "Retry save", exact: true });
    await expect(retry).toBeEnabled();
    await page.screenshot({ path: info.outputPath("capacity-denied.png") });
    await new Promise((done) => setTimeout(done, 1700));
    expect(writes.map(({ status }) => status)).toEqual([507]);
    expect(await get(path)).toEqual(before);

    const lifted = await transition("release");
    expect(lifted.released_bytes).toBeGreaterThanOrEqual(32 * 1024 * 1024);
    const retried = page.waitForResponse(relevant);
    await retry.click();
    const committed = await data(await retried, 200);
    await expect(status).toHaveText("Saved");
    expect(writes.map(({ status }) => status)).toEqual([507, 200]);
    expect(digest(writes[1].body)).toBe(digest(writes[0].body));
    expect(committed.image).toMatchObject({ annotation_revision: 2, sha256: sourceSha });
    expect(committed.annotations).toHaveLength(192);
    const ids = new Set(JSON.parse(writes[1].body).annotations.map((row: { id: string }) => row.id));
    expect(new Set(committed.annotations.map((row: { id: string }) => row.id))).toEqual(ids);
    await editor.getByRole("button", { name: "Back to gallery", exact: true }).click();
    await card.getByRole("button", { name: "Annotate", exact: true }).click();
    await expect(boxes).toHaveCount(192);
    const reopened = await get(path);
    expect(reopened.image).toMatchObject({ annotation_revision: 2, sha256: sourceSha });
    expect(reopened.annotations).toEqual(committed.annotations);
    const media = await page.request.get(api + "/images/" + image + "/content");
    expect(media.status()).toBe(200);
    expect(digest(await media.body())).toBe(sourceSha);
    expect(writes.map(({ status }) => status)).toEqual([507, 200]);
    await page.screenshot({ path: info.outputPath("capacity-reopened.png") });
    await writeFile(info.outputPath("dedicated-volume-recovery.json"), JSON.stringify({
      surface, source: process.env.REEFVISION_STORAGE_SOURCE, version: version.application_version, schema: version.current_schema_revision,
      project_id: project.id, image_id: image, original_sha256: sourceSha,
      failure: response, rejected_revision: before.image.annotation_revision, rejected_saved_annotations: before.annotations.length,
      retained_draft_annotations: 192, recovered_revision: reopened.image.annotation_revision, recovered_annotations: reopened.annotations.length,
      request_statuses: writes.map(({ status }) => status), identical_retry_sha256: digest(writes[1].body),
      restored_original_verified: true, pressure, relief: lifted,
    }, null, 2));
  } finally {
    await cdp.send("Emulation.clearDeviceMetricsOverride");
    await cdp.detach();
  }
});
