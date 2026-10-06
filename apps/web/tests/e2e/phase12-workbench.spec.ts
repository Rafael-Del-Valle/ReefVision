import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const project = {
  id: "phase12e-project",
  name: "Phase 12 Acceptance Project",
  slug: "phase-12-acceptance-project",
  description: "Scientist workspace acceptance",
  storage_root: "projects/phase-12-acceptance-project",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-05T00:00:00Z",
  updated_at: "2026-10-05T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

async function mockApi(page: Parameters<typeof test>[0]["page"]) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname.endsWith("/health")) {
      await route.fulfill({
        json: {
          status: "ok",
          version: "1.0.5",
        },
      });
      return;
    }

    if (
      url.pathname.endsWith("/project-summaries") &&
      request.method() === "GET"
    ) {
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
            archived_at: null,
            label_class_count: 0,
            active_label_class_count: 0,
          },
        ],
      });
      return;
    }

    if (
      url.pathname.endsWith(`/projects/${project.id}`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: project,
      });
      return;
    }

    if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
      await route.fulfill({
        json: {
          items: [],
          total: 0,
          page: 1,
          page_size: 24,
          pages: 0,
        },
      });
      return;
    }

    if (url.pathname.endsWith(`/projects/${project.id}/models`)) {
      await route.fulfill({
        json: [],
      });
      return;
    }

    await route.abort();
  });
}

async function mountBuiltApp(page: Parameters<typeof test>[0]["page"]) {
  const assetDirectory = path.resolve("dist/assets");

  const assets = await readdir(assetDirectory);

  const scriptName = assets.find(
    (name) => name.startsWith("index-") && name.endsWith(".js"),
  );

  const styleName = assets.find(
    (name) => name.startsWith("index-") && name.endsWith(".css"),
  );

  if (!scriptName || !styleName) {
    throw new Error("Vite entry assets are missing");
  }

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
  ) as {
    version: string;
  };

  await page.evaluate((version) => {
    window.localStorage.setItem(
      `reefvision.onboarding.dismissed.${version}`,
      "true",
    );
  }, packageMetadata.version);

  await page.addStyleTag({
    content: style,
  });

  await page.addScriptTag({
    content: script,
    type: "module",
  });
}

async function hasHorizontalOverflow(page: Parameters<typeof test>[0]["page"]) {
  return page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
}

test("supports keyboard skip navigation and the minimum desktop viewport without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({
    width: 1200,
    height: 760,
  });

  await mockApi(page);
  await mountBuiltApp(page);

  const skipLink = page.getByRole("link", {
    name: "Skip to main content",
  });

  await page.keyboard.press("Tab");

  await expect(skipLink).toBeFocused();

  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/#reefvision-main-content$/);

  expect(await hasHorizontalOverflow(page)).toBe(false);

  await page
    .getByRole("button", {
      name: "Open Phase 12 Acceptance Project",
    })
    .click();

  await expect(
    page.getByRole("heading", {
      name: "Project gallery",
    }),
  ).toBeVisible();

  await expect(
    page.getByRole("complementary", { name: "Project workspace navigation" }),
  ).toBeVisible();

  await expect(page.getByLabel("Workspace inspector")).toBeVisible();

  expect(await hasHorizontalOverflow(page)).toBe(false);
});

test("keeps the complete three-column scientist workbench usable at the default desktop size", async ({
  page,
}) => {
  await page.setViewportSize({
    width: 1440,
    height: 960,
  });

  await mockApi(page);
  await mountBuiltApp(page);

  await page
    .getByRole("button", {
      name: "Open Phase 12 Acceptance Project",
    })
    .click();

  await expect(
    page.getByRole("complementary", { name: "Project workspace navigation" }),
  ).toBeVisible();

  await expect(page.getByLabel("Workspace inspector")).toBeVisible();

  await expect(page.getByLabel("Inspector layout controls")).toBeVisible();

  expect(await hasHorizontalOverflow(page)).toBe(false);
});
