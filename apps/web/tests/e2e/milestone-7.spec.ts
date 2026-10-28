import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const pngBytes = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WHdCkUAAAAASUVORK5CYII=",
  "base64",
);

const project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: "Octocoral imagery",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Muricea Closed",
      scientific_name: null,
      state_name: null,
      display_color: "#E76F51",
      is_active: true,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
  ],
};

const baseImage = {
  id: "image-1",
  project_id: project.id,
  original_filename: "swiftia-frame.png",
  managed_path: "projects/project-1/images/originals/image-1.png",
  thumbnail_path: null,
  sha256: "a".repeat(64),
  width_px: 1600,
  height_px: 1200,
  file_size_bytes: 2048,
  media_type: "image/png",
  import_source: "trial/swiftia-frame.png",
  capture_timestamp: null,
  group_key: "source-01",
  metadata_json: {},
  annotation_status: "in_progress",
  annotation_revision: 1,
  annotation_count: 1,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
};

async function mountBuiltApp(page: Parameters<typeof test>[0]["page"]) {
  const assetDirectory = path.resolve("dist/assets");
  const assets = await readdir(assetDirectory);
  const scriptName = assets.find(
    (name) => name.startsWith("index-") && name.endsWith(".js"),
  );
  const styleName = assets.find((name) => name.endsWith(".css"));
  if (!scriptName || !styleName) {
    throw new Error("Vite build assets are missing");
  }
  const [script, style] = await Promise.all([
    readFile(path.join(assetDirectory, scriptName), "utf8"),
    readFile(path.join(assetDirectory, styleName), "utf8"),
  ]);
  await page.route("http://127.0.0.1:8000/", async (route) => {
    await route.fulfill({
      contentType: "text/html",
      body: '<main id="root"></main>',
    });
  });
  await page.goto("http://127.0.0.1:8000/");
  const packageMetadata = JSON.parse(
    await readFile(path.resolve("package.json"), "utf8"),
  ) as { version: string };
  await page.evaluate((version) => {
    window.localStorage.setItem(
      `reefvision.onboarding.dismissed.${version}`,
      "true",
    );
  }, packageMetadata.version);
  await page.addStyleTag({ content: style });
  await page.addScriptTag({ content: script, type: "module" });
}

function annotationSession() {
  return {
    image: { ...baseImage },
    label_classes: project.label_classes,
    annotations: [
      {
        id: "annotation-1",
        image_id: baseImage.id,
        label_class_id: "class-1",
        x_min: 100,
        y_min: 120,
        x_max: 180,
        y_max: 210,
        source_type: "human",
        source_model_id: null,
        source_prediction_id: null,
        created_by: "local_user",
        created_at: "2026-07-08T00:00:00Z",
        updated_at: "2026-07-08T00:00:00Z",
        deleted_at: null,
        revision: 1,
      },
    ],
    counts_by_class: [{ label_class_id: "class-1", count: 1 }],
    previous_image_id: null,
    next_image_id: null,
  };
}

test("quality-control workflow opens the flagged image and returns to the QC dashboard", async ({
  page,
}) => {
  let qcCreated = false;

  const run = {
    id: "qc-run-1",
    project_id: project.id,
    dataset_version_id: null,
    job_id: "job-qc-1",
    scope_type: "project",
    status: "succeeded",
    rule_categories_json: ["annotation_geometry"],
    selected_rule_ids_json: ["exact_duplicate_box"],
    thresholds_json: {
      near_duplicate_iou_threshold: 0.9,
    },
    configuration_json: {},
    input_checksums_json: {},
    summary_json: {},
    issue_count: 1,
    created_by: "local_user",
    created_at: "2026-07-08T00:00:00Z",
    started_at: "2026-07-08T00:00:01Z",
    completed_at: "2026-07-08T00:00:02Z",
    cancelled_at: null,
    error_message: null,
  };

  const issue = {
    id: "qc-issue-1",
    quality_control_run_id: run.id,
    project_id: project.id,
    dataset_version_id: null,
    image_id: baseImage.id,
    rule_id: "exact_duplicate_box",
    rule_version: "1.0.0",
    severity: "error",
    status: "open",
    fingerprint: "f".repeat(64),
    title: "Exact duplicate bounding boxes",
    explanation:
      "Two annotations have identical geometry and should be reviewed.",
    annotation_ids_json: ["annotation-1"],
    prediction_ids_json: [],
    class_ids_json: ["class-1"],
    measured_values_json: {
      duplicate_annotation_ids: ["annotation-1"],
      iou: 1,
    },
    thresholds_json: {},
    resolution_metadata_json: {},
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
    acknowledged_at: null,
    acknowledged_by: null,
    dismissed_at: null,
    dismissed_by: null,
    dismissed_reason: null,
    resolution_run_id: null,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.1" } });
      return;
    }
    if (
      url.pathname.endsWith("/project-summaries") &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: [
          {
            id: project.id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            storage_root: project.storage_root,
            default_annotation_type: project.default_annotation_type,
            created_at: project.created_at,
            updated_at: project.updated_at,
            archived_at: project.archived_at,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: project });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
      await route.fulfill({
        json: {
          items: [{ ...baseImage }],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/dataset-versions`)) {
      await route.fulfill({ json: [] });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}/quality-control-runs`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: qcCreated ? [run] : [] });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}/quality-control-runs`) &&
      request.method() === "POST"
    ) {
      qcCreated = true;
      await route.fulfill({ status: 201, json: run });
      return;
    }
    if (url.pathname.endsWith(`/quality-control-runs/${run.id}`)) {
      await route.fulfill({ json: run });
      return;
    }
    if (url.pathname.endsWith(`/quality-control-runs/${run.id}/issues`)) {
      await route.fulfill({
        json: {
          items: qcCreated ? [issue] : [],
          total: qcCreated ? 1 : 0,
          page: 1,
          page_size: 25,
          pages: 1,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/annotations`)) {
      await route.fulfill({ json: annotationSession() });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/prediction-proposals`)) {
      await route.fulfill({
        json: {
          items: [
            {
              id: "queue-proposal-1",
              project_id: project.id,
              image_id: baseImage.id,
              model_id: "model-1",
              model_display_name: "Queue detector",
              inference_job_id: "inference-job-1",
              model_checksum: "c".repeat(64),
              label_class_id: project.label_classes[0].id,
              predicted_label: project.label_classes[0].name,
              predicted_index: 0,
              confidence: 0.37,
              geometry_kind: "bounding_box",
              polygon_json: null,
              mask_path: null,
              mask_content_sha256: null,
              x_min: 100,
              y_min: 100,
              x_max: 260,
              y_max: 250,
              review_status: "pending",
              was_edited: false,
              reviewer_action_at: null,
              accepted_annotation_id: null,
              accepted_mask_annotation_id: null,
              inference_settings_json: { confidence_threshold: 0.25 },
              provenance_json: { provider_name: "ultralytics" },
              created_at: "2026-07-08T00:00:00Z",
            },
          ],
          counts: {
            pending: 1,
            accepted: 0,
            rejected: 0,
            edited_and_accepted: 0,
          },
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/content`)) {
      await route.fulfill({
        body: pngBytes,
        contentType: "image/png",
      });
      return;
    }
    await route.abort();
  });

  await mountBuiltApp(page);
  await page.getByRole("button", { name: /CPT Coral Study/ }).click();
  await page.getByRole("tab", { name: "Review" }).click();
  await page.getByRole("tab", { name: "Quality control" }).click();
  await page.getByRole("button", { name: "Run quality control" }).click();

  await expect(
    page.getByText("Exact duplicate bounding boxes").last(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open image" }).click();

  await expect(
    page
      .getByTestId("annotation-editor")
      .getByRole("heading", { name: "swiftia-frame.png" }),
  ).toBeVisible();
  await expect(
    page.getByText("Exact duplicate bounding boxes").last(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Back to Quality Control" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Back to Quality Control" }).click();
  await expect(
    page.getByRole("heading", { name: "Quality Control", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Exact duplicate bounding boxes").last(),
  ).toBeVisible();
});

test("review-queue workflow preserves score context and item state transitions", async ({
  page,
}) => {
  let queueCreated = false;
  let itemState: "pending" | "in_progress" = "pending";
  let startedAt: string | null = null;
  const queueProposal = {
    id: "queue-proposal-1",
    project_id: project.id,
    image_id: baseImage.id,
    model_id: "model-1",
    model_display_name: "Queue detector",
    inference_job_id: "inference-job-1",
    model_checksum: "c".repeat(64),
    label_class_id: project.label_classes[0].id,
    predicted_label: project.label_classes[0].name,
    predicted_index: 0,
    confidence: 0.37,
    geometry_kind: "bounding_box",
    polygon_json: null,
    mask_path: null,
    mask_content_sha256: null,
    x_min: 100,
    y_min: 100,
    x_max: 260,
    y_max: 250,
    review_status: "pending",
    was_edited: false,
    reviewer_action_at: null,
    accepted_annotation_id: null,
    accepted_mask_annotation_id: null,
    inference_settings_json: { confidence_threshold: 0.25 },
    provenance_json: { provider_name: "ultralytics" },
    created_at: "2026-07-08T00:00:00Z",
  };

  const run = {
    id: "qc-run-1",
    project_id: project.id,
    dataset_version_id: null,
    job_id: "job-qc-1",
    scope_type: "project",
    status: "succeeded",
    rule_categories_json: ["statistics"],
    selected_rule_ids_json: ["annotation_count_outlier"],
    thresholds_json: {},
    configuration_json: {},
    input_checksums_json: {},
    summary_json: {},
    issue_count: 1,
    created_by: "local_user",
    created_at: "2026-07-08T00:00:00Z",
    started_at: "2026-07-08T00:00:01Z",
    completed_at: "2026-07-08T00:00:02Z",
    cancelled_at: null,
    error_message: null,
  };

  const queue = {
    id: "queue-1",
    project_id: project.id,
    dataset_version_id: null,
    source_quality_control_run_id: run.id,
    regenerated_from_queue_id: null,
    scope_type: "project",
    status: "complete",
    formula_id: "review_priority_v1",
    formula_version: "1.0.0",
    configuration_json: {},
    input_checksums_json: {},
    summary_json: {},
    item_count: 1,
    created_by: "local_user",
    created_at: "2026-07-08T00:00:00Z",
    completed_at: "2026-07-08T00:00:02Z",
    error_message: null,
  };

  const queueItem = () => ({
    id: "queue-item-1",
    review_queue_id: queue.id,
    project_id: project.id,
    dataset_version_id: null,
    image_id: baseImage.id,
    split: null,
    review_state: itemState,
    score: 82.4,
    rank_position: 1,
    highest_qc_severity: "warning",
    label_class_ids_json: ["class-1"],
    model_ids_json: [],
    related_issue_ids_json: ["qc-issue-1"],
    signal_values_json: {
      unresolved_qc_severity: 0.6,
      unreviewed_state: 1,
    },
    normalized_signals_json: {
      unresolved_qc_severity: 0.6,
      unreviewed_state: 1,
    },
    weights_json: {
      unresolved_qc_severity: 18,
      unreviewed_state: 10,
    },
    score_breakdown_json: [
      {
        signal_id: "unresolved_qc_severity",
        label: "Unresolved QC severity",
        raw_value: 0.6,
        normalized_value: 0.6,
        weight: 18,
        contribution: 43.2,
        description:
          "Unresolved QC severity contributes according to the configured deterministic weight.",
      },
      {
        signal_id: "unreviewed_state",
        label: "Image not marked reviewed",
        raw_value: 1,
        normalized_value: 1,
        weight: 10,
        contribution: 24,
        description:
          "Image not marked reviewed contributes according to the configured deterministic weight.",
      },
    ],
    input_checksum: "c".repeat(64),
    reason_summary:
      "Unresolved QC severity: +43.20, Image not marked reviewed: +24.00",
    skip_reason: null,
    created_at: "2026-07-08T00:00:00Z",
    updated_at: "2026-07-08T00:00:00Z",
    started_at: startedAt,
    completed_at: null,
    returned_at: null,
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({ json: { status: "ok", version: "1.0.1" } });
      return;
    }
    if (
      url.pathname.endsWith("/project-summaries") &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: [
          {
            id: project.id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            storage_root: project.storage_root,
            default_annotation_type: project.default_annotation_type,
            created_at: project.created_at,
            updated_at: project.updated_at,
            archived_at: project.archived_at,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: project });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
      await route.fulfill({
        json: {
          items: [{ ...baseImage }],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/dataset-versions`)) {
      await route.fulfill({ json: [] });
      return;
    }
    if (url.pathname.endsWith(`/projects/${project.id}/quality-control-runs`)) {
      await route.fulfill({ json: [run] });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}/review-queues`) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: queueCreated ? [queue] : [] });
      return;
    }
    if (
      url.pathname.endsWith(`/projects/${project.id}/review-queues`) &&
      request.method() === "POST"
    ) {
      queueCreated = true;
      await route.fulfill({ status: 201, json: queue });
      return;
    }
    if (url.pathname.endsWith(`/review-queues/${queue.id}/items`)) {
      await route.fulfill({
        json: {
          items: queueCreated ? [queueItem()] : [],
          total: queueCreated ? 1 : 0,
          page: 1,
          page_size: 25,
          pages: 1,
        },
      });
      return;
    }
    if (
      url.pathname.endsWith("/review-queue-items/queue-item-1/start") &&
      request.method() === "POST"
    ) {
      itemState = "in_progress";
      startedAt = "2026-07-08T00:00:03Z";
      await route.fulfill({ json: queueItem() });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/annotations`)) {
      await route.fulfill({ json: annotationSession() });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/prediction-proposals`)) {
      await route.fulfill({
        json: {
          items: [queueProposal],
          counts: {
            pending: 1,
            accepted: 0,
            rejected: 0,
            edited_and_accepted: 0,
          },
        },
      });
      return;
    }
    if (url.pathname.endsWith(`/images/${baseImage.id}/content`)) {
      await route.fulfill({
        body: pngBytes,
        contentType: "image/png",
      });
      return;
    }
    await route.abort();
  });

  await mountBuiltApp(page);
  await page.getByRole("button", { name: /CPT Coral Study/ }).click();
  await page.getByRole("tab", { name: "Review" }).click();
  await page.getByRole("tab", { name: "Review queue" }).click();
  await page.getByRole("button", { name: "Generate queue" }).click();

  const reviewQueueList = page.locator(".dashboard-list");

  await expect(
    reviewQueueList.getByText("Rank #1", {
      exact: true,
    }),
  ).toBeVisible();

  await expect(
    reviewQueueList.getByText("Unresolved QC severity", {
      exact: true,
    }),
  ).toBeVisible();
  // A human reviewer label is required before QC triage can start.
  await page.getByLabel("Single-item reviewer label").fill("reef-scientist");
  await page.getByRole("button", { name: "Start review" }).click();
  await expect(page.getByText("in_progress")).toBeVisible();

  await page.getByRole("button", { name: "Open image" }).click();
  await expect(
    page.getByRole("button", { name: "Back to Review Queue" }),
  ).toBeVisible();
  await expect(page.getByText(/Review score 82\.40/)).toBeVisible();
  await page.getByTestId("prediction-row-queue-proposal-1").click();
  await expect(
    page.getByRole("region", { name: "Prediction Inspector" }),
  ).toBeVisible();
  await expect(
    page.getByRole("meter", { name: "Raw model confidence 0.37" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Back to Review Queue" }).click();
  await expect(
    page.getByRole("heading", { name: "Review Queue", exact: true }),
  ).toBeVisible();
  await expect(
    reviewQueueList.getByText("Rank #1", {
      exact: true,
    }),
  ).toBeVisible();
});
