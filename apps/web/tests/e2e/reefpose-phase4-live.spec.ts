import { expect, test } from "@playwright/test";

const enabled = process.env.REEFPOSE_PHASE4_LIVE_ACCEPTANCE === "1";
const apiBase = "http://127.0.0.1:8000/api/v1";

test.describe("ReefPose Phase 4 live GUI", () => {
  test.skip(
    !enabled,
    "Set REEFPOSE_PHASE4_LIVE_ACCEPTANCE=1 with the isolated API, worker, and Vite UI running.",
  );

  test("associates, corrects, reloads, evaluates, and exports two identities", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "reefvision.onboarding.dismissed.1.0.3",
        "true",
      );
    });
    await page.goto("http://127.0.0.1:5173/");

    const projects = (await (
      await page.request.get(`${apiBase}/projects`)
    ).json()) as Array<{
      id: string;
      name: string;
      label_classes: Array<{ id: string }>;
    }>;
    const project = projects.find(
      (item) => item.name === "Phase 9 verified pose dataset",
    );
    expect(project).toBeTruthy();
    const videos = (await (
      await page.request.get(`${apiBase}/projects/${project!.id}/videos`)
    ).json()) as Array<{ id: string }>;
    expect(videos.length).toBeGreaterThan(0);
    const videoId = videos[0].id;

    const schemaResponse = await page.request.post(
      `${apiBase}/projects/${project!.id}/pose-schemas`,
      {
        data: {
          name: `Phase 4 synthetic fish ${Date.now()}`,
          landmarks: [
            {
              id: "nose",
              name: "Nose",
              group: "head",
              required: true,
            },
          ],
          edges: [],
        },
      },
    );
    expect(schemaResponse.ok()).toBeTruthy();
    const schema = (await schemaResponse.json()) as {
      id: string;
      revision: number;
      content_hash: string;
    };

    const createPoseTrack = async (offset: number, prefix: string) => {
      const keyframes = [0, 1, 2].map((frame) => ({
        frame,
        bbox: [offset + frame * 4, 20, 30, 15],
        confidence: 0.9,
        pose_observations: [
          {
            id: `${prefix}-${frame}-nose`,
            landmark_id: "nose",
            semantic_label: "nose",
            occurrence_index: 0,
            x: offset + frame * 4 + 5,
            y: 25,
            confidence: 0.9,
            status: "visible",
            source: "model",
          },
        ],
      }));
      const createdResponse = await page.request.post(
        `${apiBase}/videos/${videoId}/tracks`,
        {
          data: {
            label_class_id: project!.label_classes[0].id,
            geometry_kind: "bbox",
            keyframes,
            interpolation: "hold",
            status: "verified",
          },
        },
      );
      expect(createdResponse.ok()).toBeTruthy();
      const created = (await createdResponse.json()) as {
        id: string;
        revision: number;
      };
      const boundResponse = await page.request.put(
        `${apiBase}/video-tracks/${created.id}`,
        {
          data: {
            base_revision: created.revision,
            label_class_id: project!.label_classes[0].id,
            keyframes,
            interpolation: "hold",
            status: "verified",
            pose_schema_binding: {
              schema_id: schema.id,
              schema_revision: schema.revision,
              content_hash: schema.content_hash,
            },
          },
        },
      );
      expect(boundResponse.ok()).toBeTruthy();
      return created.id;
    };

    await createPoseTrack(10, "left");
    await createPoseTrack(150, "right");

    await page
      .getByRole("button", { name: "Open Phase 9 verified pose dataset" })
      .click();
    await page.getByRole("tab", { name: "Video & automation" }).click();
    await page.getByRole("tab", { name: "Video & tracking" }).click();

    const identityPanel = page.getByRole("region", {
      name: "Animal identity tracking",
    });
    await expect(identityPanel).toBeVisible();
    const queuedResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/projects\/[^/]+\/pose-identity-runs$/.test(
          new URL(response.url()).pathname,
        ),
    );
    await identityPanel
      .getByRole("button", { name: "Associate individuals" })
      .click();
    const job = (await (await queuedResponse).json()) as {
      result_json: { run_id: string };
    };
    const runId = job.result_json.run_id;

    await expect
      .poll(
        async () => {
          const response = await page.request.get(
            `${apiBase}/pose-identity-runs/${runId}`,
          );
          return ((await response.json()) as { status: string }).status;
        },
        { timeout: 60_000 },
      )
      .toBe("completed");

    await expect(
      identityPanel.getByRole("option", { name: /completed/ }),
    ).toHaveCount(1, {
      timeout: 10_000,
    });
    await identityPanel.getByLabel("Identity run").selectOption(runId);
    await expect(
      identityPanel.getByRole("button", { name: "animal-0001" }),
    ).toBeVisible();
    await expect(
      identityPanel.getByRole("button", { name: "animal-0002" }),
    ).toBeVisible();
    await expect(
      identityPanel.getByRole("img", {
        name: "Animal animal-0001 skeleton at frame 0",
      }),
    ).toBeVisible();

    await identityPanel.getByLabel("Correction action").selectOption("swap");
    await identityPanel
      .getByLabel("Identity to correct")
      .selectOption({ index: 1 });
    await identityPanel
      .getByLabel("Destination identity")
      .selectOption({ index: 2 });
    await identityPanel.getByLabel("Frame start").fill("0");
    await identityPanel.getByLabel("Frame end").fill("0");
    await identityPanel
      .getByLabel("Correction reason")
      .fill("Phase 4 live crossing correction");
    const correctionResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith(
          `/pose-identity-runs/${runId}/corrections`,
        ),
    );
    await identityPanel
      .getByRole("button", { name: "Save identity correction" })
      .click();
    expect((await correctionResponse).status()).toBe(201);
    await expect(
      identityPanel.getByText("Correction history (1)"),
    ).toBeVisible();

    await page.reload();
    await page
      .getByRole("button", { name: "Open Phase 9 verified pose dataset" })
      .click();
    await page.getByRole("tab", { name: "Video & automation" }).click();
    await page.getByRole("tab", { name: "Video & tracking" }).click();
    const reopenedPanel = page.getByRole("region", {
      name: "Animal identity tracking",
    });
    await reopenedPanel.getByLabel("Identity run").selectOption(runId);
    await expect(
      reopenedPanel.getByText("Correction history (1)"),
    ).toBeVisible();
    await expect(reopenedPanel.getByText(/Revision 2 · Swap/)).toBeVisible();

    const truthResponse = await page.request.post(
      `${apiBase}/projects/${project!.id}/pose-identity-truth-datasets`,
      {
        data: {
          name: `Phase 4 live synthetic truth ${Date.now()}`,
          video_id: videoId,
          pose_schema_id: schema.id,
          pose_schema_revision: schema.revision,
          pose_schema_content_hash: schema.content_hash,
          scientific_context: "synthetic_engineering",
          verified_by: "phase4-live-fixture",
          observations: [
            ...[0, 1, 2].map((frame) => ({
              identity_id: "truth-left",
              frame_index: frame,
              bbox: [10 + frame * 4, 20, 30, 15],
            })),
            ...[0, 1, 2].map((frame) => ({
              identity_id: "truth-right",
              frame_index: frame,
              bbox: [150 + frame * 4, 20, 30, 15],
            })),
          ],
        },
      },
    );
    expect(truthResponse.ok()).toBeTruthy();
    const truth = (await truthResponse.json()) as { id: string };
    const evaluationResponse = await page.request.post(
      `${apiBase}/pose-identity-runs/${runId}/evaluations`,
      { data: { truth_dataset_id: truth.id, spatial_iou_threshold: 0.5 } },
    );
    expect(evaluationResponse.status()).toBe(201);
    const evaluation = (await evaluationResponse.json()) as {
      metrics_json: { id_f1: number };
      warnings_json: string[];
    };
    expect(evaluation.metrics_json.id_f1).toBeGreaterThanOrEqual(0);
    expect(evaluation.warnings_json.join(" ").toLowerCase()).toContain(
      "synthetic",
    );

    const exported = await page.request.get(
      `${apiBase}/pose-identity-runs/${runId}/export?format=json`,
    );
    expect(exported.ok()).toBeTruthy();
    const exportPayload = (await exported.json()) as {
      corrections: Array<{ revision: number }>;
      association_run: { parameters_sha256: string };
    };
    expect(exportPayload.corrections[0].revision).toBe(2);
    expect(exportPayload.association_run.parameters_sha256).toHaveLength(64);
  });
});
