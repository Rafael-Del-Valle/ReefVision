import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const pngBytes = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WHdCkUAAAAASUVORK5CYII=",
  "base64",
);

const now = "2026-08-08T00:00:00Z";
const project = {
  id: "project-m2",
  name: "Milestone 2 Coral Study",
  slug: "milestone-2-coral-study",
  description: "Editable mask acceptance",
  storage_root: "projects/project-m2",
  default_annotation_type: "bbox",
  created_at: now,
  updated_at: now,
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-m2",
      class_index: 0,
      display_order: 0,
      name: "Muricea Closed",
      scientific_name: null,
      state_name: "Closed",
      description: null,
      display_color: "#E76F51",
      is_active: true,
      archived_at: null,
      created_at: now,
      updated_at: now,
    },
    {
      id: "class-2",
      project_id: "project-m2",
      class_index: 1,
      display_order: 1,
      name: "Muricea Open",
      scientific_name: null,
      state_name: "Open",
      description: null,
      display_color: "#2A9D8F",
      is_active: true,
      archived_at: null,
      created_at: now,
      updated_at: now,
    },
  ],
};

function makeImage(id: string, filename: string, revision = 0) {
  return {
    id,
    project_id: project.id,
    original_filename: filename,
    managed_path: `projects/${project.id}/images/originals/${id}.png`,
    thumbnail_path: null,
    sha256: id === "image-1" ? "a".repeat(64) : "b".repeat(64),
    width_px: 1600,
    height_px: 1200,
    file_size_bytes: 2048,
    media_type: "image/png",
    import_source: `trial/${filename}`,
    capture_timestamp: null,
    group_key: null,
    metadata_json: {},
    annotation_status: revision > 0 ? "in_progress" : "unannotated",
    annotation_revision: revision,
    annotation_count: 0,
    created_at: now,
    updated_at: now,
  };
}

type MaskRecord = {
  id: string;
  image_id: string;
  label_class_id: string | null;
  geometry_kind: string;
  mask_path: string | null;
  polygon_json: number[][] | null;
  x_min: number | null;
  y_min: number | null;
  x_max: number | null;
  y_max: number | null;
  area_pixels: number | null;
  source_type: string;
  provenance_json: Record<string, unknown> | null;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  revision: number;
};

type SessionState = {
  image: ReturnType<typeof makeImage>;
  label_classes: typeof project.label_classes;
  annotations: Array<Record<string, unknown>>;
  mask_annotations: MaskRecord[];
  counts_by_class: Array<{ label_class_id: string; count: number }>;
  previous_image_id: string | null;
  next_image_id: string | null;
};

async function mountBuiltApp(page: Parameters<typeof test>[0]["page"]) {
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
}

function maskCounts(masks: MaskRecord[]) {
  return project.label_classes.map((labelClass) => ({
    label_class_id: labelClass.id,
    count: masks.filter((mask) => mask.label_class_id === labelClass.id).length,
  }));
}

function persistedPolygon(
  imageId: string,
  draft: {
    id: string;
    label_class_id: string;
    points: Array<{ x: number; y: number }>;
  },
  revision: number,
): MaskRecord {
  const xs = draft.points.map((point) => point.x);
  const ys = draft.points.map((point) => point.y);
  let doubleArea = 0;
  for (let index = 0; index < draft.points.length; index += 1) {
    const current = draft.points[index];
    const next = draft.points[(index + 1) % draft.points.length];
    doubleArea += current.x * next.y - next.x * current.y;
  }
  return {
    id: draft.id,
    image_id: imageId,
    label_class_id: draft.label_class_id,
    geometry_kind: "polygon",
    mask_path: null,
    polygon_json: draft.points.map((point) => [point.x, point.y]),
    x_min: Math.min(...xs),
    y_min: Math.min(...ys),
    x_max: Math.max(...xs),
    y_max: Math.max(...ys),
    area_pixels: Math.round(Math.abs(doubleArea) / 2),
    source_type: "human",
    provenance_json: null,
    status: "draft",
    created_by: "local_user",
    created_at: now,
    updated_at: now,
    deleted_at: null,
    revision,
  };
}

test("Milestone 2 polygon and raster edits persist across image navigation and restart", async ({
  page,
}) => {
  const sessions: Record<string, SessionState> = {
    "image-1": {
      image: makeImage("image-1", "swiftia-day0.png"),
      label_classes: project.label_classes,
      annotations: [],
      mask_annotations: [],
      counts_by_class: maskCounts([]),
      previous_image_id: null,
      next_image_id: "image-2",
    },
    "image-2": {
      image: makeImage("image-2", "swiftia-day90.png"),
      label_classes: project.label_classes,
      annotations: [],
      mask_annotations: [],
      counts_by_class: maskCounts([]),
      previous_image_id: "image-1",
      next_image_id: null,
    },
  };
  const polygonSavePayloads: Array<Record<string, unknown>> = [];
  const rasterEditPayloads: Array<Record<string, unknown>> = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();

    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.7.0" } });
      return;
    }
    if (url.pathname.endsWith("/project-summaries") && method === "GET") {
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
    if (url.pathname.endsWith(`/projects/${project.id}`) && method === "GET") {
      await route.fulfill({ json: project });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}/images`) &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          items: [sessions["image-1"].image, sessions["image-2"].image],
          total: 2,
          page: 1,
          page_size: 24,
          pages: 1,
        },
      });
      return;
    }

    const annotationMatch = url.pathname.match(
      /\/images\/(image-[12])\/annotations$/,
    );
    if (annotationMatch) {
      const imageId = annotationMatch[1];
      const session = sessions[imageId];
      if (method === "GET") {
        await route.fulfill({ json: session });
        return;
      }
      const payload = request.postDataJSON() as {
        annotation_status: string;
        annotations?: Array<Record<string, unknown>>;
        mask_annotations?: Array<{
          id: string;
          label_class_id: string;
          points: Array<{ x: number; y: number }>;
        }>;
      };
      polygonSavePayloads.push(payload as unknown as Record<string, unknown>);
      const nextRevision = session.image.annotation_revision + 1;
      const existingRasters = session.mask_annotations.filter(
        (mask) => mask.geometry_kind === "raster_mask",
      );
      const polygons = (payload.mask_annotations ?? []).map((draft) =>
        persistedPolygon(imageId, draft, nextRevision),
      );
      session.mask_annotations = [...polygons, ...existingRasters];
      session.image = {
        ...session.image,
        annotation_revision: nextRevision,
        annotation_status: payload.annotation_status as ReturnType<
          typeof makeImage
        >["annotation_status"],
      };
      session.counts_by_class = maskCounts(session.mask_annotations);
      await route.fulfill({
        json: {
          image: session.image,
          annotations: session.annotations,
          mask_annotations: session.mask_annotations,
          counts_by_class: session.counts_by_class,
        },
      });
      return;
    }

    const rasterEditMatch = url.pathname.match(
      /\/images\/(image-[12])\/raster-mask-edits$/,
    );
    if (rasterEditMatch && method === "POST") {
      const imageId = rasterEditMatch[1];
      const session = sessions[imageId];
      const payload = request.postDataJSON() as {
        base_revision: number;
        mask_annotation_id?: string | null;
        label_class_id: string;
        mode: "paint" | "erase";
      };
      rasterEditPayloads.push(payload as unknown as Record<string, unknown>);
      const existing = payload.mask_annotation_id
        ? session.mask_annotations.find(
            (mask) => mask.id === payload.mask_annotation_id,
          )
        : undefined;
      const revision = (existing?.revision ?? 0) + 1;
      const maskId = existing?.id ?? "raster-mask-1";
      const raster: MaskRecord = {
        id: maskId,
        image_id: imageId,
        label_class_id: payload.label_class_id,
        geometry_kind: "raster_mask",
        mask_path: `projects/${project.id}/masks/${imageId}/${maskId}-r${revision}.png`,
        polygon_json: null,
        x_min: 100,
        y_min: 100,
        x_max: 500,
        y_max: 500,
        area_pixels: payload.mode === "erase" ? 900 : 1200,
        source_type: "human",
        provenance_json: null,
        status: "draft",
        created_by: "local_user",
        created_at: now,
        updated_at: now,
        deleted_at: null,
        revision,
      };
      session.mask_annotations = [
        ...session.mask_annotations.filter((mask) => mask.id !== maskId),
        raster,
      ];
      session.image = {
        ...session.image,
        annotation_revision: session.image.annotation_revision + 1,
        annotation_status: "in_progress",
      };
      session.counts_by_class = maskCounts(session.mask_annotations);
      await route.fulfill({
        json: { image: session.image, mask_annotation: raster },
      });
      return;
    }

    if (url.pathname.match(/\/images\/image-[12]\/content$/)) {
      await route.fulfill({ body: pngBytes, contentType: "image/png" });
      return;
    }
    if (url.pathname.match(/\/mask-annotations\/[^/]+\/content$/)) {
      await route.fulfill({ body: pngBytes, contentType: "image/png" });
      return;
    }
    await route.abort();
  });

  await mountBuiltApp(page);
  await page.getByRole("button", { name: /Milestone 2 Coral Study/ }).click();
  await page.getByRole("button", { name: "Annotate" }).first().click();
  await page.getByTestId("open-polygon-tool").click();
  await expect(page.getByTestId("mask-workspace")).toBeVisible();

  const layer = page.getByTestId("polygon-mask-layer");
  const layerBox = await layer.boundingBox();
  if (!layerBox) throw new Error("Polygon layer geometry is unavailable");
  const point = (x: number, y: number) => ({
    x: layerBox.x + layerBox.width * x,
    y: layerBox.y + layerBox.height * y,
  });
  for (const [x, y] of [
    [0.25, 0.25],
    [0.55, 0.25],
    [0.55, 0.55],
    [0.25, 0.55],
  ] as const) {
    const target = point(x, y);
    await page.mouse.click(target.x, target.y);
  }
  await page.getByTestId("polygon-draft-point-0").click();
  await expect(layer.locator("g[data-mask-id]")).toHaveCount(1);
  const maskId = await layer
    .locator("g[data-mask-id]")
    .getAttribute("data-mask-id");
  if (!maskId) throw new Error("Created polygon did not receive an ID");

  await page.getByTestId("move-polygon-nodes").click();
  await layer.locator(`g[data-mask-id="${maskId}"] polygon`).click();
  await expect(
    page.locator(`[data-testid^="mask-vertex-${maskId}-"]`),
  ).toHaveCount(4);

  const firstVertex = page.getByTestId(`mask-vertex-${maskId}-0`);
  const vertexBox = await firstVertex.boundingBox();
  if (!vertexBox) throw new Error("Polygon vertex geometry is unavailable");
  await page.mouse.move(
    vertexBox.x + vertexBox.width / 2,
    vertexBox.y + vertexBox.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(vertexBox.x + 35, vertexBox.y + 25, { steps: 5 });
  await page.mouse.up();

  await page.getByTestId("insert-polygon-node").click();
  await expect(page.getByTestId("enhanced-annotation-editor")).toHaveAttribute(
    "data-vertex-edit-mode",
    "insert",
  );
  const selectedPolygon = layer.locator(`g[data-mask-id="${maskId}"] polygon`);
  await selectedPolygon.click();
  const polygonPointCount = async () => {
    const points = await selectedPolygon.getAttribute("points");
    return points?.trim().split(/\s+/).filter(Boolean).length ?? 0;
  };
  await expect.poll(polygonPointCount).toBe(5);

  await page.getByTestId("move-polygon-nodes").click();
  await selectedPolygon.click();
  await expect(
    page.locator(`[data-testid^="mask-vertex-${maskId}-"]`),
  ).toHaveCount(5);

  await page.getByTestId("delete-polygon-node").click();
  await page.locator(`[data-testid^="mask-vertex-${maskId}-"]`).last().click();
  await expect.poll(polygonPointCount).toBe(4);
  await page.getByTestId("move-polygon-nodes").click();
  await selectedPolygon.click();
  await expect(
    page.locator(`[data-testid^="mask-vertex-${maskId}-"]`),
  ).toHaveCount(4);

  await page.getByRole("button", { name: "Muricea Open" }).click();
  await expect(page.locator(".annotation-selection-row strong")).toHaveText(
    "Muricea Open",
  );
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(".annotation-selection-row strong")).toHaveText(
    "Muricea Closed",
  );
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(page.locator(".annotation-selection-row strong")).toHaveText(
    "Muricea Open",
  );

  const saveButton = page
    .getByTestId("mask-workspace")
    .getByRole("button", { name: "Save now" });
  await expect(saveButton).toBeEnabled();
  await saveButton.click();
  await expect.poll(() => polygonSavePayloads.length).toBeGreaterThan(0);
  expect(
    (
      polygonSavePayloads.at(-1)?.mask_annotations as Array<{
        label_class_id: string;
      }>
    )[0].label_class_id,
  ).toBe("class-2");

  await page.getByTestId("open-brush-tool").click();
  await expect(page.getByTestId("raster-mask-workspace")).toBeVisible();
  const brush = page.getByTestId("raster-brush-layer");
  const brushBox = await brush.boundingBox();
  if (!brushBox) throw new Error("Raster brush geometry is unavailable");
  await page.mouse.move(brushBox.x + 100, brushBox.y + 100);
  await page.mouse.down();
  await page.mouse.move(brushBox.x + 220, brushBox.y + 180, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => rasterEditPayloads.length).toBe(1);
  await expect(page.getByRole("button", { name: "Erase" })).toBeEnabled();
  await page.getByRole("button", { name: "Erase" }).click();
  await page.mouse.move(brushBox.x + 160, brushBox.y + 140);
  await page.mouse.down();
  await page.mouse.move(brushBox.x + 190, brushBox.y + 155, { steps: 4 });
  await page.mouse.up();
  await expect.poll(() => rasterEditPayloads.length).toBe(2);
  expect(rasterEditPayloads.map((payload) => payload.mode)).toEqual([
    "paint",
    "erase",
  ]);
  expect(rasterEditPayloads[1].mask_annotation_id).toBe("raster-mask-1");

  await page.getByTestId("return-main-tools").click();
  await expect(page.getByTestId("annotation-editor")).toBeVisible();
  await page.keyboard.press("d");
  await expect(
    page
      .getByTestId("annotation-editor")
      .getByRole("heading", { name: "swiftia-day90.png" }),
  ).toBeVisible();
  await page.keyboard.press("a");
  await expect(
    page
      .getByTestId("annotation-editor")
      .getByRole("heading", { name: "swiftia-day0.png" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to gallery" }).click();

  await page.goto("about:blank");
  await mountBuiltApp(page);
  await page.getByRole("button", { name: /Milestone 2 Coral Study/ }).click();
  await page.getByRole("button", { name: "Annotate" }).first().click();
  await page.getByTestId("open-polygon-tool").click();
  await expect(page.getByTestId("mask-workspace")).toBeVisible();
  await expect(page.locator(`g[data-mask-id="${maskId}"]`)).toHaveCount(1);
  await page.getByTestId("move-polygon-nodes").click();
  await page.locator(`g[data-mask-id="${maskId}"] polygon`).click();
  await expect(page.locator(".annotation-selection-row strong")).toHaveText(
    "Muricea Open",
  );

  await page.getByTestId("open-brush-tool").click();
  await expect(
    page.getByRole("button", { name: /Muricea Closed \| r2/ }),
  ).toBeVisible();
});
