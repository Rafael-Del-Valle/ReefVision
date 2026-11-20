import { expect } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { test } from "./spatialDesktop";

test("reopens offline currents, exports signed vectors, and reloads unassessed evidence", async ({
  desktop: { page, api, web, surface },
}, info) => {
  const fixture = process.env.REEFVISION_CURRENT_FIELD_FIXTURE;
  if (!fixture) {
    test.skip(
      true,
      "Generate the offline cache with scripts/seed_environmental_current_live.py.",
    );
    return;
  }
  test.setTimeout(60_000);
  const archive = await readFile(fixture);
  const sha256 = (bytes: Buffer) =>
    createHash("sha256").update(bytes).digest("hex");
  const name = `Synthetic offline currents ${randomUUID().slice(0, 8)}`;
  const imported = await page.request.post(`${api}/exchange-packages/import`, {
    multipart: {
      project_name: name,
      file: {
        name: "environmental-current.reefvision.zip",
        mimeType: "application/zip",
        buffer: archive,
      },
    },
  });
  expect(imported.status(), await imported.text()).toBe(201);
  const { project_id: projectId } = await imported.json();
  const environment = `${api}/projects/${projectId}/environment`;
  const datasets = await page.request.get(`${environment}/datasets`);
  expect(datasets.ok(), await datasets.text()).toBe(true);
  const inventory = await datasets.json();
  expect(inventory.items).toHaveLength(1);
  const [{ cache_key: cacheKey, provider, record_count: count }] =
    inventory.items;
  expect(provider).toBe("copernicus_marine");
  expect(count).toBe(8);
  const cached = await page.request.get(`${environment}/datasets/${cacheKey}`);
  expect(cached.ok(), await cached.text()).toBe(true);
  const { items } = await cached.json();
  const sourceIds = items.map(({ id }: { id: string }) => id).sort();
  const health = await page.request.get(`${api}/health`);
  expect(health.ok()).toBe(true);
  const { version } = await health.json();
  await page.addInitScript((version: string) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${version}`, "true");
  }, version);

  const openAnalyses = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Data & annotation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Environmental Context", exact: true })
      .click();
    await page.getByRole("tab", { name: "Analyses", exact: true }).click();
  };
  const openCurrentSlice = async () => {
    await page.getByLabel("Analysis task").selectOption("currents");
    await page.getByRole("button", { name: "Open ocean current map" }).click();
    await page.getByLabel("Cached ocean dataset").selectOption(cacheKey);
    await expect(page.getByText(/Mean speed: 2\.000 m\/s/)).toBeVisible();
    await expect(page.getByLabel("Online basemap tiles")).not.toBeChecked();
  };
  const downloadVectors = async (filename: string) => {
    const downloading = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Export current vector summary CSV" })
      .click();
    const destination = info.outputPath(filename);
    await (await downloading).saveAs(destination);
    return readFile(destination);
  };

  await openAnalyses();
  await openCurrentSlice();
  const originalCsv = await downloadVectors("current-vectors.csv");
  const [header, ...rows] = originalCsv.toString("utf8").trim().split(/\r?\n/);
  expect(header).toContain("east_velocity_m_per_s");
  expect(rows).toHaveLength(4);
  for (const row of rows) {
    expect(row).toMatch(/,"-79\.[45]","5","sea_surface","-2","0","2","270",/);
    expect(row).toContain('"unassessed","unassessed"');
  }

  const saving = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${environment}/analyses/current-streamline`,
  );
  await page
    .getByRole("button", { name: "Calculate bounded streamlines" })
    .click();
  const saved = await saving;
  expect(saved.status(), await saved.text()).toBe(201);
  const { result } = await saved.json();
  const resultPane = page.getByRole("region", {
    name: "Current streamline result",
  });
  await expect(resultPane).toContainText(result.id);
  await expect(resultPane).toContainText("unassessed QC");
  await expect(resultPane).toContainText("uncertainty is not propagated");
  expect(result.quality_control).toMatchObject({
    status: "unassessed",
    flags: ["unassessed_current_input"],
  });
  expect(result.payload.streamlines).toHaveLength(4);
  expect([...result.source_record_ids].sort()).toEqual(sourceIds);
  expect(result.content_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(result.payload.input_sha256).toMatch(/^[a-f0-9]{64}$/);

  await openAnalyses();
  await page.getByLabel("Analysis task").selectOption("saved");
  await page.getByRole("button", { name: "Load saved analyses" }).click();
  const evidence = page.getByRole("article", {
    name: "Saved environmental analysis",
  });
  await expect(
    evidence.getByRole("heading", { name: "Current streamlines", exact: true }),
  ).toBeVisible();
  await expect(evidence).toContainText("Quality control: unassessed");
  await expect(
    evidence.getByRole("link", { name: "Download evidence CSV" }),
  ).toHaveAttribute("href", new RegExp(`${result.id}\\.csv$`));
  await evidence.getByRole("button", { name: "Check evidence" }).click();
  await expect(evidence.getByRole("status")).toContainText(
    "Evidence is current",
  );
  const reopened = await page.request.get(
    `${environment}/analyses/results/${result.id}`,
  );
  expect(reopened.status(), await reopened.text()).toBe(200);
  expect(await reopened.json()).toEqual(result);

  await openCurrentSlice();
  const reopenedCsv = await downloadVectors("reopened-current-vectors.csv");
  expect(sha256(reopenedCsv)).toBe(sha256(originalCsv));
  await writeFile(
    info.outputPath("environmental-current-receipt.json"),
    JSON.stringify(
      {
        surface,
        archive_sha256: sha256(archive),
        project_id: projectId,
        cache_key: cacheKey,
        source_record_ids: sourceIds,
        result_id: result.id,
        content_sha256: result.content_sha256,
        input_sha256: result.payload.input_sha256,
        quality_control: result.quality_control,
        csv_sha256: sha256(originalCsv),
      },
      null,
      2,
    ),
  );
});
