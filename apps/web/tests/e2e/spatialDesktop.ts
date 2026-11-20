import { expect, test as base, type Page } from "@playwright/test";

interface SpatialDesktop {
  page: Page;
  web: string;
  api: string;
  surface: "tauri-webview2" | "source-browser";
}

export const test = base.extend<{
  desktop: SpatialDesktop;
  spatialWeb: string;
  spatialApi: string;
}>({
  spatialWeb: [process.env.REEFVISION_GUIDED_TEST_WEB ?? "", { option: true }],
  spatialApi: [process.env.REEFVISION_GUIDED_TEST_API ?? "", { option: true }],
  desktop: async ({ playwright, spatialWeb, spatialApi }, use, info) => {
    const endpoint = process.env.REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT;
    if (!spatialApi || (!spatialWeb && !endpoint)) {
      info.skip(
        true,
        "Requires the isolated ReefVision API and browser or packaged WebView2",
      );
      return;
    }
    if (
      endpoint &&
      !/^ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[a-z0-9-]+$/i.test(
        endpoint,
      )
    ) {
      throw new Error(
        "Spatial WebView2 acceptance requires a loopback CDP endpoint.",
      );
    }
    const browser = endpoint
      ? await playwright.chromium.connectOverCDP(endpoint, { isLocal: true })
      : await playwright.chromium.launch(info.project.use.launchOptions);
    try {
      if (endpoint) {
        const page = browser
          .contexts()
          .flatMap((context) => context.pages())
          .find((candidate) =>
            /^https?:\/\/tauri\.localhost(?:\/|$)/.test(candidate.url()),
          );
        if (!page)
          throw new Error(
            "The packaged ReefVision WebView2 target is unavailable.",
          );
        await expect
          .poll(() => page.evaluate(() => "__TAURI_INTERNALS__" in window))
          .toBe(true);
        await use({
          page,
          web: new URL("/", page.url()).href,
          api: spatialApi,
          surface: "tauri-webview2",
        });
      } else {
        await use({
          page: await browser.newPage(),
          web: spatialWeb,
          api: spatialApi,
          surface: "source-browser",
        });
      }
    } finally {
      await browser.close();
    }
  },
});
