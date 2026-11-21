import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";
import { test } from "./spatialDesktop";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import type {
  Capture,
  Index,
  Receipt,
} from "../../src/features/project-assets/multispectralApi";
import type {
  WorkflowGraphRecord,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";

function bandTiff(samples: number[]) {
  const count = 9,
    data = 8 + 2 + count * 12 + 4;
  const buf = Buffer.alloc(data + samples.length);
  buf.write("II");
  buf.writeUInt16LE(42, 2);
  buf.writeUInt32LE(8, 4);
  buf.writeUInt16LE(count, 8);
  const tags = [
    [256, 4, 4],
    [257, 4, 2],
    [258, 3, 8],
    [259, 3, 1],
    [262, 3, 1],
    [273, 4, data],
    [277, 3, 1],
    [278, 4, 2],
    [279, 4, samples.length],
  ];
  tags.forEach(([tag, type, value], i) => {
    const p = 10 + i * 12;
    buf.writeUInt16LE(tag, p);
    buf.writeUInt16LE(type, p + 2);
    buf.writeUInt32LE(1, p + 4);
    buf.writeUInt32LE(value, p + 8);
  });
  Buffer.from(samples).copy(buf, data);
  return buf;
}

async function checked<T>(response: APIResponse | Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}
const post = (page: Page, url: string) =>
  page.waitForResponse(
    (r) => r.url() === url && r.request().method() === "POST",
  );
const hash = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");

test("imports original bands, reopens their calibrated index and runs the saved graph twice", async ({
  desktop,
}, info) => {
  test.setTimeout(120000);
  const { page, api, web, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  const name = "Spectral " + randomUUID().slice(0, 8);
  const project = await checked<{ id: string }>(
    await page.request.post(api + "/projects", {
      data: { name, template: "blank" },
    }),
    201,
  );
  const base = api + "/projects/" + project.id,
    root = base + "/multispectral";
  const open = async () => {
    await page.goto(web);
    const guide = page.getByRole("dialog", { name: /Welcome to ReefVision/ });
    await expect(
      page.getByRole("button", { name: "Help", exact: true }),
    ).toBeVisible();
    if (await guide.isVisible()) await page.keyboard.press("Escape");
    await page
      .getByRole("button", { name: "Open " + name, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Data & annotation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Project assets", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Multispectral images", exact: true })
      .click();
  };
  await open();
  const original = page.getByRole("region", {
    name: "Import multispectral image",
    exact: true,
  });
  const files = [
    {
      name: "red.tif",
      mimeType: "image/tiff",
      buffer: bandTiff([20, 20, 20, 0, 20, 0, 20, 20]),
    },
    {
      name: "nir.tif",
      mimeType: "image/tiff",
      buffer: bandTiff([60, 255, 0, 20, 0, 60, 60, 40]),
    },
  ];
  await original.getByLabel(/Original band files/).setInputFiles(files);
  await original.getByRole("button", { name: "Import band originals" }).click();
  await original.getByLabel("Acquisition name").fill("Generated aligned tiles");
  await original
    .getByLabel("Sensor", { exact: true })
    .fill("Generated two-band fixture");
  for (const [i, file] of files.entries()) {
    const band = original.getByRole("group", { name: file.name });
    await band.getByLabel("Center wavelength (nm)").fill(i ? "850" : "660");
    await band.getByLabel("NoData digital number").fill("255");
    if (i) await band.getByLabel("Column offset (pixels)").fill("1");
    await band.getByLabel("Supply reflectance calibration").check();
    await band.getByLabel("Dark reference (DN)").fill("0");
    await band.getByLabel("White reference (DN)").fill("100");
    await band
      .getByLabel("Calibration reference")
      .fill("Known generated 100 DN panel");
  }
  await original.getByLabel("Record reviewed grid alignment").check();
  await original
    .getByLabel("Reference grid", { exact: true })
    .fill("Red source pixels");
  await original.getByLabel("Alignment reviewer").fill("Fixture reviewer");
  await original
    .getByLabel("Alignment evidence")
    .fill("Generated integer translation");
  await original.getByLabel("Maximum residual (pixels)").fill("0");
  const created = post(page, root + "/acquisitions");
  await original.getByRole("button", { name: "Save acquisition" }).click();
  const capture = await checked<Receipt<Capture>>(await created, 201);
  for (const [i, band] of capture.snapshot.bands.entries()) {
    expect(
      hash(
        await (
          await page.request.get(api + "/images/" + band.image_id + "/content")
        ).body(),
      ),
    ).toBe(hash(files[i].buffer));
  }
  const preview = page.getByRole("img", {
    name: "Selected bands on the registered source-pixel grid",
  });
  await expect(preview).toBeVisible();
  const displayed = await preview.evaluate(async (el: HTMLImageElement) => {
    await el.decode();
    const canvas = document.createElement("canvas");
    canvas.width = el.naturalWidth;
    canvas.height = el.naturalHeight;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(el, 0, 0);
    return Array.from(ctx.getImageData(1, 0, 1, 1).data);
  });
  expect(displayed).toEqual([153, 51, 51, 255]);
  const calculated = post(
    page,
    root + "/acquisitions/" + capture.id + "/indices",
  );
  await page.getByRole("button", { name: "Calculate spectral index" }).click();
  const saved = await checked<Receipt<Index>>(await calculated, 201);
  expect(saved.snapshot.result).toMatchObject({
    status: "available",
    mean: 0.5,
    valid_pixels: 3,
    reference_pixels: 8,
  });
  const result = page.getByRole("region", { name: "Saved spectral index" });
  await expect(result.getByText(/3 of 8 reference pixels/)).toBeVisible();
  const output = info.outputPath("spectral-index.json");
  const downloading = page.waitForEvent("download");
  await result.getByRole("button", { name: "Download index report" }).click();
  await (await downloading).saveAs(output);
  expect(JSON.parse(await readFile(output, "utf8"))).toEqual(saved);
  const raster = page.waitForEvent("download");
  await result.getByRole("button", { name: "Download float TIFF" }).click();
  const rasterFile = info.outputPath("spectral-index.tif");
  await (await raster).saveAs(rasterFile);
  await open();
  await expect(result.getByText(/3 of 8 reference pixels/)).toBeVisible();
  const registering = post(page, base + "/workflow-graphs");
  await result.getByRole("button", { name: "Save spectral workflow" }).click();
  const graph = await checked<WorkflowGraphRecord>(await registering, 201);
  const runs = [];
  for (let i = 0; i < 2; i++) {
    const pending = post(page, base + "/workflow-runs");
    await page
      .getByRole("listitem")
      .filter({ hasText: graph.name })
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const { id } = await checked<{ id: string }>(await pending, 202);
    let detail!: WorkflowRunDetail;
    await expect
      .poll(
        async () => {
          detail = await checked<WorkflowRunDetail>(
            await page.request.get(api + "/workflow-runs/" + id),
            200,
          );
          return detail.run.status;
        },
        { timeout: 35000 },
      )
      .toBe("succeeded");
    const artifact = detail.artifacts.find(
      (a) => a.data_type === "multispectral_index",
    )!;
    expect(artifact.payload_json).toEqual(saved);
    runs.push({ id, sha256: artifact.payload_sha256 });
  }
  expect(runs[0].id).not.toBe(runs[1].id);
  expect(runs[0].sha256).toBe(runs[1].sha256);
  await writeFile(
    info.outputPath("multispectral-evidence.json"),
    JSON.stringify({
      application_version: runtime.application_version,
      schema_revision: runtime.schema_revision,
      surface,
      project_id: project.id,
      acquisition_sha256: capture.content_sha256,
      record: saved,
      displayed_rgba: displayed,
      export_sha256: hash(await readFile(output)),
      tiff_sha256: hash(await readFile(rasterFile)),
      graph_sha256: graph.graph_sha256,
      runs,
      generated_fixture: true,
    }),
  );
});
