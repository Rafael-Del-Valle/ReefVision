import { expect, test, type APIResponse } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

const tile = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAFUlEQVR4nGNUDc5iwA2Y8MgxjFxpAB0EAPaXFk9sAAAAAElFTkSuQmCC",
  "base64",
);

async function checked(response: APIResponse, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return response.json();
}

function csvFields(line: string) {
  return Array.from(
    line.matchAll(/(?:^|,)(?:"((?:[^"]|"")*)"|([^,]*))/g),
    ([, quoted, plain]) => quoted?.replaceAll('""', '"') ?? plain,
  );
}

test("reviews projected-plane density in coverage, saved workflow replay, and CSV", async ({
  page,
}, info) => {
  const web = process.env.REEFVISION_GUIDED_TEST_WEB;
  const api = process.env.REEFVISION_GUIDED_TEST_API;
  test.skip(!web || !api, "Requires the isolated ReefVision API and frontend");

  const name = `Synthetic projected density ${randomUUID().slice(0, 8)}`;
  const { id: project } = await checked(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
    201,
  );
  const base = `${api}/projects/${project}`;
  async function label(classIndex: number, labelName: string) {
    return checked(
      await page.request.post(`${base}/classes`, {
        data: {
          class_index: classIndex,
          name: labelName,
          display_color: "#346178",
        },
      }),
      201,
    );
  }
  const target = await label(0, "Counted organisms");
  const excluded = await label(1, "Excluded class");
  const imported = await checked(
    await page.request.post(`${base}/imports/images`, {
      multipart: {
        files: {
          name: "reference-plane.png",
          mimeType: "image/png",
          buffer: tile,
        },
      },
    }),
    200,
  );
  const imageId = imported.successful[0].image_id;
  function rectangle(labelId: string, x: number, y: number) {
    return {
      id: randomUUID(),
      label_class_id: labelId,
      geometry_kind: "polygon",
      points: [
        { x, y },
        { x: x + 1, y },
        { x: x + 1, y: y + 1 },
        { x, y: y + 1 },
      ],
    };
  }
  await checked(
    await page.request.put(`${api}/images/${imageId}/annotations`, {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [],
        mask_annotations: [
          rectangle(target.id, 0, 0),
          rectangle(target.id, 1, 0),
          rectangle(target.id, 5, 5),
          rectangle(excluded.id, 0, 1),
        ],
      },
    }),
    200,
  );
  await checked(
    await page.request.put(`${api}/images/${imageId}/measurement-calibration`, {
      data: {
        distance_per_pixel: 10,
        unit: "cm",
        source: "Synthetic analytical homography",
        perspective_homography: [
          [1, 0, 0],
          [0, 1, 0],
          [1, 0, 1],
        ],
      },
    }),
    200,
  );

  const { version } = JSON.parse(await readFile("package.json", "utf8")) as {
    version: string;
  };
  await page.addInitScript(
    (current) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${current}`,
        "true",
      ),
    version,
  );
  const openProject = async () => {
    await page.goto(web!);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  };
  const openCoverage = async () => {
    await page
      .getByRole("tab", { name: "Data & annotation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Computed Metrics", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Open verified mask coverage", exact: true })
      .click();
  };
  const openWorkflow = async () => {
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Workflow builder", exact: true })
      .click();
  };

  await openProject();
  await openCoverage();
  const coverage = page.getByRole("region", {
    name: "Verified mask area and coverage",
  });
  await coverage.getByLabel("Coverage name").fill("Declared analytical plane");
  await coverage.getByLabel("Target class IDs").fill(target.id);
  await coverage.getByLabel("Saved ROI polygons (JSON)").fill(
    JSON.stringify([
      {
        image_id: imageId,
        points: [
          [0, 0],
          [2, 0],
          [2, 2],
          [0, 2],
        ],
      },
    ]),
  );
  await coverage
    .getByRole("checkbox", {
      name: "Use reference-plane homography for physical values",
    })
    .check();
  const pendingDefinition = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/computed-mask-coverage-definitions"),
  );
  await coverage
    .getByRole("button", { name: "Save coverage definition", exact: true })
    .click();
  const defined = await pendingDefinition;
  expect(defined.status(), await defined.text()).toBe(201);
  const definition = await defined.json();
  await coverage.getByLabel("Coverage image IDs").fill(imageId);
  const pendingPreview = page.waitForResponse((response) =>
    response.url().endsWith(`/${definition.id}/preview`),
  );
  await coverage
    .getByRole("button", { name: "Preview mask coverage", exact: true })
    .click();
  const previewResponse = await pendingPreview;
  expect(previewResponse.status(), await previewResponse.text()).toBe(200);
  const preview = await previewResponse.json();

  // The third verified target is outside the ROI. The fourth mask is an
  // unrelated class inside it. Only the first two enter the numerator.
  expect(preview.mask_count).toBe(3);
  expect(preview.density_object_count).toBe(2);
  expect(
    preview.area_by_class.map(
      (entry: { label_class_id: string }) => entry.label_class_id,
    ),
  ).toEqual([target.id]);
  expect(preview.calibration_method).toBe("projective_reference_plane");
  expect(preview.physical_unit).toBe("cm");
  expect(preview.roi_denominator_pixels).toBe(9);
  expect(preview.sampling_area_physical).toBeCloseTo(45 / 32, 12);
  expect(preview.target_union_in_roi_physical).toBeCloseTo(15 / 16, 12);
  expect(preview.object_density_per_square_unit).toBeCloseTo(64 / 45, 12);
  await expect(coverage.getByText(/1\.42222.*masks\/cm²/)).toBeVisible();
  await expect(
    coverage
      .getByText("Density numerator masks", { exact: true })
      .locator("..")
      .locator("dd"),
  ).toHaveText("2");

  const pendingSave = page.waitForResponse((response) =>
    response.url().endsWith(`/${definition.id}/calculate`),
  );
  await coverage
    .getByRole("button", { name: "Save immutable coverage", exact: true })
    .click();
  const saveResponse = await pendingSave;
  expect(saveResponse.status(), await saveResponse.text()).toBe(201);
  const saved = await saveResponse.json();

  await openWorkflow();
  await page
    .getByRole("combobox", { name: "Template", exact: true })
    .selectOption("verified-mask-coverage");
  const advanced = page.getByText("Advanced: edit workflow JSON directly", {
    exact: true,
  });
  await advanced.click();
  const jsonField = advanced.locator("..").locator("textarea");
  const graph = JSON.parse(await jsonField.inputValue());
  graph.nodes.find(
    (node: { node_type: string }) => node.node_type === "mask_coverage",
  ).parameters = {
    definition_id: definition.id,
    image_ids: [imageId],
  };
  await jsonField.fill(JSON.stringify(graph, null, 2));
  async function run(click: () => Promise<void>) {
    const queued = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith("/workflow-runs"),
    );
    await click();
    const response = await queued;
    expect(response.status(), await response.text()).toBe(202);
    const run = await response.json();
    await expect
      .poll(
        async () => {
          const detail = await checked(
            await page.request.get(`${api}/workflow-runs/${run.id}`),
            200,
          );
          return detail.run.status;
        },
        { timeout: 20_000 },
      )
      .toBe("succeeded");
    const detail = await checked(
      await page.request.get(`${api}/workflow-runs/${run.id}`),
      200,
    );
    const artifact = detail.artifacts.find(
      (item: { data_type: string }) =>
        item.data_type === "computed_metric_result",
    );
    expect(artifact.payload_json).toMatchObject({
      definition_id: definition.id,
      density_object_count: 2,
      mask_count: 3,
      physical_unit: "cm",
      calibration_method: "projective_reference_plane",
      evidence_sha256: saved.evidence_sha256,
    });
    expect(artifact.payload_json.object_density_per_square_unit).toBeCloseTo(
      64 / 45,
      12,
    );
    return { run, resultId: artifact.payload_json.result_id };
  }
  const first = await run(() =>
    page.getByRole("button", { name: "Save & run", exact: true }).click(),
  );
  await openProject();
  await openWorkflow();
  const revision = page
    .getByRole("listitem")
    .filter({ hasText: "Verified mask area and coverage" });
  const replay = await run(() =>
    revision
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click(),
  );
  expect(replay.run.id).not.toBe(first.run.id);
  expect(replay.run.workflow_graph_record_id).toBe(
    first.run.workflow_graph_record_id,
  );

  await openCoverage();
  const downloaded = page.waitForEvent("download");
  await coverage
    .getByRole("link", { name: "Export mask coverage CSV", exact: true })
    .click();
  const csv = await downloaded;
  const path = info.outputPath("projected-plane-density.csv");
  await csv.saveAs(path);
  const [heading, ...lines] = (await readFile(path, "utf8"))
    .trimEnd()
    .split(/\r?\n/);
  const headers = csvFields(heading);
  const rows = lines.map((line) =>
    Object.fromEntries(
      csvFields(line).map((value, index) => [headers[index], value]),
    ),
  );
  for (const resultId of [saved.id, first.resultId, replay.resultId]) {
    const row = rows.find(
      (item) => item.row_kind === "overall" && item.result_id === resultId,
    );
    expect(row).toMatchObject({
      physical_unit: "cm",
      mask_count: "3",
      density_object_count: "2",
      evidence_sha256: saved.evidence_sha256,
    });
    expect(Number(row?.sampling_area_physical)).toBeCloseTo(45 / 32, 12);
    expect(Number(row?.object_density_per_square_unit)).toBeCloseTo(
      64 / 45,
      12,
    );
  }
});
