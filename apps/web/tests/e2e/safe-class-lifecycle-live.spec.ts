import { expect, type Locator } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { test } from "./spatialDesktop";

test("reviews class edits and preserves frozen exports after reopening", async ({
  desktop,
}, info) => {
  test.setTimeout(120_000);
  const { page, api, web } = desktop;
  const name = `Generated class study ${randomUUID().slice(0, 8)}`;
  const json = async (
    response: Awaited<ReturnType<typeof page.request.get>>,
  ) => {
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };
  const get = async (url: string) => json(await page.request.get(url));
  const digest = (contents: Buffer) =>
    createHash("sha256").update(contents).digest("hex");
  const project = await json(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
  );
  const root = `${api}/projects/${project.id}`;
  const addClass = async (label: string, index: number) =>
    json(
      await page.request.post(`${root}/classes`, {
        data: { name: label, class_index: index, display_color: "#356281" },
      }),
    );
  const source = await addClass("Source box", 0);
  const target = await addClass("Reviewed destination", 1);
  const protectedLabel = await addClass("Protected polygon", 2);
  const image = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAFAAAAA8CAIAAAB+RarbAAAAeUlEQVR4nOXOQQEAIBCAMKSZSYxjbVucD5Zg655NicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x6O+gGf/8sEBAAAAABJRU5ErkJggg==",
    "base64",
  );
  const imported = await json(
    await page.request.post(`${root}/imports/images`, {
      multipart: {
        files: {
          name: "generated-class-fixture.png",
          mimeType: "image/png",
          buffer: image,
        },
      },
    }),
  );
  const imageId = imported.successful[0].image_id;
  const annotation = `${api}/images/${imageId}/annotations`;
  const box = {
    id: randomUUID(),
    label_class_id: source.id,
    x_min: 5,
    y_min: 6,
    x_max: 20,
    y_max: 24,
  };
  const mask = {
    id: randomUUID(),
    label_class_id: protectedLabel.id,
    geometry_kind: "polygon",
    points: [
      { x: 24, y: 10 },
      { x: 42, y: 14 },
      { x: 29, y: 33 },
    ],
  };
  await json(
    await page.request.put(annotation, {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [box],
        mask_annotations: [mask],
      },
    }),
  );
  const classification = `${api}/images/${imageId}/classification-labels`;
  const labels = await json(
    await page.request.put(classification, {
      data: { label_class_ids: [protectedLabel.id] },
    }),
  );
  const before = await get(annotation);
  const frozen = await json(
    await page.request.post(`${root}/dataset-versions`, {
      data: {
        name: "Frozen before class edits",
        eligible_annotation_statuses: ["reviewed"],
        split_method: "manual",
        manual_assignments: [{ image_id: imageId, split: "train" }],
      },
    }),
  );
  const empty = await addClass("Unused example", 3);

  const health = await get(`${api}/health`);
  await page.addInitScript((version) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${version}`, "true");
  }, health.version);
  const open = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Data & annotation", exact: true })
      .click();
  };
  const openClasses = async () => {
    await open();
    await page.getByRole("tab", { name: "Classes", exact: true }).click();
  };
  const row = (label: string) =>
    page.locator(".class-row").filter({
      has: page
        .locator(".class-row-title strong")
        .getByText(label, { exact: true }),
    });
  const button = (classRow: Locator, label: string) =>
    classRow.getByRole("button", { name: label, exact: true });

  await openClasses();
  const protectedRow = row(protectedLabel.name);
  const unused = row(empty.name);
  await expect(button(protectedRow, "Delete unused")).toBeDisabled();
  await expect(button(unused, "Delete unused")).toBeDisabled();
  await button(protectedRow, "Usage").click();
  await expect(
    protectedRow.getByText("Active mask annotations", { exact: true }),
  ).toBeVisible();
  await expect(
    protectedRow.getByText("Active image-level classifications", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(button(protectedRow, "Delete unused")).toBeDisabled();
  await button(protectedRow, "Preview reassign").click();
  await expect(
    protectedRow.getByText(/cannot be safely reassigned in bulk/).first(),
  ).toBeVisible();
  await expect(button(protectedRow, "Run reassign")).toBeDisabled();
  await button(protectedRow, "Archive").click();
  await expect(button(protectedRow, "Restore")).toBeVisible();
  await button(protectedRow, "Restore").click();
  await expect(button(protectedRow, "Archive")).toBeVisible();

  const boxRow = row(source.name);
  await boxRow.getByLabel("Name for class 0").fill("Renamed source box");
  await boxRow.getByLabel(`Order for ${source.name}`).fill("8");
  await button(boxRow, "Save").click();
  const renamed = row("Renamed source box");
  await expect(renamed).toBeVisible();
  expect((await get(`${root}/classes`)).at(-1)).toMatchObject({
    id: source.id,
    class_index: 0,
    display_order: 8,
  });
  await renamed.getByLabel("Reassign into").selectOption(target.id);
  await renamed
    .getByLabel("Operation notes")
    .fill("Reviewed mapping of this generated box");
  await button(renamed, "Preview reassign").click();
  await expect(button(renamed, "Run reassign")).toBeEnabled();
  await renamed.getByText("Records in this preview", { exact: true }).click();
  await expect(renamed.getByText(box.id, { exact: true })).toBeVisible();
  const reassign = button(renamed, "Run reassign");
  await reassign.click();
  const reassignConfirmation = page.getByRole("alertdialog", {
    name: "Reassign class",
  });
  await expect(
    reassignConfirmation.getByRole("button", { name: "Cancel" }),
  ).toBeFocused();
  expect((await get(annotation)).image.annotation_revision).toBe(
    before.image.annotation_revision,
  );
  await page.keyboard.press("Escape");
  await expect(reassignConfirmation).toHaveCount(0);
  await expect(reassign).toBeFocused();
  expect((await get(annotation)).image.annotation_revision).toBe(
    before.image.annotation_revision,
  );
  await reassign.click();
  await reassignConfirmation
    .getByRole("button", { name: "Run reassign" })
    .click();
  await expect(
    renamed.getByText("Latest operation", { exact: true }),
  ).toBeVisible();
  await button(unused, "Usage").click();
  await expect(button(unused, "Delete unused")).toBeEnabled();
  await button(unused, "Delete unused").click();
  const deleteConfirmation = page.getByRole("alertdialog", {
    name: "Delete unused class",
  });
  await expect(deleteConfirmation).toBeVisible();
  await deleteConfirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(unused).toBeVisible();
  expect(
    (await get(`${root}/classes`)).some(
      (value: { id: string }) => value.id === empty.id,
    ),
  ).toBe(true);
  await button(unused, "Delete unused").click();
  await deleteConfirmation
    .getByRole("button", { name: "Delete unused class" })
    .click();
  await expect(unused).toHaveCount(0);

  await openClasses();
  await expect(renamed).toBeVisible();
  await expect(unused).toHaveCount(0);
  const after = await get(annotation);
  expect(after.annotations).toHaveLength(1);
  expect(after.annotations[0]).toMatchObject({
    ...box,
    label_class_id: target.id,
  });
  expect(after.image.annotation_revision).toBe(
    before.image.annotation_revision + 1,
  );
  expect(after.mask_annotations).toEqual(before.mask_annotations);
  expect(await get(classification)).toEqual(labels);
  const sourceContent = await page.request.get(
    `${api}/images/${imageId}/content`,
  );
  expect(sourceContent.ok()).toBeTruthy();
  expect(digest(await sourceContent.body())).toBe(digest(image));

  await page
    .getByRole("tab", { name: "Dataset versions", exact: true })
    .click();
  const exporting = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${api}/dataset-versions/${frozen.id}/exports`,
  );
  await page.getByRole("button", { name: "Export YOLO dataset" }).click();
  const { export: exported, job } = await json(await exporting);
  await expect
    .poll(async () => (await get(`${api}/jobs/${job.id}`)).status, {
      timeout: 20_000,
    })
    .toBe("succeeded");
  const manifest = await get(`${api}/exports/${exported.id}/manifest`);
  expect(manifest.dataset_version_manifest_sha256).toBe(frozen.manifest_sha256);
  expect(manifest.class_map).toEqual(frozen.class_map_json);
  expect(manifest.class_map).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        id: source.id,
        name: source.name,
        class_index: 0,
      }),
    ]),
  );
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download zip", exact: true }).click();
  const download = await downloading;
  const zipPath = info.outputPath("frozen-class-export.zip");
  await download.saveAs(zipPath);
  const zip = await readFile(zipPath);
  expect(zip.subarray(0, 2).toString()).toBe("PK");
  const servedZip = await page.request.get(
    `${api}/exports/${exported.id}/download`,
  );
  expect(servedZip.ok()).toBeTruthy();
  expect(digest(zip)).toBe(digest(await servedZip.body()));
  await writeFile(
    info.outputPath("class-lifecycle-evidence.json"),
    JSON.stringify(
      {
        surface: desktop.surface,
        project_id: project.id,
        original_sha256: digest(image),
        explicit_confirmation: true,
        reassign: {
          annotation_id: box.id,
          from: source.id,
          to: target.id,
          original_revision: before.image.annotation_revision,
          final_revision: after.image.annotation_revision,
        },
        protected: {
          class_id: protectedLabel.id,
          mask_id: mask.id,
          image_label_id: labels[0].id,
        },
        frozen: {
          dataset_version_id: frozen.id,
          manifest_sha256: frozen.manifest_sha256,
          archive_sha256: digest(zip),
        },
      },
      null,
      2,
    ),
  );
});
