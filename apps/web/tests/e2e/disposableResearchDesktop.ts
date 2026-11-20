import { realpath, stat } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { expect, type Page } from "@playwright/test";

export async function verifyResearchDesktop(page: Page, api: string) {
  const profile = process.env.REEFVISION_RESEARCH_TEST_PROFILE;
  const version = process.env.REEFVISION_RESEARCH_TEST_VERSION;
  const schema = process.env.REEFVISION_RESEARCH_TEST_SCHEMA;
  if (!profile || !isAbsolute(profile) || !version || !schema) {
    throw new Error(
      "Supply the isolated research profile, application version and schema before running this journey.",
    );
  }
  expect(new URL(api).origin).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
  const root = await realpath(profile);
  const markers = await Promise.all(
    [".reefvision-clean-install-acceptance", ".reefvision-disposable-qa"].map(
      async (name) =>
        (await stat(join(root, name)).catch(() => null))?.isFile(),
    ),
  );
  expect(markers, "The selected profile must be marked disposable").toContain(
    true,
  );
  const response = await page.request.get(`${api}/system/version`);
  expect(response.status(), await response.text()).toBe(200);
  const runtime = await response.json();
  expect(runtime).toMatchObject({
    application_version: version,
    current_schema_revision: schema,
    expected_schema_revision: schema,
    safe_mode: false,
  });
  expect(await realpath(runtime.data_dir)).toBe(root);
  expect(await realpath(runtime.database_path)).toBe(
    await realpath(join(root, "reefvision.db")),
  );
  return {
    application_version: version,
    schema_revision: schema,
    profile: root,
  };
}
