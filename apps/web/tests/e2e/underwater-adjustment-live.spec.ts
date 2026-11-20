import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { expect, type APIResponse, type Response } from "@playwright/test";
import type { ImageAdjustmentRecord } from "../../src/features/annotation-editor/imageAdjustmentApi";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");

async function checked<T>(
  response: APIResponse | Response,
  status: number,
): Promise<T> {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

test("previews and reopens a raw-axis adjustment, runs a local model, and replays its saved graph", async ({
  desktop,
}, info) => {
  const { page, api, web, surface } = desktop;
  test.setTimeout(150_000);
  page.setDefaultTimeout(10_000);
  const fixturePath = process.env.REEFVISION_UNDERWATER_TEST_FIXTURE;
  test.skip(
    !fixturePath,
    "Requires the verified generated RGB image and local model fixture",
  );
  const runtime = await verifyResearchDesktop(page, api);
  const fixture = JSON.parse(await readFile(fixturePath!, "utf8")) as {
    image: string;
    image_sha256: string;
    weights: string;
    weights_sha256: string;
    width_px: number;
    height_px: number;
  };
  const original = await readFile(fixture.image);
  const weights = await readFile(fixture.weights);
  expect(sha256(original)).toBe(fixture.image_sha256);
  expect(sha256(weights)).toBe(fixture.weights_sha256);
  expect(fixture.width_px).not.toBe(fixture.height_px);
  const name = `Generated RGB proof ${randomUUID().slice(0, 8)}`;
  const imageName = "synthetic-exif-orientation.png";
  const project = await checked<{ id: string }>(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
    201,
  );
  const endpoint = `${api}/projects/${project.id}`;
  const label = await checked<{ id: string }>(
    await page.request.post(`${endpoint}/classes`, {
      data: {
        class_index: 0,
        name: "Fixture square",
        display_color: "#28A95C",
      },
    }),
    201,
  );
  const model = await checked<{ id: string; sha256: string }>(
    await page.request.post(`${endpoint}/models/register`, {
      multipart: {
        file: {
          name: "synthetic-local.pt",
          mimeType: "application/octet-stream",
          buffer: weights,
        },
        purpose: "detector",
        display_name: "Synthetic local detector",
      },
    }),
    200,
  );
  expect(model.sha256).toBe(fixture.weights_sha256);
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${version}`,
        "true",
      ),
    runtime.application_version,
  );
  await page.goto(web);
  await page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  const write = (url: string) =>
    page.waitForResponse(
      (res) => res.url() === url && res.request().method() === "POST",
    );
  const pendingImport = write(`${endpoint}/imports/images`);
  await page.getByLabel("Import files", { exact: true }).setInputFiles({
    name: imageName,
    mimeType: "image/png",
    buffer: original,
  });
  const imported = await checked<{ successful: { image_id: string }[] }>(
    await pendingImport,
    200,
  );
  const imageId = imported.successful[0].image_id;
  const source = `${api}/images/${imageId}`;
  const body = await checked<{
    metadata_json: { exif: { Orientation: number } };
    width_px: number;
    height_px: number;
  }>(await page.request.get(source), 200);
  expect(body.metadata_json.exif.Orientation).toBe(6);
  expect([body.width_px, body.height_px]).toEqual([
    fixture.width_px,
    fixture.height_px,
  ]);
  const markupId = randomUUID();
  await checked(
    await page.request.put(`${source}/annotations`, {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [
          {
            id: markupId,
            label_class_id: label.id,
            x_min: 12,
            y_min: 14,
            x_max: 40,
            y_max: 45,
          },
        ],
      },
    }),
    200,
  );
  const card = page.getByRole("article", { name: imageName, exact: false });
  const openImage = () =>
    card.getByRole("button", { name: "Annotate" }).click();
  await openImage();
  const editor = page.getByTestId("annotation-editor");
  const grid = editor.getByTestId("viewport-transform");
  const background = grid.locator("image").first();
  const panel = () =>
    editor.getByText("Image adjustments", { exact: true }).click();
  await expect(background).toHaveAttribute("width", String(fixture.width_px));
  await expect(background).toHaveAttribute("height", String(fixture.height_px));
  const transform = await grid.getAttribute("transform");
  const before = await background.getAttribute("href");
  await panel();
  await editor.getByLabel("Red gain (%)", { exact: true }).fill("125");
  await editor.getByLabel("Blue gain (%)", { exact: true }).fill("90");
  const previewed = write(`${source}/adjustments/preview`);
  await editor
    .getByRole("button", { name: "Preview adjustment", exact: true })
    .click();
  const preview = await previewed;
  expect(preview.status()).toBe(200);
  await expect(background).toHaveAttribute("href", /^blob:/);
  const displayed = await background.evaluate(async (element) => {
    const response = await fetch(element.getAttribute("href")!);
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);
    const dimensions = [bitmap.width, bitmap.height];
    bitmap.close();
    return {
      dimensions,
      bytes: Array.from(new Uint8Array(await blob.arrayBuffer())),
    };
  });
  expect(displayed.dimensions).toEqual([fixture.width_px, fixture.height_px]);
  const previewSha = sha256(Buffer.from(displayed.bytes));
  expect(previewSha).not.toBe(fixture.image_sha256);
  await expect(grid).toHaveAttribute("transform", transform!);
  await expect(editor.getByTestId(`annotation-${markupId}`)).toBeVisible();

  const saving = write(`${source}/adjustments`);
  await editor.getByRole("button", { name: "Save adjustment recipe" }).click();
  const recipe = await checked<ImageAdjustmentRecord>(await saving, 201);
  expect(recipe.receipt.rendition_sha256).toBe(previewSha);
  expect(recipe.receipt.original_sha256).toBe(fixture.image_sha256);
  await expect(
    editor.getByText(recipe.content_sha256, { exact: true }),
  ).toBeVisible();
  await editor.getByRole("button", { name: "Show original pixels" }).click();
  await expect(background).toHaveAttribute("href", before!);
  await editor.getByRole("button", { name: "Show adjusted pixels" }).click();
  await expect(background).toHaveAttribute("href", /^blob:/);

  const renditionHref = await background.getAttribute("href");
  await editor.getByTestId("open-polygon-tool").click();
  const polygon = page.getByTestId("mask-workspace");
  await expect(polygon.getByRole("img", { name: imageName })).toHaveAttribute(
    "src",
    renditionHref!,
  );
  await polygon.getByTestId("open-brush-tool").click();
  const raster = page.getByTestId("raster-mask-workspace");
  const rasterImage = raster.getByRole("img", { name: imageName });
  await expect(rasterImage).toHaveAttribute("src", renditionHref!);
  await expect
    .poll(() =>
      rasterImage.evaluate((image: HTMLImageElement) => [
        image.naturalWidth,
        image.naturalHeight,
      ]),
    )
    .toEqual([fixture.width_px, fixture.height_px]);
  await raster.getByTestId("return-main-tools").click();
  await expect(background).toHaveAttribute("href", renditionHref!);
  await panel();

  const receiptDownload = page.waitForEvent("download");
  await editor.getByRole("link", { name: "Download recipe JSON" }).click();
  const exported = await receiptDownload;
  expect(exported.suggestedFilename()).toBe(`adjustment-${recipe.id}.json`);
  const receiptFile = info.outputPath("adjustment-recipe-export.json");
  await exported.saveAs(receiptFile);
  expect(JSON.parse(await readFile(receiptFile, "utf8"))).toEqual(recipe);
  const pngDownload = page.waitForEvent("download");
  await editor.getByRole("link", { name: "Download adjusted PNG" }).click();
  const png = await pngDownload;
  expect(sha256(await readFile((await png.path())!))).toBe(previewSha);
  await editor
    .getByRole("button", { name: "Back to gallery", exact: true })
    .click();
  await openImage();
  await panel();
  await editor.getByLabel("Saved adjustment recipes").selectOption(recipe.id);
  await expect(
    editor.getByText(recipe.content_sha256, { exact: true }),
  ).toBeVisible();

  const choice = editor.getByLabel(
    "Use saved adjustment for the next model run",
  );
  await expect(choice).not.toBeChecked();
  await choice.check();
  await editor.getByLabel("Deployment confidence").fill("0.0001");
  await editor.getByLabel("Deployment device").selectOption("cpu");
  const infer = write(`${endpoint}/inference-jobs`);
  await editor
    .getByRole("button", { name: "Run model on this image", exact: true })
    .click();
  const job = await checked<{
    id: string;
    request_json: {
      image_adjustment: Record<string, string>;
      checkpoint_sha256: string;
    };
  }>(await infer, 200);
  expect(job.request_json.image_adjustment).toMatchObject({
    recipe_id: recipe.id,
    content_sha256: recipe.content_sha256,
    original_sha256: fixture.image_sha256,
    rendition_sha256: previewSha,
  });
  expect(job.request_json.checkpoint_sha256).toBe(fixture.weights_sha256);
  await expect(choice).not.toBeChecked();
  await expect(editor.getByText(/Model job succeeded/)).toBeVisible({
    timeout: 30_000,
  });
  const prediction = await checked<{
    items: {
      id: string;
      inference_job_id: string;
      review_status: string;
      x_min: number;
      y_min: number;
      x_max: number;
      y_max: number;
      provenance_json: { model_input: Record<string, unknown> };
    }[];
  }>(await page.request.get(`${source}/prediction-proposals`), 200);
  const pending = prediction.items.filter(
    (row) => row.inference_job_id === job.id,
  );
  expect(pending.length).toBeGreaterThan(0);
  for (const row of pending) {
    expect(row.review_status).toBe("pending");
    expect(row.x_min).toBeGreaterThanOrEqual(0);
    expect(row.y_min).toBeGreaterThanOrEqual(0);
    expect(row.x_max).toBeLessThanOrEqual(fixture.width_px);
    expect(row.y_max).toBeLessThanOrEqual(fixture.height_px);
    expect(row.provenance_json.model_input).toMatchObject({
      pixel_axes: "raw_source",
      rendition_sha256: previewSha,
      original_sha256: fixture.image_sha256,
    });
  }
  expect(
    sha256(await (await page.request.get(`${source}/content`)).body()),
  ).toBe(fixture.image_sha256);
  const annotations = await checked<{
    annotations: Array<{
      id: string;
      x_min: number;
      y_min: number;
      x_max: number;
      y_max: number;
    }>;
  }>(await page.request.get(`${source}/annotations`), 200);
  expect(annotations.annotations).toHaveLength(1);
  expect(annotations.annotations[0]).toMatchObject({
    id: markupId,
    x_min: 12,
    y_min: 14,
    x_max: 40,
    y_max: 45,
  });
  await editor
    .getByRole("button", { name: "Back to gallery", exact: true })
    .click();

  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Workflow builder", exact: true })
    .click();
  await page
    .getByRole("combobox")
    .filter({
      has: page.getByRole("option", { name: "Project images", exact: true }),
    })
    .selectOption("project-images");
  await page.getByLabel("Add node").selectOption("underwater_adjustment");
  const node = page.locator("[data-node-id^='underwater_adjustment-']");
  await node.getByRole("button", { name: "Configure", exact: true }).click();
  const currentImageChoice = page.getByRole("combobox").filter({
    has: page.getByRole("option", { name: imageName, exact: true }),
  });
  const currentRecipeChoice = page.getByRole("combobox").filter({
    has: page.getByRole("option", {
      name: recipe.content_sha256.slice(0, 12),
      exact: true,
    }),
  });
  await currentImageChoice.selectOption(imageId);
  await currentRecipeChoice.selectOption(recipe.id);
  await page
    .locator("[data-node-id='project']")
    .getByRole("button", { name: /Project.*▶/i })
    .click();
  await node.getByRole("button", { name: /◀.*Project/i }).click();
  const execute = async (button: string) => {
    const queued = write(`${endpoint}/workflow-runs`);
    await page.getByRole("button", { name: button, exact: true }).click();
    const { id } = await checked<{ id: string }>(await queued, 202);
    let result:
      | {
          run: { status: string; graph_sha256: string };
          artifacts: {
            data_type: string;
            payload_sha256: string;
            payload_json: { receipt: object };
          }[];
        }
      | undefined;
    await expect
      .poll(
        async () => {
          result = await checked<NonNullable<typeof result>>(
            await page.request.get(`${api}/workflow-runs/${id}`),
            200,
          );
          return result.run.status;
        },
        { timeout: 30_000 },
      )
      .toBe("succeeded");
    const adjusted = result!.artifacts.find(
      (artifact) => artifact.data_type === "adjusted_image_reference",
    );
    expect(adjusted?.payload_json.receipt).toEqual(recipe.receipt);
    return {
      id,
      graph_sha256: result!.run.graph_sha256,
      payload_sha256: adjusted!.payload_sha256,
    };
  };
  const first = await execute("Save & run");
  await page.goto(web);
  await page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Workflow builder", exact: true })
    .click();
  await page.getByRole("button", { name: "Load", exact: true }).first().click();
  await node.getByRole("button", { name: "Configure", exact: true }).click();
  await expect(currentRecipeChoice).toHaveValue(recipe.id);
  const second = await execute("Run saved revision");
  expect(second.id).not.toBe(first.id);
  expect(second.graph_sha256).toBe(first.graph_sha256);
  expect(second.payload_sha256).toBe(first.payload_sha256);
  await writeFile(
    info.outputPath("underwater-adjustment-evidence.json"),
    JSON.stringify(
      {
        surface,
        application_version: runtime.application_version,
        schema_revision: runtime.schema_revision,
        project_id: project.id,
        image_id: imageId,
        recipe,
        original_sha256: fixture.image_sha256,
        model_sha256: model.sha256,
        job: job.id,
        source_pixel_predictions: pending.map(
          ({ id, x_min, y_min, x_max, y_max }) => ({
            id,
            x_min,
            y_min,
            x_max,
            y_max,
          }),
        ),
        saved_graph_runs: [first, second],
        raw_axes_reopened: true,
        polygon_and_raster_reused_rendition: true,
        original_bytes_match: true,
      },
      null,
      2,
    ),
  );
});
