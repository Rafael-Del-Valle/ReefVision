import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

test("imports sensor JSON and displays offline NOAA provenance in Environmental Context", async ({
  page,
}) => {
  const project = {
    id: "project-environment",
    name: "Environmental survey",
    slug: "environmental-survey",
    description: null,
    storage_root: "projects/project-environment",
    default_annotation_type: "bbox",
    georeference_height_offset_m: 0,
    georeference_height_evidence: null,
    created_at: "2026-10-18T00:00:00Z",
    updated_at: "2026-10-18T00:00:00Z",
    archived_at: null,
    label_classes: [],
  };
  const sensor = {
    variable: "water_temperature",
    value: 68,
    unit: "degF",
    observed_at: "2026-10-17T14:30:00+02:00",
    source_kind: "observed",
    provenance: { source: "Reef logger", acquired_at: "2026-10-18T00:00:00Z" },
  };
  const record = {
    ...sensor,
    schema_version: "1.1.0",
    id: "sensor-record",
    project_id: project.id,
    subject: {},
    depth_m: null,
    depth_reference: null,
    qc: "unassessed",
    qc_flags: [],
    normalized_value: 20,
    normalized_unit: "degC",
    normalized_uncertainty: null,
    content_sha256: "a".repeat(64),
  };
  const records: (typeof record)[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.2" } });
    } else if (url.pathname.endsWith("/project-summaries")) {
      await route.fulfill({
        json: [
          { ...project, label_class_count: 0, active_label_class_count: 0 },
        ],
      });
    } else if (url.pathname.endsWith(`/projects/${project.id}`)) {
      await route.fulfill({ json: project });
    } else if (url.pathname.endsWith("/images")) {
      await route.fulfill({
        json: { items: [], total: 0, page: 1, page_size: 24, pages: 0 },
      });
    } else if (url.pathname.endsWith("/scientific-records")) {
      if (request.method() === "POST") {
        expect(request.postDataJSON()).toEqual({ records: [sensor] });
        records.push(record);
        await route.fulfill({
          status: 201,
          json: { items: [record], total: 1 },
        });
      } else {
        expect(url.searchParams.get("limit")).toBe("100");
        await route.fulfill({
          json: { items: records, total: records.length },
        });
      }
    } else if (url.pathname.endsWith("/environment/noaa")) {
      expect(request.postDataJSON()).toEqual({
        station_id: "8724580",
        day: "2026-10-17",
        offline: true,
      });
      const noaa = {
        ...record,
        id: "noaa-record",
        provenance: {
          source: "NOAA CO-OPS",
          acquired_at: "2026-10-17T18:00:00Z",
        },
      };
      records.push(noaa);
      await route.fulfill({
        json: {
          items: [noaa],
          cache_status: "stale_offline",
          fetched_at: "2026-10-17T18:00:00Z",
          expires_at: "2026-10-18T00:00:00Z",
          source_url:
            "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=8724580",
          skipped_missing: 1,
        },
      });
    } else {
      await route.abort();
    }
  });

  const assetDirectory = path.resolve("dist/assets");
  const assets = await readdir(assetDirectory);
  const scriptName = assets.find(
    (name) => name.startsWith("index-") && name.endsWith(".js"),
  );
  const styleName = assets.find((name) => name.endsWith(".css"));
  if (!scriptName || !styleName)
    throw new Error("Vite build assets are missing");
  const [script, style, metadata] = await Promise.all([
    readFile(path.join(assetDirectory, scriptName), "utf8"),
    readFile(path.join(assetDirectory, styleName), "utf8"),
    readFile(path.resolve("package.json"), "utf8"),
  ]);
  await page.route("http://127.0.0.1:8000/", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<main id="root"></main>',
    }),
  );
  await page.goto("http://127.0.0.1:8000/");
  await page.evaluate(
    (version: string) =>
      window.localStorage.setItem(
        `reefvision.onboarding.dismissed.${version}`,
        "true",
      ),
    JSON.parse(metadata).version,
  );
  await page.addStyleTag({ content: style });
  await page.addScriptTag({ content: script, type: "module" });

  await page.getByRole("button", { name: /Environmental survey/ }).click();
  await page.getByRole("tab", { name: "Environmental Context" }).click();
  await expect(
    page.getByRole("heading", { name: "Environmental Context", level: 2 }),
  ).toBeVisible();
  await expect(page.getByText("No scientific records yet")).toBeVisible();
  await page.getByLabel("Sensor JSON file").setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from("{broken"),
  });
  await page.getByRole("button", { name: "Import sensor JSON" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "The selected file is not valid JSON.",
  );
  await page.getByLabel("Sensor JSON file").setInputFiles({
    name: "sensor.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ records: [sensor] })),
  });
  await page.getByRole("button", { name: "Import sensor JSON" }).click();
  await expect(page.getByText("Imported 1 scientific record.")).toBeVisible();
  await expect(page.getByText("68 degF")).toBeVisible();
  await expect(page.getByText("20 degC")).toBeVisible();
  await expect(page.getByText("2026-10-17 12:30:00 UTC")).toBeVisible();
  await expect(page.getByText("Unknown depth")).toBeVisible();

  await page.getByLabel("NOAA station ID").fill("8724580");
  await page.getByLabel("Observation day (UTC)").fill("2026-10-17");
  await page.getByLabel("Use cached data only (offline)").check();
  await page.getByRole("button", { name: "Import NOAA data" }).click();
  const result = page.getByLabel("NOAA import result");
  await expect(result).toContainText("Stale cache used offline");
  await expect(result).toContainText("Missing values skipped: 1");
  await expect(result).toContainText("2026-10-17 18:00:00 UTC");
  await expect(
    result.getByRole("link", { name: "NOAA source" }),
  ).toHaveAttribute("href", /station=8724580/);
  await expect(page.getByText("NOAA CO-OPS")).toBeVisible();
});
