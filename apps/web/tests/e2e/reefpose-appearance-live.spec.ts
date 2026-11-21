import { expect, type Response } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { test } from "./spatialDesktop";

interface AppearanceFixture {
  project_id: string;
  project_name: string;
  model_id: string;
  model_sha256: string;
  reference_id: string;
  rater: string;
  videos: {
    id: string;
    observations: { striped: string[]; spotted: string[] };
  }[];
  fixture_roles: Record<"Reviewer A" | "Reviewer B" | "Adjudicator", string>;
}

test("reviews cross-video appearances, held-out errors and saved replay", async ({
  desktop,
}, info) => {
  const seed = process.env.REEFVISION_APPEARANCE_TEST_SEED;
  test.skip(
    !seed,
    "Requires a disposable generated appearance fixture and local trained weights",
  );
  test.setTimeout(150000);
  const { page, api, web, surface } = desktop;
  const fixture = JSON.parse(
    await readFile(seed!, "utf8"),
  ) as AppearanceFixture;
  const device = process.env.REEFVISION_APPEARANCE_TEST_DEVICE ?? "cpu";
  const name = "Synthetic appearance " + randomUUID().slice(0, 8);
  const root = api + "/projects/" + fixture.project_id;
  const probe = fixture.videos[2].observations.striped[0];
  const match = fixture.videos[3].observations.striped[0];
  const other = fixture.videos[3].observations.spotted[0];
  const health = await (await page.request.get(api + "/health")).json();
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        "reefvision.onboarding.dismissed." + version,
        "true",
      ),
    health.version,
  );
  async function openIdentity() {
    await page.goto(web);
    await page
      .getByRole("button", {
        name: "Open " + fixture.project_name,
        exact: true,
      })
      .click();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & tracking", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: "Video", exact: true })
      .first()
      .selectOption(fixture.videos[2].id);
    await page
      .getByText("Appearance across gaps and recordings", { exact: true })
      .click();
  }
  await openIdentity();
  const panel = page.getByRole("region", { name: "Appearance comparison" });
  await panel.getByLabel("Study name").fill(name);
  await panel
    .getByLabel("Trained native checkpoint")
    .selectOption(fixture.model_id);
  await panel
    .getByLabel("Reviewed probe from this recording")
    .selectOption(probe);
  await panel
    .getByLabel("Reviewed gallery observations")
    .selectOption([other, match]);
  await panel.getByLabel("Minimum same-recording gap (seconds)").fill("0.9");
  await panel.getByLabel("Minimum winning margin").fill("0");
  await panel
    .getByLabel("Frozen independent reference")
    .selectOption(fixture.reference_id);
  await panel.getByLabel("Reference rater").selectOption(fixture.rater);
  await panel.getByLabel(/Prespecified held-out false-match limit/).fill("0.1");
  await panel
    .getByLabel(/Prespecified held-out missed-match limit/)
    .fill("0.2");
  await panel.getByLabel("Appearance device").selectOption(device);
  const waitForPost = (url: string) =>
    page.waitForResponse(
      (response: Response) =>
        response.request().method() === "POST" && response.url() === url,
    );
  const queued = waitForPost(root + "/pose-appearance/studies");
  await panel
    .getByRole("button", { name: "Compare reviewed appearances" })
    .click();
  expect((await queued).status()).toBe(202);
  const result = panel.getByRole("article", { name: "Appearance result" });
  await expect(result.getByRole("heading", { name })).toBeVisible({
    timeout: 45000,
  });
  await expect(result).toContainText(
    "False matches 0/8 (0.000). Missed matches 0/8 (0.000).",
  );
  await expect(result.getByRole("img", { name: /Gallery crop/ })).toHaveCount(
    2,
  );
  await expect(result.getByText(/proposed match/)).toBeVisible();
  await expect(result.getByText(/Within the prespecified limit/)).toHaveCount(
    2,
  );
  const study = await panel.getByLabel("Saved appearance study").inputValue();
  const studyUrl = root + "/pose-appearance/studies/" + study;
  async function review(
    actor: keyof AppearanceFixture["fixture_roles"],
    outcome: string,
  ) {
    await result
      .getByLabel("Reviewer Lab role key")
      .fill(fixture.fixture_roles[actor]);
    await result.getByLabel("Reviewed gallery candidate").selectOption(match);
    await result.getByLabel("Identity judgement").selectOption(outcome);
    await result
      .getByLabel("Judgement reason")
      .fill("Generated control " + actor);
    const posted = waitForPost(studyUrl + "/reviews");
    await result
      .getByRole("button", { name: "Record independent judgement" })
      .click();
    const response = await posted;
    expect(response.status(), await response.text()).toBe(200);
    return response.json();
  }
  await review("Reviewer A", "same");
  await expect(result).not.toContainText("Generated control Reviewer A");
  await review("Reviewer B", "different");
  await expect(result).toContainText("disputed");
  await review("Adjudicator", "same");
  await expect(result).toContainText("Review: same");
  await expect(
    result.getByRole("link", { name: "Export appearance report" }),
  ).toHaveAttribute("href", studyUrl + "/export");
  const report = await (await page.request.get(studyUrl + "/export")).json();
  expect(report.snapshot.result.ranking.selected).toBe(match);
  expect(report.snapshot.result.device).toContain(device);
  expect(report.snapshot.inputs.model.sha256).toBe(fixture.model_sha256);
  expect(report.decisions).toHaveLength(3);
  await result
    .getByRole("button", { name: "Save replay in Workflow Builder" })
    .click();
  await expect(panel.getByText(/Saved workflow/)).toBeVisible();
  await page
    .getByRole("tab", { name: "Workflow builder", exact: true })
    .click();
  const saved = page
    .getByRole("listitem")
    .filter({ has: page.getByText("Replay " + name, { exact: true }) });
  const started = waitForPost(root + "/workflow-runs");
  await saved.getByRole("button", { name: "Run saved revision" }).click();
  const run = await (await started).json();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(api + "/workflow-runs/" + run.id)
          ).json()
        ).run.status,
      { timeout: 45000 },
    )
    .toBe("succeeded");
  const runDetail = await (
    await page.request.get(api + "/workflow-runs/" + run.id)
  ).json();
  const verified = runDetail.artifacts.find(
    (item: { data_type: string }) =>
      item.data_type === "pose_appearance_report",
  );
  expect(verified.payload_json.study_sha256).toBe(report.content_sha256);
  await openIdentity();
  await panel.getByLabel("Saved appearance study").selectOption(study);
  await expect(result).toContainText("Generated control Adjudicator");
  await result.screenshot({ path: info.outputPath("appearance-result.png") });
  await writeFile(
    info.outputPath("appearance-reidentification.json"),
    JSON.stringify(
      {
        surface,
        version: health.version,
        project_id: fixture.project_id,
        study_id: study,
        study_sha256: report.content_sha256,
        model_sha256: fixture.model_sha256,
        device: report.snapshot.result.device,
        reference_kind: report.snapshot.inputs.reference.data_kind,
        heldout: report.snapshot.result.evaluation.heldout,
        role_slots: report.decisions.map(
          (d: { role_slot: string }) => d.role_slot,
        ),
        workflow_run_id: run.id,
        workflow_artifact_sha256: verified.payload_sha256,
      },
      null,
      2,
    ),
    "utf8",
  );
});
