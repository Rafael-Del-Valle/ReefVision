import { createHash, randomBytes, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";

import type {
  DetectabilityAssessment,
  DetectabilityVisit,
  TaxonProposal,
  TaxonomySource,
} from "../../src/features/ecology/taxonomyApi";
import type {
  WorkflowGraphRecord,
  WorkflowRun,
  WorkflowRunDetail,
} from "../../src/features/workflow-graphs/workflowGraphApi";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

test.use({ trace: "off" });

const label = "Plexaura homomalla";
const protocol = "Synthetic repeat-search protocol v1";
const date = "2026-02-02";
const start = date + "T00:00:00Z";
const end = date + "T05:00:00Z";
const reviewedReason =
  "Synthetic known-presence reference was checked independently";
const sha256 = (value: Buffer) =>
  createHash("sha256").update(value).digest("hex");

async function checked<T>(result: APIResponse | Response, status: number) {
  expect(result.status(), await result.text()).toBe(status);
  return (await result.json()) as T;
}

function post(page: Page, url: string) {
  return page.waitForResponse(
    (response) =>
      response.url() === url && response.request().method() === "POST",
  );
}

test("Review a named taxon and replay an effort-aware independent-unit detectability assessment", async ({
  desktop,
}, info) => {
  test.setTimeout(120_000);
  const { page, web, api, surface } = desktop;
  const isolated = await verifyResearchDesktop(page, api);
  const projectTitle = "Synthetic taxonomy " + randomUUID().slice(0, 8);
  const project = await checked<{ id: string }>(
    await page.request.post(api + "/projects", {
      data: { name: projectTitle, template: "blank" },
    }),
    201,
  );
  const root = api + "/projects/" + project.id;
  const taxonomy = root + "/taxonomy";
  const managerKey = randomBytes(32).toString("hex");
  const reviewerKey = randomBytes(32).toString("hex");
  const manager = { Authorization: "Bearer " + managerKey };
  const reviewer = { Authorization: "Bearer " + reviewerKey };
  const managerRole = await checked<{ id: string }>(
    await page.request.post(root + "/reviewer-lab/initialize", {
      headers: { "X-ReefVision-Role-Key": managerKey },
      data: { name: "Fixture observer" },
    }),
    201,
  );
  const reviewerRole = await checked<{ id: string }>(
    await page.request.post(root + "/reviewer-lab/roles", {
      headers: { ...manager, "X-ReefVision-Role-Key": reviewerKey },
      data: { name: "Fixture independent reviewer", role: "reviewer" },
    }),
    201,
  );
  async function recorded<T>(
    resource: string,
    data: unknown,
    headers: Record<string, string> = {},
  ) {
    return checked<T>(
      await page.request.post(taxonomy + "/" + resource, {
        data: JSON.stringify(data),
        headers: { ...headers, "Content-Type": "application/json" },
      }),
      201,
    );
  }
  const originals: Array<TaxonomySource & { filename: string }> = [];
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        "reefvision.onboarding.dismissed." + version,
        "true",
      ),
    isolated.application_version,
  );
  await page.goto(web);
  async function original(number: number) {
    const png = await page.evaluate((number) => {
      const canvas = document.createElement("canvas");
      canvas.width = 32 + number;
      canvas.height = 40;
      const context = canvas.getContext("2d")!;
      context.fillStyle = `rgb(${(number * 11) % 255},${(number * 17) % 255},${(number * 23) % 255})`;
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#cc6555";
      context.fillRect(3, 5, 4 + (number % 8), 11);
      return canvas.toDataURL("image/png").split(",")[1];
    }, number);
    const file = Buffer.from(png, "base64");
    const filename = `generated-survey-${number}.png`;
    const imported = await checked<{ successful: Array<{ image_id: string }> }>(
      await page.request.post(root + "/imports/images", {
        multipart: {
          files: { name: filename, mimeType: "image/png", buffer: file },
          relative_paths: filename,
        },
      }),
      200,
    );
    const source = {
      kind: "image" as const,
      id: imported.successful[0].image_id,
      sha256: sha256(file),
      filename,
    };
    originals.push(source);
    return source;
  }
  const identityIds: string[] = [];
  for (let group = 1; group <= 5; group++) {
    const identity = await checked<{ id: string }>(
      await page.request.post(root + "/ecology/organisms", {
        data: {
          organism_key: `synthetic-colony-${group}`,
          kind: "colony",
          experimental_unit_type: "tank",
          experimental_unit_id: `tank-${group}`,
          reason: "Declared independent synthetic unit",
        },
      }),
      201,
    );
    identityIds.push(identity.id);
  }
  type Original = Awaited<ReturnType<typeof original>>;
  const pinned = ({ kind, id, sha256 }: Original): TaxonomySource => ({
    kind,
    id,
    sha256,
  });
  const foreground = await original(1);
  const foregroundObservations = [await original(2), await original(3)];
  const foregroundReferences = [await original(4), await original(5)];
  for (let group = 2; group <= 5; group++) {
    const proposal = await recorded<TaxonProposal>(
      "proposals",
      {
        identity_revision_id: identityIds[group - 1],
        scientific_name: label,
        rank: "species",
        source: pinned(await original(group * 5 + 1)),
        reason: "Declared generated taxon for this named organism",
      },
      manager,
    );
    await recorded(
      `proposals/${proposal.id}/reviews`,
      {
        expected_revision: 0,
        decision: "confirmed",
        reason: "Fixture taxonomy corroboration",
      },
      reviewer,
    );
    for (let repeat = 0; repeat < 2; repeat++) {
      const visit = await recorded<DetectabilityVisit>(
        "visits",
        {
          proposal_id: proposal.id,
          protocol,
          started_at: `${date}T0${group - 1}:${repeat === 0 ? "00" : "12"}:00Z`,
          effort_seconds: 30,
          outcome: repeat === 0 ? "detected" : "not_detected",
          source: pinned(await original(group * 5 + 2 + repeat)),
          notes: "Generated completed protocol visit",
        },
        manager,
      );
      await recorded(
        `visits/${visit.id}/presence-reviews`,
        {
          expected_revision: 0,
          decision: "confirmed",
          source: pinned(await original(group * 5 + 4 + repeat)),
          reason: reviewedReason,
        },
        reviewer,
      );
    }
  }

  async function openTaxonomy() {
    await page.goto(web);
    await page
      .getByRole("button", { name: "Open " + projectTitle, exact: true })
      .click();
    await page.getByRole("tab", { name: "Research", exact: true }).click();
    await page
      .getByRole("tab", { name: "Organisms & ecology", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Taxonomy and detectability", exact: true })
      .click();
  }
  const workspace = page.getByRole("region", {
    name: "Taxonomy and detectability",
    exact: true,
  });
  async function connect(key: string, name: string) {
    const change = workspace.getByRole("button", {
      name: "Change local role",
      exact: true,
    });
    if (await change.isVisible()) await change.click();
    await workspace.getByLabel("Reviewer Lab key").fill(key);
    await workspace
      .getByRole("button", { name: "Connect local role", exact: true })
      .click();
    await expect(
      workspace.getByRole("status").filter({ hasText: name }),
    ).toBeVisible();
  }
  await openTaxonomy();
  await connect(managerKey, "Fixture observer");
  const proposalForm = workspace.getByRole("form", { name: "Propose a taxon" });
  await proposalForm
    .getByLabel("Registered organism")
    .selectOption(identityIds[0]);
  await proposalForm.getByLabel("Scientific name").fill(label);
  await proposalForm
    .getByRole("combobox", { name: /^Taxonomy source file/ })
    .selectOption("image:" + foreground.id);
  await proposalForm
    .getByLabel("Proposal reason")
    .fill("Pinned generated evidence for named organism");
  const proposed = post(page, taxonomy + "/proposals");
  await proposalForm
    .getByRole("button", { name: "Submit taxon proposal" })
    .click();
  const proposal = await checked<TaxonProposal>(await proposed, 201);
  expect(proposal).toMatchObject({
    state: "proposed",
    proposal: {
      author: { role_revision_id: managerRole.id },
      source: pinned(foreground),
    },
  });
  const selection = workspace.getByRole("region", {
    name: "Selected taxon proposal",
  });
  await expect(
    selection.getByText("Proposed by Fixture observer · manager"),
  ).toBeVisible();
  await expect(
    selection.getByRole("button", { name: "Record taxonomy decision" }),
  ).toHaveCount(0);
  await connect(reviewerKey, "Fixture independent reviewer");
  const taxReview = selection.getByRole("form", {
    name: "Taxonomy decision",
    exact: true,
  });
  await taxReview
    .getByLabel("Decision reason")
    .fill("Fixture media checked by a second current role");
  const deciding = post(page, `${taxonomy}/proposals/${proposal.id}/reviews`);
  await taxReview
    .getByRole("button", { name: "Record taxonomy decision" })
    .click();
  const confirmed = await checked<{
    review: { reviewer: { role_revision_id: string }; decision: string };
  }>(await deciding, 201);
  expect(confirmed.review).toMatchObject({
    decision: "confirmed",
    reviewer: { role_revision_id: reviewerRole.id },
  });
  await expect(
    selection.getByRole("listitem").filter({ hasText: "Confirmed" }),
  ).toBeVisible();

  await workspace
    .getByRole("button", { name: "Sampling visits", exact: true })
    .click();
  const visitForm = workspace.getByRole("form", {
    name: "Record a sampling visit",
  });
  for (let repeat = 0; repeat < 3; repeat++) {
    await connect(managerKey, "Fixture observer");
    await visitForm
      .getByLabel("Organism and taxon proposal")
      .selectOption(proposal.id);
    await visitForm.getByLabel("Sampling protocol").fill(protocol);
    await visitForm
      .getByLabel("Visit start (UTC or offset)")
      .fill(`${date}T00:${String(repeat * 12).padStart(2, "0")}:00Z`);
    await visitForm
      .getByLabel("Observation outcome")
      .selectOption(["detected", "not_detected", "unobserved"][repeat]);
    if (repeat < 2) {
      await visitForm.getByLabel("Observed effort (seconds)").fill("30");
      await visitForm
        .getByRole("combobox", { name: /^Observation source file/ })
        .selectOption("image:" + foregroundObservations[repeat].id);
    }
    await visitForm
      .getByLabel("Visit notes")
      .fill(
        repeat < 2
          ? "Reviewed full generated observation"
          : "No image or effort collected",
      );
    const recording = post(page, taxonomy + "/visits");
    await visitForm
      .getByRole("button", { name: "Record sampling visit" })
      .click();
    const visit = await checked<DetectabilityVisit>(await recording, 201);
    if (repeat < 2) {
      await connect(reviewerKey, "Fixture independent reviewer");
      const presence = workspace.getByRole("form", {
        name: "Known presence decision",
        exact: true,
      });
      await presence
        .getByRole("combobox", { name: /^Separate presence source file/ })
        .selectOption("image:" + foregroundReferences[repeat].id);
      await presence.getByLabel("Decision reason").fill(reviewedReason);
      const review = post(
        page,
        `${taxonomy}/visits/${visit.id}/presence-reviews`,
      );
      await presence
        .getByRole("button", { name: "Record known presence decision" })
        .click();
      await checked(await review, 201);
      await expect(
        workspace.getByText(reviewedReason, { exact: true }),
      ).toBeVisible();
    }
  }

  await workspace
    .getByRole("button", { name: "Detectability assessments", exact: true })
    .click();
  const assessment = workspace.getByRole("form", {
    name: "Estimate detectability",
  });
  await assessment.getByLabel("Target scientific name").fill(label);
  await assessment.getByLabel("Sampling protocol").fill(protocol);
  await assessment.getByLabel("Independent unit type").fill("tank");
  await assessment.getByLabel("Minimum effort (seconds)").fill("20");
  await assessment.getByLabel("Window start (UTC or offset)").fill(start);
  await assessment.getByLabel("Window end (UTC or offset)").fill(end);
  const saving = post(page, taxonomy + "/assessments");
  await assessment
    .getByRole("button", { name: "Save detectability assessment" })
    .click();
  const saved = await checked<DetectabilityAssessment>(await saving, 201);
  expect(saved.result).toMatchObject({
    status: "estimated",
    estimate: 0.5,
    independent_groups: 5,
    total_recorded_visits: 11,
    eligible_visits: 10,
    observed_detections: 5,
    observed_nondetections: 5,
    included_effort_seconds: 300,
    confidence_interval: { level: 0.95 },
  });
  expect(
    saved.result.visits
      .filter((row) => row.exclusion)
      .map((row) => row.exclusion),
  ).toEqual(["unobserved"]);
  const result = workspace.getByRole("region", {
    name: "Saved detectability assessment",
  });
  await expect(result.getByRole("status")).toContainText(
    "Estimated detection: 50.0%",
  );
  await result
    .getByText("Survey evidence and exclusions", { exact: true })
    .click();
  await expect(result.getByText(/Visit unobserved/)).toBeVisible();
  const downloading = page.waitForEvent("download");
  await result.getByRole("link", { name: "Export detectability JSON" }).click();
  const output = info.outputPath("detectability-assessment.json");
  await (await downloading).saveAs(output);
  const exportBytes = await readFile(output);
  expect(JSON.parse(exportBytes.toString())).toEqual(saved);
  expect(exportBytes.toString()).not.toContain(managerKey);
  expect(exportBytes.toString()).not.toContain(reviewerKey);
  const graphRequest = post(page, root + "/workflow-graphs");
  await result
    .getByRole("button", { name: "Save detectability workflow" })
    .click();
  const graph = await checked<WorkflowGraphRecord>(await graphRequest, 201);

  const receipts = [];
  for (let runNumber = 0; runNumber < 2; runNumber++) {
    await page
      .getByRole("listitem")
      .filter({ hasText: graph.name })
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    await expect
      .poll(
        async () => {
          const response = await checked<WorkflowRun[]>(
            await page.request.get(root + "/workflow-runs"),
            200,
          );
          return response.filter(
            (row) =>
              row.workflow_graph_record_id === graph.id &&
              row.status === "succeeded",
          ).length;
        },
        { timeout: 35_000 },
      )
      .toBe(runNumber + 1);
  }
  const runs = (
    await checked<WorkflowRun[]>(
      await page.request.get(root + "/workflow-runs"),
      200,
    )
  ).filter((row) => row.workflow_graph_record_id === graph.id);
  expect(runs).toHaveLength(2);
  for (const run of runs) {
    const detail = await checked<WorkflowRunDetail>(
      await page.request.get(api + "/workflow-runs/" + run.id),
      200,
    );
    const artifact = detail.artifacts.find(
      (row) => row.data_type === "detectability_assessment",
    );
    expect(artifact?.payload_json).toEqual(saved);
    receipts.push({ run_id: run.id, payload_sha256: artifact?.payload_sha256 });
  }
  expect(receipts[0].payload_sha256).toBe(receipts[1].payload_sha256);
  await openTaxonomy();
  await workspace
    .getByRole("button", { name: "Detectability assessments", exact: true })
    .click();
  await workspace
    .getByRole("button", { name: /Plexaura homomalla.*estimated/ })
    .click();
  await expect(result.getByRole("status")).toContainText(
    "Estimated detection: 50.0%",
  );
  await expect(
    result.getByText(saved.result_sha256, { exact: true }),
  ).toBeVisible();
  for (const source of originals) {
    const raw = await page.request.get(
      api + "/images/" + source.id + "/content",
    );
    expect(raw.status()).toBe(200);
    expect(sha256(await raw.body())).toBe(source.sha256);
  }
  await writeFile(
    info.outputPath("taxonomy-detectability-proof.json"),
    JSON.stringify(
      {
        surface,
        application_version: isolated.application_version,
        schema_revision: isolated.schema_revision,
        generated_fixture: true,
        project_id: project.id,
        two_fixture_role_revisions: [managerRole.id, reviewerRole.id],
        originals,
        proposal_id: proposal.id,
        proposal_sha256: proposal.proposal_sha256,
        assessment_id: saved.id,
        result_sha256: saved.result_sha256,
        exported_file_sha256: sha256(exportBytes),
        graph_id: graph.id,
        graph_sha256: graph.graph_sha256,
        runs: receipts,
        grouped_result: saved.result.groups,
      },
      null,
      2,
    ),
  );
});
