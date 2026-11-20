import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test } from "./spatialDesktop";

type Grouping = { recording_id: string; animal_id: string };
type FrozenSource = {
  recording: { id: string };
  frame_track: { id: string };
  reviewed_track: { id: string };
  identity: { animal_id: string };
  source_grouping: Grouping;
  split: string;
};

test("declares grouped pose acquisition, verifies a pose, and freezes the same disjoint temporal sources", async ({
  desktop: { page, api, web },
}, info) => {
  const receipt = process.env.REEFVISION_LINEAGE_FIXTURE_RECEIPT;
  test.skip(!receipt, "Requires the synthetic ReefPose lineage fixture.");
  test.setTimeout(90000);
  const fixture = JSON.parse(await readFile(receipt!, "utf8")) as {
    round: { project_id: string };
    items: {
      video_id: string;
      video_track_id: string;
      acquisition_provenance_json: { source_grouping: Grouping };
    }[];
    temporal: { dataset: { manifest: { sources: FrozenSource[] } } };
  };
  const item = fixture.items[0];
  const declared = item.acquisition_provenance_json.source_grouping;
  const root = `${api}/projects/${fixture.round.project_id}`;
  const video = `${api}/videos/${item.video_id}`;
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.4.0", "true"),
  );
  await page.goto(web);
  await page
    .getByRole("button", { name: "Open Synthetic ReefPose lineage" })
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
    .selectOption(item.video_id);
  const prepared = await page.request.get(video);
  expect((await prepared.json()).frame_directory_path).toBeTruthy();
  await page.getByLabel("Existing track").selectOption(item.video_track_id);
  await page.getByLabel("Enable source-coordinate overlay").check();

  const acquisition = page.getByRole("region", {
    name: "Pose Active Learning",
  });
  await acquisition
    .getByLabel("Pose Active Learning round name")
    .fill(`Grouped UI review ${randomUUID()}`);
  await acquisition.getByLabel("Pose Active Learning review budget").fill("1");
  await acquisition
    .getByLabel("Recording ID", { exact: true })
    .fill(declared.recording_id);
  await acquisition
    .getByLabel("Animal ID across recordings")
    .fill(declared.animal_id);
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${root}/pose-active-learning-rounds`,
  );
  await acquisition
    .getByRole("button", { name: "Create pose acquisition round" })
    .click();
  const round = await created;
  expect(round.status(), await round.text()).toBe(201);
  const selected = await round.json();
  expect(selected.selection_manifest_json.source_grouping).toEqual(declared);
  await expect(
    acquisition.getByText(/Sampling unit development-animal/),
  ).toBeVisible();
  await acquisition
    .getByRole("button", {
      name: "Review in Pose Annotation Editor",
      exact: true,
    })
    .click();
  await expect(
    acquisition.getByText(
      /Open in Pose Annotation Editor\. Saving the reviewed pose/,
    ),
  ).toBeVisible();
  const reviewed = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      response.url().includes("/pose-active-learning-candidates/") &&
      response.request().postDataJSON().action === "verify",
  );
  await page.getByRole("button", { name: "Save pose", exact: true }).click();
  const candidate = await reviewed;
  expect(candidate.status(), await candidate.text()).toBe(200);
  const freezing = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response
        .url()
        .endsWith(
          `/pose-active-learning-rounds/${selected.id}/training-dataset`,
        ),
  );
  await acquisition
    .getByRole("button", { name: "Freeze verified training dataset" })
    .click();
  const frozen = await freezing;
  expect(frozen.status(), await frozen.text()).toBe(201);
  const frozenFrame = await frozen.json();
  const frozenItems = await page.request.get(
    `${api}/pose-training-datasets/${frozenFrame.id}/items`,
  );
  expect(frozenItems.ok(), await frozenItems.text()).toBeTruthy();
  const actualItems = await frozenItems.json();
  expect(actualItems).toHaveLength(1);
  expect(actualItems[0].acquisition_provenance_json.source_grouping).toEqual(
    declared,
  );
  expect(
    actualItems[0].acquisition_provenance_json.source_grouping_study
      .organism_key,
  ).toBe(declared.animal_id);
  await acquisition.screenshot({
    path: info.outputPath("grouped-pose-acquisition.png"),
  });

  const temporal = page.getByRole("region", {
    name: "Native temporal ReefPose",
  });
  await temporal
    .getByLabel("Dataset name")
    .fill(`Grouped UI temporal ${randomUUID()}`);
  for (const [
    index,
    source,
  ] of fixture.temporal.dataset.manifest.sources.entries()) {
    await temporal
      .getByRole("button", { name: "Add sequence", exact: true })
      .click();
    const seq = temporal.getByRole("group", {
      name: `Sequence ${index + 1}`,
      exact: true,
    });
    await seq
      .getByLabel("Frame-model track")
      .selectOption(source.frame_track.id);
    await seq
      .getByLabel("Human-reviewed supervision track")
      .selectOption(source.reviewed_track.id);
    await seq
      .getByLabel("Reviewed animal identity")
      .selectOption(source.identity.animal_id);
    await seq
      .getByLabel("I confirmed these two tracks represent the same animal")
      .check();
    await seq
      .getByLabel("Recording ID", { exact: true })
      .fill(source.source_grouping.recording_id);
    await seq
      .getByLabel("Animal ID across recordings")
      .fill(source.source_grouping.animal_id);
    await seq.getByLabel("Sequence partition").selectOption(source.split);
  }
  const temporalFreeze = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url() === `${root}/temporal-reefpose/datasets`,
  );
  await temporal
    .getByRole("button", { name: "Freeze a sequence dataset" })
    .click();
  const temporalResult = await temporalFreeze;
  expect(temporalResult.status(), await temporalResult.text()).toBe(201);
  const temporalDataset = await temporalResult.json();
  expect(temporalDataset.frame_lineage_state).toBe("held_out");
  const frozenTemporal = await page.request.get(
    `${root}/temporal-reefpose/datasets/${temporalDataset.id}`,
  );
  expect(frozenTemporal.ok(), await frozenTemporal.text()).toBeTruthy();
  const detail = await frozenTemporal.json();
  expect(
    detail.manifest.sources.map((row: FrozenSource) => row.source_grouping),
  ).toEqual(
    fixture.temporal.dataset.manifest.sources.map(
      (source) => source.source_grouping,
    ),
  );
  await temporal.screenshot({
    path: info.outputPath("grouped-temporal-study.png"),
  });
});
