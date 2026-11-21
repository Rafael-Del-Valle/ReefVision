import { expect } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { test } from "./spatialDesktop";

interface Seed {
  project_name: string;
  project_id: string;
  fixture_role: string;
  form: {
    audio_report_id: string;
    event_label: string;
    channel: number;
    maximum_time_uncertainty_us: number;
    coverage_evidence: string;
    identity_evidence: string;
    footprint: {
      station: string;
      grid: string;
      bounds_xyxy: number[];
      registration_error_px: number;
      maximum_total_error_px: number;
      evidence: string;
    };
    exposures: {
      index_id: string;
      annotation_evidence_id: string;
      start_utc: string;
      end_utc: string;
      uncertainty_us: number;
      clock_evidence: string;
      station_grid_offset_xy: number[];
      registration_evidence: string;
    }[];
  };
}

test("aligns reviewed audio and optical surveys, withholds conflicts and reopens a saved graph", async ({
  desktop,
}, info) => {
  const input = process.env.REEFVISION_MULTIMODAL_TEST_SEED;
  test.skip(!input, "Requires a disposable generated paired-survey project");
  test.setTimeout(120000);
  const { page, api, web, surface } = desktop;
  const seed: Seed = JSON.parse(await readFile(input!, "utf8"));
  const form = seed.form;
  const base = api + "/projects/" + seed.project_id;
  const version = (await (await page.request.get(api + "/health")).json())
    .version;
  await page.addInitScript(
    (v) => localStorage.setItem("reefvision.onboarding.dismissed." + v, "true"),
    version,
  );
  const name = "Paired station " + randomUUID().slice(0, 8);
  async function open() {
    await page.goto(web);
    await page
      .getByRole("button", { name: "Open " + seed.project_name, exact: true })
      .click();
    await page.getByRole("tab", { name: "Research", exact: true }).click();
    await page
      .getByRole("tab", { name: "Multimodal analysis", exact: true })
      .click();
  }
  await open();
  const panel = page.getByRole("region", { name: "Multimodal analysis" });
  const set = (key: string, val: string | number) =>
    panel.getByLabel(key, { exact: true }).fill(String(val));
  await set("Study name", name);
  await panel
    .getByLabel("Frozen acoustic report")
    .selectOption(form.audio_report_id);
  await set("Reviewed event label", form.event_label);
  await set("Acoustic channel (zero-based)", form.channel);
  await set(
    "Maximum combined clock uncertainty (µs)",
    form.maximum_time_uncertainty_us,
  );
  await panel.getByRole("checkbox", { name: /complete recording/ }).check();
  await set("Acoustic review coverage evidence", form.coverage_evidence);
  await set("Station", form.footprint.station);
  await set("Reference grid name", form.footprint.grid);
  for (const [i, side] of ["left", "top", "right", "bottom"].entries()) {
    await set("Footprint " + side + " (px)", form.footprint.bounds_xyxy[i]);
  }
  await set(
    "Footprint registration uncertainty (px)",
    form.footprint.registration_error_px,
  );
  await set(
    "Maximum total spatial uncertainty (px)",
    form.footprint.maximum_total_error_px,
  );
  await set("Footprint evidence", form.footprint.evidence);
  for (const [i, e] of form.exposures.entries()) {
    const row = panel.getByRole("group", {
      name: "Optical observation " + (i + 1),
      exact: true,
    });
    await row.getByLabel("Calibrated index").selectOption(e.index_id);
    await row
      .getByLabel("Reviewed organism box")
      .selectOption(e.annotation_evidence_id);
    await row.getByLabel("Exposure start with UTC offset").fill(e.start_utc);
    await row.getByLabel("Exposure end with UTC offset").fill(e.end_utc);
    await row
      .getByLabel("Exposure time uncertainty (µs)")
      .fill(String(e.uncertainty_us));
    await row.getByLabel("Clock evidence").fill(e.clock_evidence);
    await row
      .getByLabel("Grid translation X (px)")
      .fill(String(e.station_grid_offset_xy[0]));
    await row
      .getByLabel("Grid translation Y (px)")
      .fill(String(e.station_grid_offset_xy[1]));
    await row.getByLabel("Translation evidence").fill(e.registration_evidence);
  }
  await panel
    .getByLabel("Organism correspondence")
    .selectOption("same organism");
  await set("Identity evidence", form.identity_evidence);
  async function freeze() {
    await set("Reviewer Lab role key", seed.fixture_role);
    const posted = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url() === base + "/multimodal/studies",
    );
    await panel.getByRole("button", { name: "Freeze paired study" }).click();
    const response = await posted;
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  }
  const signed = await freeze();
  const result = panel.getByRole("article", { name: "Paired survey result" });
  await expect(result).toContainText("Exposed minus control: 0.3000");
  await expect(
    result.getByRole("cell", { name: "16", exact: true }),
  ).toHaveCount(2);
  await expect(result).toContainText("outside reviewed events");
  await result
    .getByText("Optical calibration and source records", { exact: true })
    .click();
  await expect(result.getByText(/800 nm.*Generated optical panel/)).toHaveCount(
    2,
  );
  await result
    .getByRole("button", { name: "Recompute from originals" })
    .click();
  await expect(result.getByText("Recomputed the frozen study.")).toBeVisible();
  const exportUrl = await result
    .getByRole("link", { name: "Export survey report" })
    .getAttribute("href");
  expect(exportUrl).toBe(base + "/multimodal/studies/" + signed.id + "/export");
  const exported = await (await page.request.get(exportUrl!)).json();
  expect(exported.content_sha256).toBe(signed.content_sha256);
  await result.screenshot({
    path: info.outputPath("paired-optical-acoustic.png"),
  });
  await result
    .getByRole("button", { name: "Save replay in Workflow Builder" })
    .click();
  await expect(result.getByText(/Saved workflow/)).toBeVisible();
  await set("Study name", name + " uncertain alignment");
  await set("Maximum combined clock uncertainty (µs)", 5);
  const withheld = await freeze();
  await expect(result).toContainText("Shared result withheld");
  await expect(result).toContainText(
    "Combined clock uncertainty exceeds the declared tolerance.",
  );
  expect(withheld.snapshot.result.exposed_minus_control).toBeNull();
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Workflow builder", exact: true })
    .click();
  const item = page
    .getByRole("listitem")
    .filter({ has: page.getByText("Replay " + name, { exact: true }) });
  const posted = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" && r.url() === base + "/workflow-runs",
  );
  await item.getByRole("button", { name: "Run saved revision" }).click();
  const run = await (await posted).json();
  const fetchRun = async () =>
    await (await page.request.get(api + "/workflow-runs/" + run.id)).json();
  await expect
    .poll(async () => (await fetchRun()).run.status)
    .toBe("succeeded");
  const artifact = (await fetchRun()).artifacts.find(
    (a: { data_type: string }) => a.data_type === "multimodal_study_report",
  );
  expect(artifact.payload_json.result).toEqual(signed.snapshot.result);
  await open();
  await panel.getByLabel("Saved multimodal studies").selectOption(signed.id);
  await expect(result).toContainText("Exposed minus control: 0.3000");
  await writeFile(
    info.outputPath("paired-optical-acoustic.json"),
    JSON.stringify(
      {
        surface,
        version,
        fixture: "generated paired acoustic and calibrated optical survey",
        project_id: seed.project_id,
        study_id: signed.id,
        study_sha256: signed.content_sha256,
        result: signed.snapshot.result,
        withheld_study_id: withheld.id,
        withheld_sha256: withheld.content_sha256,
        withheld_reasons: withheld.snapshot.result.reasons,
        workflow_run_id: run.id,
        workflow_artifact_sha256: artifact.payload_sha256,
      },
      null,
      2,
    ),
    "utf8",
  );
});
