import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, type Page } from "@playwright/test";

export async function loadResearchScratchDetector(
  page: Page,
  api: string,
  receiptPath: string,
) {
  const prior = JSON.parse(await readFile(receiptPath, "utf8")) as {
    surface: "tauri-webview2" | "source-browser";
    project_id: string;
    training_run_id: string;
    device: string;
    initializer: string;
    checkpoint_sha256: string;
    model_id: string;
  };
  expect(prior).toMatchObject({ device: "cpu", initializer: "scratch" });
  expect(prior.checkpoint_sha256).toMatch(/^[0-9a-f]{64}$/);
  const model = await page.request.get(`${api}/models/${prior.model_id}`);
  expect(model.status(), await model.text()).toBe(200);
  expect(await model.json()).toMatchObject({
    id: prior.model_id,
    project_id: prior.project_id,
    metadata_json: { source_training_run_id: prior.training_run_id },
    sha256: prior.checkpoint_sha256,
    provider_name: "ultralytics",
    purpose: "detector",
  });
  const runPath = `${api}/training-runs/${prior.training_run_id}`;
  const response = await page.request.get(runPath);
  expect(response.status(), await response.text()).toBe(200);
  const run = (await response.json()) as {
    id: string;
    project_id: string;
    status: string;
    device: string;
    initial_checkpoint_source: string;
    result_checkpoint_path: string;
    artifact_manifest: {
      pretrained: boolean;
      artifacts: { relative_path: string }[];
    };
  };
  expect(run).toMatchObject({
    id: prior.training_run_id,
    project_id: prior.project_id,
    status: "completed",
    device: "cpu",
    initial_checkpoint_source: "scratch",
    artifact_manifest: { pretrained: false },
  });
  const index = run.artifact_manifest.artifacts.findIndex(
    (row) => row.relative_path === run.result_checkpoint_path,
  );
  expect(index).toBeGreaterThanOrEqual(0);
  const checkpoint = await page.request.get(`${runPath}/artifacts/${index}`);
  expect(checkpoint.status()).toBe(200);
  const bytes = await checkpoint.body();
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(
    prior.checkpoint_sha256,
  );
  return {
    bytes,
    sha256: prior.checkpoint_sha256,
    training_run_id: prior.training_run_id,
    surface: prior.surface,
  };
}
