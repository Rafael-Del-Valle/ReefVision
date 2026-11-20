import { expect, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { checked, verifyOriginal } from "./pairedStillComparisonFixture";
import {
  generatedZipMembers,
  seedResearchPackage,
} from "./reproducibilityPackageFixture";
import { test } from "./spatialDesktop";

const checksum = /^[a-f0-9]{64}$/;
const sha256 = (data: Buffer) =>
  createHash("sha256").update(data).digest("hex");

interface Proof {
  schema_version: string;
  evidence: Record<
    "study" | "review" | "comparison",
    { id: string; content_sha256: string }
  >;
  section_sha256: Record<string, string>;
  proof_sha256: string;
}

interface OmittedSource {
  kind: string;
  record_id: string;
  sha256: string;
  requires_relink_for: string[];
}

interface Manifest {
  format_name: string;
  format_version: string;
  proof: Proof;
  exchange_manifest_sha256: string;
  entries: { path: string; size_bytes: number; sha256: string }[];
  omitted_sources: OmittedSource[];
  included_media_count: number;
}

function posting(page: Page, path: string) {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && response.url() === path,
  );
}

test.use({ trace: "off", screenshot: "off", video: "off" });

test("exports and restores a reproducibility package with replayable study, review and model proof", async ({
  desktop: { page, api, web, surface },
}, info) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(15_000);
  const { fixture, study, report, comparison, original, field, roleKeys } =
    await seedResearchPackage(page, api);
  const { version } = JSON.parse(await readFile("package.json", "utf8")) as {
    version: string;
  };
  await page.addInitScript((value) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${value}`, "true");
  }, version);
  async function openProject() {
    await page.goto(web);
    await page
      .getByRole("button", {
        name: `Open ${fixture.project_name}`,
        exact: true,
      })
      .click();
  }
  const title = "Export reproducibility package";
  async function openPackageWorkspace() {
    await openProject();
    await page.getByRole("tab", { name: "Research", exact: true }).click();
    await page.getByRole("tab", { name: title, exact: true }).click();
  }
  await openPackageWorkspace();
  const workspace = page.getByRole("region", {
    name: "Research reproducibility package",
    exact: true,
  });
  await workspace
    .getByRole("combobox", { name: /^Study design revision/ })
    .selectOption(study.id);
  await workspace
    .getByRole("combobox", { name: /^Sealed agreement report/ })
    .selectOption(report.id);
  await workspace
    .getByRole("combobox", { name: /^Paired model comparison/ })
    .selectOption(comparison.id);
  await expect(
    page.getByLabel("Include source media", { exact: true }),
  ).toBeChecked();
  await expect(
    page.getByLabel("Include local model weights", { exact: true }),
  ).not.toBeChecked();
  const project = `${api}/projects/${fixture.project_id}`;
  const global = api + "/reproducibility-packages";
  const exporting = posting(page, project + "/reproducibility-packages");
  await page
    .getByRole("button", { name: "Export package", exact: true })
    .click();
  const exportResponse = await exporting;
  expect(exportResponse.request().postDataJSON()).toEqual({
    study_design_id: study.id,
    reviewer_report_id: report.id,
    comparison_id: comparison.id,
    include_media: true,
    include_model_weights: false,
  });
  const { package: queued } = await checked<{ package: { id: string } }>(
    exportResponse,
    202,
  );
  const { id } = queued;
  let exported!: {
    status: string;
    manifest: Manifest;
    manifest_sha256: string;
    proof_sha256: string;
    error_message: string | null;
  };
  await expect
    .poll(
      async () => {
        exported = await checked(await page.request.get(`${global}/${id}`));
        return exported.status;
      },
      { timeout: 90_000 },
    )
    .not.toMatch(/queued|running/);
  expect(exported.status, exported.error_message ?? undefined).toBe("complete");
  expect(exported.manifest_sha256).toMatch(checksum);
  expect(exported.proof_sha256).toMatch(checksum);
  const manifest = exported.manifest;
  expect(manifest.format_name).toBe("reefvision-reproducibility");
  expect(manifest.format_version).toBe("1.5");
  expect(manifest.exchange_manifest_sha256).toMatch(checksum);
  expect(manifest.included_media_count).toBeGreaterThanOrEqual(3);
  expect(manifest.entries.map(({ path }) => path)).toEqual(
    expect.arrayContaining([
      "project.reefvision.zip",
      "evidence/study.json",
      "evidence/review.json",
      "evidence/comparison.json",
      "evidence/models.json",
      "evidence/methods.json",
      "evidence/environment.json",
      "evidence/exclusions.json",
    ]),
  );
  for (const entry of manifest.entries) {
    expect(entry.sha256).toMatch(checksum);
    expect(entry.size_bytes).toBeGreaterThan(0);
  }
  const checkpoints = fixture.registered_model_choices.map(
    (model) => model.checkpoint_sha256,
  );
  for (const digest of checkpoints) {
    const omission = manifest.omitted_sources.find(
      (source) => source.sha256 === digest,
    );
    expect(omission?.requires_relink_for.length).toBeGreaterThan(0);
  }
  expect(manifest.proof).toMatchObject({
    schema_version: "reefvision-research-proof-1",
    evidence: {
      study: { id: study.id, content_sha256: study.content_sha256 },
      review: { id: report.id, content_sha256: report.content_sha256 },
      comparison,
    },
    proof_sha256: exported.proof_sha256,
  });
  const manifestText = JSON.stringify(manifest);
  if (roleKeys.some((key) => manifestText.includes(key)))
    throw new Error("Local role key in package manifest");

  const downloading = page.waitForEvent("download");
  await page
    .getByRole("link", {
      name: "Download reproducibility package",
      exact: true,
    })
    .click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe(`${id}.reproducibility.zip`);
  const archive = info.outputPath(download.suggestedFilename());
  await download.saveAs(archive);
  const downloaded = await readFile(archive);
  const archiveHash = sha256(downloaded);
  const apiCopy = await page.request.get(`${global}/${id}/download`);
  expect(apiCopy.status()).toBe(200);
  expect(sha256(await apiCopy.body())).toBe(archiveHash);
  const members = generatedZipMembers(downloaded);
  const exchangeMember = members.get("project.reefvision.zip");
  expect(exchangeMember).toBeDefined();
  const exchange = generatedZipMembers(exchangeMember!());
  const payloads = [...members, ...exchange];
  const storedWeights = payloads
    .map(([path]) => path)
    .filter((path) => /\/weights\/|\.(pt|pth|onnx|safetensors)$/i.test(path));
  expect(
    storedWeights,
    "raw training weight files in the downloaded research package",
  ).toEqual([]);
  let originalMemberCount = 0;
  for (const [path, contents] of payloads) {
    const bytes = contents();
    const digest = sha256(bytes);
    if (path.startsWith("media/") && digest === original.sha256)
      originalMemberCount++;
    expect(
      checkpoints.includes(digest),
      `omitted checkpoint bytes in ${path}`,
    ).toBe(false);
    if (roleKeys.some((key) => bytes.includes(key)))
      throw new Error(`Local role key in package member ${path}`);
  }
  expect(
    originalMemberCount,
    "canonical image and Field alias share one archive member",
  ).toBe(1);

  async function saveProof(owner: string) {
    const saving = posting(page, owner + "/workflow-graphs");
    await page
      .getByRole("button", { name: "Open in Workflow Builder", exact: true })
      .click();
    return checked<{ id: string; name: string; graph_sha256: string }>(
      await saving,
      201,
    );
  }

  async function replayProof(owner: string, graph: { name: string }) {
    const saved = page.getByRole("listitem").filter({ hasText: graph.name });
    await saved.getByRole("button", { name: "Load", exact: true }).click();
    const running = posting(page, owner + "/workflow-runs");
    await saved
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const run = await checked<{ id: string }>(await running, 202);
    let detail!: {
      run: { status: string; error_message: string | null };
      artifacts: {
        data_type: string;
        payload_json: Proof;
        payload_sha256: string;
      }[];
    };
    await expect
      .poll(
        async () => {
          detail = await checked(
            await page.request.get(`${api}/workflow-runs/${run.id}`),
          );
          return detail.run.status;
        },
        { timeout: 90_000 },
      )
      .not.toMatch(/queued|running/);
    expect(detail.run.status, detail.run.error_message ?? undefined).toBe(
      "succeeded",
    );
    const [proof] = detail.artifacts.filter(
      (item) => item.data_type === "research_reproducibility_proof",
    );
    expect(proof.payload_json).toEqual(manifest.proof);
    expect(proof.payload_sha256).toMatch(checksum);
    return { id: run.id, sha256: proof.payload_sha256 };
  }
  const graph = await saveProof(project);
  const firstReplay = await replayProof(project, graph);
  await openProject();
  await page
    .getByRole("tab", { name: "Video & automation", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Workflow builder", exact: true })
    .click();
  const runs = [firstReplay, await replayProof(project, graph)];
  expect(runs[0].id).not.toBe(runs[1].id);
  expect(runs[0].sha256).toBe(runs[1].sha256);

  await openPackageWorkspace();
  await page
    .getByLabel("Choose reproducibility package", { exact: true })
    .setInputFiles(archive);
  const inspecting = posting(page, global + "/inspect");
  await page
    .getByRole("button", { name: "Verify package", exact: true })
    .click();
  const checkedPackage = await checked<{
    compatible: boolean;
    manifest_sha256: string;
    manifest: Manifest;
    errors: string[];
  }>(await inspecting);
  expect(checkedPackage.compatible, checkedPackage.errors.join("\n")).toBe(
    true,
  );
  expect(checkedPackage.manifest_sha256).toBe(exported.manifest_sha256);
  expect(checkedPackage.manifest.proof).toEqual(manifest.proof);
  const recoveredName = `Restored research fixture ${id.slice(0, 8)}`;
  await page
    .getByLabel("New project name", { exact: true })
    .fill(recoveredName);
  const importing = posting(page, global + "/import");
  await page
    .getByRole("button", { name: "Import as new project", exact: true })
    .click();
  const recovered = await checked<{
    project_id: string;
    project_name: string;
    reproducibility_package_id: string;
    proof_sha256: string;
    omitted_sources: OmittedSource[];
    package: { options_json: { id_map: Record<string, string> } };
  }>(await importing, 201);
  expect(recovered.project_id).not.toBe(fixture.project_id);
  expect(recovered.project_name).toBe(recoveredName);
  expect(recovered.proof_sha256).toBe(exported.proof_sha256);
  expect(recovered.omitted_sources).toEqual(manifest.omitted_sources);
  const importedReceipt = await checked<{
    direction: string;
    proof_sha256: string;
  }>(
    await page.request.get(`${global}/${recovered.reproducibility_package_id}`),
  );
  expect(importedReceipt).toMatchObject({
    direction: "import",
    proof_sha256: exported.proof_sha256,
  });
  const remappedOriginal = recovered.package.options_json.id_map[original.id];
  expect(remappedOriginal).toBeTruthy();
  expect(remappedOriginal).not.toBe(original.id);
  expect((await verifyOriginal(page, api, remappedOriginal)).sha256).toBe(
    original.sha256,
  );
  expect((await verifyOriginal(page, api, original.id)).sha256).toBe(
    original.sha256,
  );
  const restored = api + "/projects/" + recovered.project_id;
  const fieldBatch = recovered.package.options_json.id_map[field.id];
  const fieldObservation =
    recovered.package.options_json.id_map[field.capture.id];
  expect(fieldBatch).toBeTruthy();
  expect(fieldObservation).toBeTruthy();
  const restoredField = `${restored}/field-capture/batches/${fieldBatch}`;
  const retainedField = await checked<{
    origin_batch_id: string;
    manifest_sha256: string;
    observations: {
      id: string;
      source_observation_id: string;
      sha256: string;
      captured_at_utc: string | null;
    }[];
  }>(await page.request.get(restoredField));
  expect(retainedField).toMatchObject({
    origin_batch_id: field.id,
    manifest_sha256: field.manifest_sha256,
    observations: [
      {
        id: fieldObservation,
        source_observation_id: field.capture.source_observation_id,
        sha256: original.sha256,
        captured_at_utc: null,
      },
    ],
  });
  const fieldSource = await page.request.get(
    `${restoredField}/observations/${fieldObservation}/content`,
  );
  expect(fieldSource.status()).toBe(200);
  expect(sha256(await fieldSource.body())).toBe(original.sha256);
  const reconciliation = await checked<{
    report_sha256: string;
    rows: { asset_id: string }[];
  }>(await page.request.get(restoredField + "/reconciliation"));
  expect(reconciliation.rows[0].asset_id).toBe(remappedOriginal);
  expect(reconciliation.report_sha256).not.toBe(field.report_sha256);
  for (const originalModel of fixture.registered_model_choices) {
    const importedModel =
      recovered.package.options_json.id_map[originalModel.model_id];
    expect(importedModel).toBeTruthy();
    const withheld = await page.request.post(
      restored + "/model-runtime-selections/preview",
      {
        data: { model_id: importedModel, runtime_id: "pytorch", device: "cpu" },
      },
    );
    expect(withheld.status()).toBe(409);
    expect(await withheld.text()).toMatch(/checkpoint.*missing or unreadable/i);
  }
  const originalSession = await page.request.get(
    project + "/reviewer-lab/session",
    {
      headers: { Authorization: `Bearer ${roleKeys[0]}` },
    },
  );
  expect(originalSession.status()).toBe(200);
  const restoredSession = await page.request.get(
    restored + "/reviewer-lab/session",
    {
      headers: { Authorization: `Bearer ${roleKeys[0]}` },
    },
  );
  expect(restoredSession.status()).toBe(401);
  await page.goto(web);
  await page
    .getByRole("button", {
      name: `Open ${recovered.project_name}`,
      exact: true,
    })
    .click();
  await page.getByRole("tab", { name: "Research", exact: true }).click();
  await page.getByRole("tab", { name: title, exact: true }).click();
  const recoveredGraph = await saveProof(restored);
  const recoveredRun = await replayProof(restored, recoveredGraph);
  expect(recoveredRun.sha256).toBe(firstReplay.sha256);

  await writeFile(
    info.outputPath("reproducibility-package-evidence.json"),
    JSON.stringify(
      {
        surface,
        fixture_source: fixture.fixture_source,
        project_id: fixture.project_id,
        package_id: id,
        archive_sha256: archiveHash,
        manifest_sha256: exported.manifest_sha256,
        proof_sha256: exported.proof_sha256,
        evidence: manifest.proof.evidence,
        omitted_checkpoint_sha256: checkpoints,
        original_sha256: original.sha256,
        original_archive_member_count: originalMemberCount,
        restored_field_original_sha256: sha256(await fieldSource.body()),
        restored_field_manifest_sha256: retainedField.manifest_sha256,
        restored_original_id: remappedOriginal,
        restored_project_id: recovered.project_id,
        restored_package_id: recovered.reproducibility_package_id,
        reviewer_credential_restored: false,
        restored_proof_replay: recoveredRun,
        graph_id: graph.id,
        graph_sha256: graph.graph_sha256,
        runs,
      },
      null,
      2,
    ),
  );
});
