import { expect, type Page } from "@playwright/test";
import { randomBytes, randomUUID } from "node:crypto";
import { inflateRawSync } from "node:zlib";
import {
  checked,
  seedPairedStills,
  verifyOriginal,
} from "./pairedStillComparisonFixture";

interface Receipt {
  id: string;
  content_sha256: string;
}

export function generatedZipMembers(archive: Buffer) {
  // The acceptance fixture produces small, single-volume ZIPs. Read the
  // central directory so streamed local entries with data descriptors work.
  const end = archive.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  expect(end, "generated ZIP has an end record").toBeGreaterThanOrEqual(0);
  const entries = archive.readUInt16LE(end + 10);
  let central = archive.readUInt32LE(end + 16);
  const members = new Map<string, () => Buffer>();
  for (let index = 0; index < entries; index++) {
    expect(archive.readUInt32LE(central)).toBe(0x02014b50);
    const method = archive.readUInt16LE(central + 10);
    const packedSize = archive.readUInt32LE(central + 20);
    const size = archive.readUInt32LE(central + 24);
    const nameLength = archive.readUInt16LE(central + 28);
    const extraLength = archive.readUInt16LE(central + 30);
    const commentLength = archive.readUInt16LE(central + 32);
    const local = archive.readUInt32LE(central + 42);
    const name = archive.toString(
      "utf8",
      central + 46,
      central + 46 + nameLength,
    );
    expect(members.has(name), `duplicate generated ZIP member ${name}`).toBe(
      false,
    );
    members.set(name, () => {
      expect(archive.readUInt32LE(local)).toBe(0x04034b50);
      const start =
        local +
        30 +
        archive.readUInt16LE(local + 26) +
        archive.readUInt16LE(local + 28);
      const compressed = archive.subarray(start, start + packedSize);
      expect([0, 8]).toContain(method);
      const bytes =
        method === 0
          ? compressed
          : inflateRawSync(compressed, { maxOutputLength: 64 * 1024 * 1024 });
      expect(bytes.length, `decoded archive member ${name}`).toBe(size);
      return bytes;
    });
    central += 46 + nameLength + extraLength + commentLength;
  }
  return members;
}

async function declareStudy(page: Page, project: string) {
  const ecology = project + "/ecology";
  const treatments = [
    { code: "reference", label: "Synthetic reference tank" },
    { code: "comparison", label: "Synthetic comparison tank" },
  ];
  const keys = treatments.map(
    ({ code }) => `package-colony-${code}-${randomUUID().slice(0, 8)}`,
  );
  for (const [index, treatment] of treatments.entries()) {
    const tank = `package-tank-${index + 1}-${keys[index].slice(-8)}`;
    await checked(
      await page.request.post(ecology + "/organisms", {
        data: {
          organism_key: keys[index],
          experimental_unit_type: "tank",
          experimental_unit_id: tank,
          kind: "colony",
          reason: "Synthetic prospective enrollment for package verification",
          study_assignment: {
            tank_code: tank,
            treatment_code: treatment.code,
            reviewer: "Synthetic assignment reviewer",
            confirm_review: true,
          },
        },
      }),
      201,
    );
  }
  const date = (days: number) =>
    new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
  return checked<Receipt>(
    await page.request.post(ecology + "/study-designs", {
      data: {
        declaration: {
          title: "Synthetic prospective study for research package",
          timing: "prospective",
          reviewed_by: "Synthetic study reviewer",
          review_note:
            "Reviewed the generated independent tank roster and planned visits.",
          confirm_review: true,
          contrast: {
            baseline_date: date(2),
            followup_date: date(4),
            experimental_unit_type: "tank",
            estimand:
              "Equal-tank average change from the baseline visit to the follow-up visit.",
            missingness_policy: "complete_unit",
          },
          metric: "box_width",
          method: "paired_growth_contrast",
          nesting: "parent_colony_within_unit",
          exclusion_policy: "reviewed_source_exclusions",
          exclusion_rule:
            "Exclude originals when the annotated boundary is obscured.",
          organism_keys: keys,
          treatments,
        },
      },
    }),
    201,
  );
}

async function sealAgreement(page: Page, project: string, image: string) {
  const lab = project + "/reviewer-lab";
  const managerKey = randomBytes(32).toString("hex");
  const manager = { Authorization: `Bearer ${managerKey}` };
  await checked(
    await page.request.post(lab + "/initialize", {
      data: { name: "Synthetic package manager" },
      headers: { "X-ReefVision-Role-Key": managerKey },
    }),
    201,
  );
  const members = [];
  for (const [index, role] of [
    "reviewer",
    "reviewer",
    "adjudicator",
  ].entries()) {
    const key = randomBytes(32).toString("hex");
    const { member_id } = await checked<{ member_id: string }>(
      await page.request.post(lab + "/roles", {
        data: { name: `Synthetic package reviewer role ${index + 1}`, role },
        headers: { ...manager, "X-ReefVision-Role-Key": key },
      }),
      201,
    );
    members.push({ member_id, key });
  }
  const [first, second, adjudicator] = members;
  const plan = await checked<{
    id: string;
    plan_sha256: string;
    subjects: { id: string }[];
  }>(
    await page.request.post(lab + "/rounds", {
      data: {
        operation_id: randomUUID(),
        title: "Synthetic independent package checks",
        criterion: "Check source clarity in the generated held-out image.",
        reviewer_member_ids: [first.member_id, second.member_id],
        adjudicator_member_id: adjudicator.member_id,
        sources: [{ type: "image", id: image }],
      },
      headers: manager,
    }),
    201,
  );
  const round = `${lab}/rounds/${plan.id}`;
  for (const member of [first, second]) {
    await checked(
      await page.request.post(
        `${round}/subjects/${plan.subjects[0].id}/decision`,
        {
          data: {
            operation_id: randomUUID(),
            plan_sha256: plan.plan_sha256,
            value: "usable",
            reason:
              "Generated original was clear enough to identify the full rectangle.",
          },
          headers: { Authorization: `Bearer ${member.key}` },
        },
      ),
      201,
    );
  }
  const report = await checked<Receipt>(
    await page.request.post(round + "/seal", { headers: manager }),
    201,
  );
  return { report, roleKeys: [managerKey, ...members.map(({ key }) => key)] };
}

export async function seedResearchPackage(page: Page, api: string) {
  const fixture = await seedPairedStills(page, api);
  const project = `${api}/projects/${fixture.project_id}`;
  const comparisons = project + "/paired-model-comparisons";
  const [left, right] = fixture.registered_model_choices;
  const pin = ({
    runtime_selection_id,
    runtime_selection_sha256,
  }: typeof left) => ({
    id: runtime_selection_id,
    sha256: runtime_selection_sha256,
  });
  const queued = await checked<{ id: string }>(
    await page.request.post(comparisons, {
      data: {
        task: "detector",
        left: pin(left),
        right: pin(right),
        sources: [
          {
            id: fixture.report.reference_id,
            sha256: fixture.report.reference_sha256,
          },
        ],
      },
    }),
    202,
  );
  let comparison!: {
    status: string;
    error_message: string | null;
    result_json: {
      content_sha256: string;
      snapshot: {
        evidence: { groups: { observations: { media_id: string }[] }[] };
      };
    };
  };
  await expect
    .poll(
      async () => {
        comparison = await checked(
          await page.request.get(`${comparisons}/${queued.id}`),
        );
        return comparison.status;
      },
      { timeout: 60_000 },
    )
    .not.toMatch(/queued|running/);
  expect(comparison.status, comparison.error_message ?? undefined).toBe(
    "succeeded",
  );
  const originalId =
    comparison.result_json.snapshot.evidence.groups[0].observations[0].media_id;
  const original = {
    id: originalId,
    ...(await verifyOriginal(page, api, originalId)),
  };
  const batches = project + "/field-capture/batches";
  const field = await checked<{ id: string }>(
    await page.request.post(batches, {
      data: { label: "Synthetic held-out field record" },
    }),
    201,
  );
  const fieldRoot = `${batches}/${field.id}`;
  const image = await page.request.get(`${api}/images/${original.id}/content`);
  expect(image.status()).toBe(200);
  const capture = await checked<{
    id: string;
    sha256: string;
    source_observation_id: string;
  }>(
    await page.request.post(fieldRoot + "/observations", {
      multipart: {
        file: {
          name: original.original_filename,
          mimeType: "image/png",
          buffer: await image.body(),
        },
        metadata: JSON.stringify({
          observer: "Synthetic field observer",
          observation_key: "Package held-out frame field record",
          clock: {
            state: "unknown",
            evidence: "Synthetic source has no device clock metadata",
          },
        }),
      },
    }),
    201,
  );
  expect(capture.sha256).toBe(original.sha256);
  const seal = await checked<{ manifest_sha256: string }>(
    await page.request.post(fieldRoot + "/seal"),
  );
  const reconciliation = await checked<{
    report_sha256: string;
    rows: { asset_id: string; outcome: string }[];
  }>(
    await page.request.post(fieldRoot + "/reconcile", {
      data: { manifest_sha256: seal.manifest_sha256 },
    }),
  );
  expect(reconciliation.rows[0]).toMatchObject({
    asset_id: original.id,
    outcome: "duplicate_media",
  });
  const study = await declareStudy(page, project);
  const { report, roleKeys } = await sealAgreement(page, project, originalId);
  return {
    fixture,
    study,
    report,
    comparison: {
      id: queued.id,
      content_sha256: comparison.result_json.content_sha256,
    },
    original,
    field: {
      ...field,
      capture,
      manifest_sha256: seal.manifest_sha256,
      report_sha256: reconciliation.report_sha256,
    },
    roleKeys,
  };
}
