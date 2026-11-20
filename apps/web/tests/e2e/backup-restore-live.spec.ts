import { expect, type APIResponse, type Response } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { lstat, readFile, realpath, stat, writeFile } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type {
  BackupCreateResponse,
  BackupRestoreResponse,
  BackupVerificationResponse,
  JobRecord,
  SystemVersionResponse,
} from "../../src/api/client";
import { test } from "./spatialDesktop";

type BackupManifest = {
  backup_id: string;
  database_filename: string;
  database_schema_revision: string;
  file_inventory: { path: string; sha256: string; size_bytes: number }[];
};

async function json<T>(response: APIResponse | Response, status: number) {
  expect(response.status(), await response.text()).toBe(status);
  return (await response.json()) as T;
}

function managedPath(root: string, relativePath: string) {
  const parts = relativePath.split("/");
  expect(parts.every((part) => part && !/^(?:\.|\.\.)$|[:\\]/.test(part))).toBe(
    true,
  );
  return join(root, ...parts);
}

async function sha256(path: string) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

const fixturePng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAIAAABt+uBvAAAA8ElEQVR4nO3bsQkCURBF0VkRtgDB3F5swSq3BRszswL/BQNNzkknu7x0tsv1Nnx2WtwQqFlQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoHCerxzPfX7icX/NX1lQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoLD5WV2zoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQEGjW3skmBFW/O0+wAAAAAElFTkSuQmCC",
  "base64",
);

const profileJobTimeoutMs = 120_000;

test("creates, verifies, and restores a backup from System status", async ({
  desktop,
}, info) => {
  // Backup and restore each process the entire disposable acceptance profile.
  test.setTimeout(300_000);
  const { page, api, web, surface } = desktop;
  expect(new URL(api).hostname).toBe("127.0.0.1");
  const version = await json<SystemVersionResponse>(
    await page.request.get(api + "/system/version"),
    200,
  );
  expect(isAbsolute(version.data_dir)).toBe(true);
  const profile = await realpath(version.data_dir);
  // A full managed backup copies the profile. Require the disposable harness marker.
  const marker = join(profile, ".reefvision-clean-install-acceptance");
  expect((await lstat(marker)).isFile()).toBe(true);
  expect((await readFile(marker, "utf8")).trim()).not.toBe("");
  expect(version.database_path).not.toBeNull();
  expect(relative(profile, await realpath(version.database_path!))).toBe(
    "reefvision.db",
  );

  const suffix = randomUUID().slice(0, 12);
  const title = "Synthetic backup fixture " + suffix;
  const destination = "backup-copy-" + suffix;
  const target = join(profile, "recoveries", destination);
  await expect(stat(target)).rejects.toHaveProperty("code", "ENOENT");
  const project = await json<{ id: string; storage_root: string }>(
    await page.request.post(api + "/projects", {
      data: { name: title, template: "blank" },
    }),
    201,
  );
  const projectUrl = api + "/projects/" + project.id;
  const label = await json<{ id: string }>(
    await page.request.post(projectUrl + "/classes", {
      data: {
        name: "Fixture colony",
        class_index: 0,
        display_color: "#28A95C",
      },
    }),
    201,
  );
  const imageName = "backup-original.png";
  const imported = await json<{
    successful: { image_id: string; thumbnail_job_id: string }[];
  }>(
    await page.request.post(projectUrl + "/imports/images", {
      multipart: {
        files: { name: imageName, mimeType: "image/png", buffer: fixturePng },
      },
    }),
    200,
  );
  expect(imported.successful, JSON.stringify(imported)).toHaveLength(1);
  const { image_id: imageId, thumbnail_job_id: thumbnailJob } =
    imported.successful[0];
  const imageUrl = api + "/images/" + imageId;
  const annotation = {
    id: randomUUID(),
    label_class_id: label.id,
    x_min: 18,
    x_max: 53,
    y_min: 13,
    y_max: 43,
  };
  const saved = await json<{
    image: {
      sha256: string;
      annotation_status: string;
      annotation_revision: number;
    };
  }>(
    await page.request.put(imageUrl + "/annotations", {
      data: {
        base_revision: 0,
        annotation_status: "reviewed",
        annotations: [annotation],
      },
    }),
    200,
  );
  const waitForJob = async (id: string, label: string, timeout = 30_000) => {
    let job!: JobRecord;
    const describe = () => {
      if (!job) return `${label} job ${id} has no recorded status`;
      const stage = job.result_json?.stage;
      const status =
        typeof stage === "string" ? `${job.status} (${stage})` : job.status;
      return `${label} job ${id}: ${status}, progress ${job.progress_current}/${job.progress_total}${
        job.error_message ? `, error: ${job.error_message}` : ""
      }`;
    };
    try {
      await expect
        .poll(
          async () => {
            job = await json<JobRecord>(
              await page.request.get(api + "/jobs/" + id),
              200,
            );
            return (
              job.error_message !== null ||
              ["succeeded", "failed", "cancelled"].includes(job.status)
            );
          },
          { timeout },
        )
        .toBe(true);
    } catch (cause) {
      throw new Error(
        `Waiting for ${label.toLowerCase()} job failed: ${describe()}`,
        {
          cause,
        },
      );
    }
    expect(job.status, describe()).toBe("succeeded");
    expect(job.error_message, describe()).toBeNull();
    return job;
  };
  await waitForJob(thumbnailJob, "Thumbnail");
  const original =
    project.storage_root + "/images/originals/" + imageId + ".png";
  const liveOriginal = managedPath(profile, original);
  const liveOriginalBefore = await stat(liveOriginal, { bigint: true });
  const liveBefore = await json(
    await page.request.get(imageUrl + "/annotations"),
    200,
  );
  const originalSha = createHash("sha256").update(fixturePng).digest("hex");
  expect(await sha256(liveOriginal)).toBe(originalSha);
  expect(saved.image).toMatchObject({
    sha256: originalSha,
    annotation_status: "reviewed",
    annotation_revision: 1,
  });

  await page.addInitScript((appVersion) => {
    localStorage.setItem(
      "reefvision.onboarding.dismissed." + appVersion,
      "true",
    );
  }, version.application_version);
  await page.goto(web);
  await page
    .getByRole("button", { name: "System status", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Backups and restore" }),
  ).toBeVisible();
  const post = async (url: string) => {
    const request = await page.waitForRequest(
      (candidate) => candidate.url() === url && candidate.method() === "POST",
      { timeout: 15_000 },
    );
    const response = await request.response();
    if (!response) {
      throw new Error(
        `POST ${new URL(url).pathname}: ${request.failure()?.errorText ?? "no response"}`,
      );
    }
    return response;
  };

  await page.getByRole("textbox", { name: "Backup notes" }).fill(title);
  const creating = post(api + "/backups");
  await page
    .getByRole("button", { name: "Create backup", exact: true })
    .click();
  const created = await json<BackupCreateResponse>(await creating, 201);
  expect(created.backup.request_json).toMatchObject({ notes: title });
  const backupJob = await waitForJob(
    created.job.id,
    "Backup",
    profileJobTimeoutMs,
  );
  const destinationInput = page.getByRole("textbox", {
    name: "Restore destination for " + created.backup.id,
  });
  const card = page.getByRole("article").filter({ has: destinationInput });
  await expect(card.getByText("completed", { exact: true })).toBeVisible();

  const endpoint = api + "/backups/" + created.backup.id;
  const verifying = post(endpoint + "/verify");
  await card
    .getByRole("button", { name: "Verify backup", exact: true })
    .click();
  const verified = await json<BackupVerificationResponse>(await verifying, 200);
  expect(verified).toMatchObject({
    backup_id: created.backup.id,
    current_schema_revision: version.current_schema_revision,
    status: "valid",
    completion_marker_present: true,
    missing_files: [],
    checksum_failures: [],
    errors: [],
  });
  await expect(
    card.getByText("Verification: valid", { exact: true }),
  ).toBeVisible();

  await destinationInput.fill(destination);
  const restoring = post(endpoint + "/restore");
  await card
    .getByRole("button", { name: "Restore into new location", exact: true })
    .click();
  const restored = await json<BackupRestoreResponse>(await restoring, 200);
  expect(restored).toMatchObject({
    backup_id: created.backup.id,
    destination_path: "recoveries/" + destination,
    verification_status: "valid",
  });
  const restoreJob = await waitForJob(
    restored.job.id,
    "Restore",
    profileJobTimeoutMs,
  );
  const jobCard = page
    .getByRole("article")
    .filter({ hasText: "Latest restore job" });
  await expect(
    jobCard.getByRole("heading", { name: "succeeded" }),
  ).toBeVisible();
  expect(restoreJob.result_json).toMatchObject({
    destination_path: restored.destination_path,
    restored_file_count: verified.file_count,
    restored_total_size_bytes: verified.total_size_bytes,
    verification_status: "valid",
  });

  const loaded = async <T>(path: string) =>
    JSON.parse(await readFile(path, "utf8")) as T;
  const receipt = await loaded(join(target, "restore-receipt.json"));
  expect(receipt).toMatchObject({
    backup_id: created.backup.id,
    source_backup_path: created.backup.destination_path,
    restored_destination: restored.destination_path,
  });
  const manifest = await loaded<BackupManifest>(
    managedPath(profile, created.backup.manifest_path),
  );
  expect(manifest.backup_id).toBe(created.backup.id);
  expect(manifest.database_schema_revision).toBe(
    version.current_schema_revision,
  );
  expect(manifest.file_inventory).toHaveLength(verified.file_count);
  const databaseEntry = "database/" + manifest.database_filename;
  const inventoryPaths = manifest.file_inventory.map(({ path }) => path);
  expect(inventoryPaths).toEqual(
    expect.arrayContaining([databaseEntry, "data/" + original]),
  );
  expect(
    inventoryPaths.some((path) => /^data\/(webview2|EBWebView)\//i.test(path)),
  ).toBe(false);
  const snapshot = managedPath(profile, created.backup.destination_path);
  for (const entry of manifest.file_inventory) {
    const source = managedPath(snapshot, entry.path);
    const restoredPath = managedPath(
      target,
      entry.path.slice(entry.path.indexOf("/") + 1),
    );
    expect((await stat(restoredPath)).size).toBe(entry.size_bytes);
    expect(await sha256(source)).toBe(entry.sha256);
    expect(await sha256(restoredPath)).toBe(entry.sha256);
  }
  const recoveredDatabase = managedPath(target, manifest.database_filename);
  const recoveredOriginal = managedPath(target, original);
  expect(await sha256(recoveredOriginal)).toBe(originalSha);
  expect(await sha256(liveOriginal)).toBe(originalSha);
  expect((await stat(liveOriginal, { bigint: true })).ino).toBe(
    liveOriginalBefore.ino,
  );
  expect((await stat(recoveredOriginal, { bigint: true })).ino).not.toBe(
    liveOriginalBefore.ino,
  );
  expect((await stat(recoveredDatabase, { bigint: true })).ino).not.toBe(
    (await stat(version.database_path!, { bigint: true })).ino,
  );
  const copy = new DatabaseSync(recoveredDatabase, { readOnly: true });
  try {
    expect(copy.prepare("PRAGMA quick_check").get()).toEqual({
      quick_check: "ok",
    });
    expect(
      copy.prepare("SELECT name FROM projects WHERE id = ?").get(project.id),
    ).toEqual({ name: title });
    expect(
      copy
        .prepare("SELECT class_index FROM label_classes WHERE id = ?")
        .get(label.id),
    ).toEqual({ class_index: 0 });
    expect(
      copy
        .prepare(
          "SELECT annotation_status, annotation_revision, sha256 FROM images WHERE id = ?",
        )
        .get(imageId),
    ).toEqual({
      annotation_status: "reviewed",
      annotation_revision: 1,
      sha256: originalSha,
    });
    expect(
      copy
        .prepare(
          "SELECT id, label_class_id, x_min, x_max, y_min, y_max FROM annotations WHERE id = ? AND image_id = ?",
        )
        .get(annotation.id, imageId),
    ).toEqual(annotation);
  } finally {
    copy.close();
  }
  const live = await json(
    await page.request.get(imageUrl + "/annotations"),
    200,
  );
  expect(live).toEqual(liveBefore);
  await writeFile(
    info.outputPath("backup-restore-evidence.json"),
    JSON.stringify(
      {
        surface,
        backup_id: created.backup.id,
        backup_job_id: backupJob.id,
        restore_job_id: restoreJob.id,
        restore_status: restoreJob.status,
        restore_destination: restored.destination_path,
        verified_files: verified.file_count,
        restored_files: restoreJob.result_json?.restored_file_count,
        database_schema_revision: version.current_schema_revision,
        backup_database_sha256: await sha256(recoveredDatabase),
        original_sha256: originalSha,
        live_original_unchanged: true,
        independent_recovery: true,
      },
      null,
      2,
    ),
  );
});
