import {
  expect,
  type APIResponse,
  type Page,
  type Response,
} from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { detectorStill } from "./ordinaryDetectorFixture";

const sha256 = (data: Buffer) =>
  createHash("sha256").update(data).digest("hex");
export const heldOutGroups = ["fresh-heldout-group-a", "fresh-heldout-group-b"];

interface Selection {
  runtime_selection_id: string;
  runtime_selection_sha256: string;
  model_id: string;
  checkpoint_sha256: string;
}

interface SourceFixture {
  project_id: string;
  training_runs: string[];
  registered_model_choices: Selection[];
  report: { reference_id: string; reference_sha256: string };
}

export interface StillComparisonFixture extends SourceFixture {
  project_name: string;
  fixture_source: "copied_generated_training" | "local_cpu_training";
}

export async function checked<T>(
  response: APIResponse | Response,
  status = 200,
): Promise<T> {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

export async function seedPairedStills(
  page: Page,
  api: string,
): Promise<StillComparisonFixture> {
  const copiedReceipt = process.env.REEFVISION_COMPARISON_FIXTURE_RECEIPT;
  if (copiedReceipt) {
    const copy = JSON.parse(
      await readFile(copiedReceipt, "utf8"),
    ) as SourceFixture;
    const project = await checked<{ name: string }>(
      await page.request.get(`${api}/projects/${copy.project_id}`),
    );
    return {
      ...copy,
      project_name: project.name,
      fixture_source: "copied_generated_training",
    };
  }

  const project = await checked<{ id: string; name: string }>(
    await page.request.post(api + "/projects", {
      data: { name: "Synthetic comparison " + randomUUID(), template: "blank" },
    }),
    201,
  );
  const root = `${api}/projects/${project.id}`;
  const label = await checked<{ id: string }>(
    await page.request.post(root + "/classes", {
      data: {
        name: "Synthetic rectangle",
        class_index: 0,
        display_color: "#52dd85",
      },
    }),
    201,
  );

  async function acquire(index: number, group: string) {
    const { file, box } = detectorStill(index);
    const loaded = await checked<{ successful: { image_id: string }[] }>(
      await page.request.post(root + "/imports/images", {
        multipart: { files: file },
      }),
    );
    const [{ image_id: id }] = loaded.successful;
    await checked(
      await page.request.put(`${api}/images/${id}/annotations`, {
        data: {
          base_revision: 0,
          annotation_status: "reviewed",
          annotations: [{ id: randomUUID(), label_class_id: label.id, ...box }],
        },
      }),
    );
    await checked(
      await page.request.patch(`${api}/images/${id}`, {
        data: { group_key: group, annotation_status: "reviewed" },
      }),
    );
    return id;
  }

  type Assignment = {
    image_id: string;
    split: "train" | "validation" | "test";
  };
  async function freeze(name: string, manual_assignments: Assignment[]) {
    return checked<{ id: string; manifest_sha256: string }>(
      await page.request.post(root + "/dataset-versions", {
        data: {
          name,
          split_method: "manual",
          manual_assignments,
          eligible_annotation_statuses: ["reviewed"],
        },
      }),
      201,
    );
  }

  const assignments: Assignment[] = [];
  for (let index = 0; index < 6; index++) {
    assignments.push({
      image_id: await acquire(
        index,
        `known-upstream-group-${Math.floor(index / 2)}`,
      ),
      split: index === 2 || index === 3 ? "validation" : "train",
    });
  }
  const training = await freeze("Offline training and validation", assignments);
  const selections: Selection[] = [];
  const runs: string[] = [];
  for (const seed of [1, 17]) {
    const name = `Synthetic CPU checkpoint seed ${seed}`;
    const draft = await checked<{ id: string }>(
      await page.request.post(root + "/training-drafts", {
        data: {
          name,
          run_name: name,
          dataset_version_id: training.id,
          task: "detect",
          catalog_model_id: "ultralytics/yolo11/detect/n",
          initial_checkpoint_source: "scratch",
          device: "cpu",
          precision: "fp32",
          random_seed: seed,
          training_config: { epochs: 1, batch: 2, imgsz: 96, workers: 0 },
        },
      }),
    );
    const run = await checked<{ id: string }>(
      await page.request.post(root + "/training-runs", {
        data: { draft_id: draft.id },
      }),
    );
    const details = () => page.request.get(`${api}/training-runs/${run.id}`);
    let completed!: {
      status: string;
      error_message: string | null;
      device: string;
      initial_checkpoint_source: string;
    };
    await expect
      .poll(
        async () => {
          completed = await checked(await details());
          return completed.status;
        },
        { timeout: 90_000 },
      )
      .toMatch(/^(completed|failed|cancelled)$/);
    expect(completed.status, completed.error_message ?? undefined).toBe(
      "completed",
    );
    expect(completed).toMatchObject({
      device: "cpu",
      initial_checkpoint_source: "scratch",
    });
    runs.push(run.id);

    const model = await checked<{ id: string; sha256: string }>(
      await page.request.post(root + "/models/register-from-run", {
        data: { training_run_id: run.id, display_name: name },
      }),
    );
    const runtime = root + "/model-runtime-selections";
    const configuration = {
      model_id: model.id,
      runtime_id: "pytorch",
      device: "cpu",
      prompt: "confidence 0, iou 0.45",
    };
    const preview = await checked<{ content_sha256: string }>(
      await page.request.post(runtime + "/preview", { data: configuration }),
    );
    const selection = await checked<{ id: string; content_sha256: string }>(
      await page.request.post(runtime, {
        data: { draft: configuration, reviewed_sha256: preview.content_sha256 },
      }),
      201,
    );
    selections.push({
      model_id: model.id,
      checkpoint_sha256: model.sha256,
      runtime_selection_id: selection.id,
      runtime_selection_sha256: selection.content_sha256,
    });
  }
  expect(selections[0].checkpoint_sha256).not.toBe(
    selections[1].checkpoint_sha256,
  );
  for (let index = 6; index < 9; index++) {
    assignments.push({
      image_id: await acquire(index, heldOutGroups[index === 8 ? 1 : 0]),
      split: "test",
    });
  }
  const reference = await freeze("Untouched held-out groups", assignments);
  return {
    project_name: project.name,
    project_id: project.id,
    fixture_source: "local_cpu_training",
    training_runs: runs,
    registered_model_choices: selections,
    report: {
      reference_id: reference.id,
      reference_sha256: reference.manifest_sha256,
    },
  };
}

export async function verifyOriginal(page: Page, api: string, id: string) {
  const record = await checked<{ original_filename: string; sha256: string }>(
    await page.request.get(`${api}/images/${id}`),
  );
  const source = await page.request.get(`${api}/images/${id}/content`);
  expect(source.status()).toBe(200);
  expect(sha256(await source.body())).toBe(record.sha256);
  return { original_filename: record.original_filename, sha256: record.sha256 };
}
