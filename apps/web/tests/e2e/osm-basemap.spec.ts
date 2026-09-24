import { expect, test } from "@playwright/test";
import path from "node:path";

const networkEnabled = process.env.REEFVISION_RUN_OSM_NETWORK_TEST === "1";

test.describe("ReefVision OpenStreetMap demo acceptance", () => {
  test.skip(!networkEnabled, "Real OSM network acceptance is opt-in.");

  test("renders live OSM tiles, attribution, and a dynamic metric scale", async ({
    page,
  }) => {
    const successfulTiles: string[] = [];

    page.on("response", (response) => {
      if (
        response.url().startsWith("https://tile.openstreetmap.org/") &&
        response.status() >= 200 &&
        response.status() < 400
      ) {
        successfulTiles.push(response.url());
      }
    });

    await page.setContent(`
        <!doctype html>
        <html>
          <head>
            <meta charset="utf-8" />
          </head>
          <body style="margin:0">
            <div
              id="map"
              style="width:900px;height:520px"
            ></div>
          </body>
        </html>
      `);

    // Playwright is running from apps/web, so resolve directly
    // from the local node_modules directory. This is ESM-safe.
    const leafletRoot = path.resolve("node_modules", "leaflet");

    await page.addStyleTag({
      path: path.join(leafletRoot, "dist", "leaflet.css"),
    });

    await page.addScriptTag({
      path: path.join(leafletRoot, "dist", "leaflet.js"),
    });

    await page.evaluate(() => {
      type DemoMap = {
        setZoom: (zoom: number) => void;
      };

      type LeafletGlobal = {
        map: (element: string) => {
          setView: (center: [number, number], zoom: number) => DemoMap;
        };

        tileLayer: (
          url: string,
          options: {
            maxZoom: number;
            attribution: string;
          },
        ) => {
          addTo: (map: DemoMap) => unknown;
        };

        control: {
          scale: (options: {
            position: string;
            metric: boolean;
            imperial: boolean;
            maxWidth: number;
          }) => {
            addTo: (map: DemoMap) => unknown;
          };
        };
      };

      const globals = window as typeof window & {
        L: LeafletGlobal;
        __reefvisionMap?: DemoMap;
      };

      const map = globals.L.map("map").setView([32.7765, -79.9311], 11);

      globals.__reefvisionMap = map;

      globals.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);

      globals.L.control
        .scale({
          position: "bottomleft",
          metric: true,
          imperial: false,
          maxWidth: 120,
        })
        .addTo(map);
    });

    await expect
      .poll(() => successfulTiles.length, {
        timeout: 20_000,
        message: "Expected at least one successful live OSM tile.",
      })
      .toBeGreaterThan(0);

    await expect(page.locator(".leaflet-tile-loaded").first()).toBeVisible();

    const attribution = page.locator(".leaflet-control-attribution");

    await expect(attribution).toBeVisible();

    await expect(attribution).toContainText("OpenStreetMap");

    const scale = page.locator(".leaflet-control-scale");

    await expect(scale).toBeVisible();

    const metricLines = page.locator(".leaflet-control-scale-line");

    // One line only = metric. No imperial line.
    await expect(metricLines).toHaveCount(1);

    await expect(metricLines.first()).toContainText(/(?:m|km)/);

    const scaleBefore = (await metricLines.first().textContent())?.trim();

    expect(scaleBefore).toBeTruthy();

    // Zoom substantially closer and verify that the
    // displayed reference distance changes.
    await page.evaluate(() => {
      const globals = window as typeof window & {
        __reefvisionMap?: {
          setZoom: (zoom: number) => void;
        };
      };

      globals.__reefvisionMap?.setZoom(18);
    });

    await expect
      .poll(async () => (await metricLines.first().textContent())?.trim(), {
        timeout: 5_000,
        message: "Expected metric scale to update after zoom.",
      })
      .not.toBe(scaleBefore);
  });
});
