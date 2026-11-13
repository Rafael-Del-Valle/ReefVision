import { expect, test } from "@playwright/test";

const enabled = process.env.REEFPOSE_PHASE5_LIVE_ACCEPTANCE === "1";
const apiBase = "http://127.0.0.1:8000/api/v1";
const projectName = "Phase 5 synthetic gape acceptance";

test.describe("ReefPose Phase 5 live GUI", () => {
  test.skip(
    !enabled,
    "Set REEFPOSE_PHASE5_LIVE_ACCEPTANCE=1 with the isolated seeded API and Vite UI running.",
  );

  test("measures, detects, reviews, reloads, navigates, and exports gape cycles", async ({
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
    const project = projects.find((item) => item.name === projectName);
    expect(project).toBeTruthy();
    const videos = (await (
      await page.request.get(`${apiBase}/projects/${project!.id}/videos`)
    ).json()) as Array<{ id: string }>;
    expect(videos).toHaveLength(1);
    const videoId = videos[0].id;

    const schemaResponse = await page.request.post(
      `${apiBase}/projects/${project!.id}/pose-schemas`,
      {
        data: {
          name: `Phase 5 fish gape ${Date.now()}`,
          landmarks: [
            {
              id: "upper_jaw",
              name: "Upper jaw",
              group: "mouth",
              required: true,
            },
            {
              id: "lower_jaw",
              name: "Lower jaw",
              group: "mouth",
              required: true,
            },
            { id: "eye", name: "Eye", group: "head", required: true },
          ],
          edges: [
            { from_id: "upper_jaw", to_id: "lower_jaw" },
            { from_id: "upper_jaw", to_id: "eye" },
          ],
        },
      },
    );
    expect(schemaResponse.ok()).toBeTruthy();
    const schema = (await schemaResponse.json()) as {
      id: string;
      revision: number;
      content_hash: string;
    };

    const gapeValues = [1, 2, 7, 9, 8, 2, 1, 7, 10, 9, 2, 1];
    const keyframes = gapeValues.map((gape, frame) => ({
      frame,
      bbox: [20 + frame, 20, 40, 30],
      confidence: 0.95,
      pose_observations: [
        {
          id: `upper-${frame}`,
          landmark_id: "upper_jaw",
          semantic_label: "upper_jaw",
          occurrence_index: 0,
          x: 35 + frame,
          y: 30,
          confidence: 0.95,
          status: "visible",
          source: "model",
        },
        {
          id: `lower-${frame}`,
          landmark_id: "lower_jaw",
          semantic_label: "lower_jaw",
          occurrence_index: 0,
          x: 35 + frame,
          y: 30 + gape,
          confidence: 0.92,
          status: "visible",
          source: "model",
        },
        {
          id: `eye-${frame}`,
          landmark_id: "eye",
          semantic_label: "eye",
          occurrence_index: 0,
          x: 45 + frame,
          y: 25,
          confidence: 0.9,
          status: "visible",
          source: "model",
        },
      ],
    }));
    const trackResponse = await page.request.post(
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
    expect(trackResponse.status(), await trackResponse.text()).toBe(201);
    const track = (await trackResponse.json()) as {
      id: string;
      revision: number;
    };
    const bindResponse = await page.request.put(
      `${apiBase}/video-tracks/${track.id}`,
      {
        data: {
          base_revision: track.revision,
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
    expect(bindResponse.ok()).toBeTruthy();

    await page.getByRole("button", { name: `Open ${projectName}` }).click();
    await page.getByRole("tab", { name: "Video & automation" }).click();
    await page.getByRole("tab", { name: "Video & tracking" }).click();

    const identityPanel = page.getByRole("region", {
      name: "Animal identity tracking",
    });
    await expect(identityPanel).toBeVisible();
    const identityQueued = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/projects\/[^/]+\/pose-identity-runs$/.test(
          new URL(response.url()).pathname,
        ),
    );
    await identityPanel
      .getByRole("button", { name: "Associate individuals" })
      .click();
    const identityJob = (await (await identityQueued).json()) as {
      result_json: { run_id: string };
    };
    const identityRunId = identityJob.result_json.run_id;
    await expect
      .poll(async () => {
        const response = await page.request.get(
          `${apiBase}/pose-identity-runs/${identityRunId}`,
        );
        return ((await response.json()) as { status: string }).status;
      })
      .toBe("completed");
    await identityPanel.getByLabel("Identity run").selectOption(identityRunId);
    await expect(
      identityPanel.getByRole("button", { name: "Accept" }),
    ).toHaveCount(1);
    await identityPanel.getByRole("button", { name: "Accept" }).click();
    await expect(identityPanel.getByText("Scientist Confirmed")).toBeVisible();

    const movement = page.getByRole("region", {
      name: "Biological movement analysis",
    });
    await expect(movement).toBeVisible();
    await expect(movement.getByLabel("Individual")).toContainText(
      "animal-0001",
    );
    await movement
      .getByRole("button", { name: "Calculate measurements" })
      .click();
    const measurementRunId = await expect
      .poll(async () => {
        const response = await page.request.get(
          `${apiBase}/projects/${project!.id}/pose-measurement-runs`,
        );
        const runs = (await response.json()) as Array<{
          id: string;
          status: string;
        }>;
        return runs.find((run) => run.status === "completed")?.id ?? "";
      })
      .not.toBe("")
      .then(async () => {
        const response = await page.request.get(
          `${apiBase}/projects/${project!.id}/pose-measurement-runs`,
        );
        const runs = (await response.json()) as Array<{
          id: string;
          status: string;
        }>;
        return runs.find((run) => run.status === "completed")!.id;
      });
    await movement
      .getByLabel("Saved measurement run")
      .selectOption(measurementRunId);
    await expect(
      movement.getByRole("img", { name: "Anatomical measurement time series" }),
    ).toBeVisible();

    await movement.getByRole("button", { name: "Detect cycles" }).click();
    const eventRunId = await expect
      .poll(async () => {
        const response = await page.request.get(
          `${apiBase}/projects/${project!.id}/pose-event-runs`,
        );
        const runs = (await response.json()) as Array<{
          id: string;
          status: string;
        }>;
        return runs.find((run) => run.status === "completed")?.id ?? "";
      })
      .not.toBe("")
      .then(async () => {
        const response = await page.request.get(
          `${apiBase}/projects/${project!.id}/pose-event-runs`,
        );
        const runs = (await response.json()) as Array<{
          id: string;
          status: string;
        }>;
        return runs.find((run) => run.status === "completed")!.id;
      });
    await movement.getByLabel("Saved event run").selectOption(eventRunId);
    await expect(movement.getByLabel("Event candidate")).toContainText(
      "Frames 2–5",
    );
    await movement.getByRole("button", { name: "Go to event frame" }).click();
    await expect(
      identityPanel.getByRole("img", { name: /skeleton at frame 3/ }),
    ).toBeVisible();
    await movement.getByLabel("Start frame").fill("1");
    await movement.getByLabel("End frame").fill("5");
    await movement
      .getByLabel("Review reason")
      .fill("Include the observed closed baseline before the first gape");
    await movement.getByRole("button", { name: "Save boundaries" }).click();
    await expect(movement.getByLabel("Event candidate")).toContainText(
      "Frames 1–5",
    );
    await movement.getByRole("button", { name: "Confirm complete" }).click();
    const secondEventId = await movement
      .getByLabel("Event candidate")
      .locator("option")
      .filter({ hasText: "Frames 7–10" })
      .getAttribute("value");
    expect(secondEventId).toBeTruthy();
    await movement.getByLabel("Event candidate").selectOption(secondEventId!);
    await movement.getByRole("button", { name: "Confirm complete" }).click();
    await expect(movement.getByTestId("event-status")).toContainText(
      "Confirmed complete cycles: 2",
    );

    await page.reload();
    await page.getByRole("button", { name: `Open ${projectName}` }).click();
    await page.getByRole("tab", { name: "Video & automation" }).click();
    await page.getByRole("tab", { name: "Video & tracking" }).click();
    const reopened = page.getByRole("region", {
      name: "Biological movement analysis",
    });
    await expect(
      reopened.getByText("Event revision history (5)"),
    ).toBeVisible();
    await expect(
      reopened.getByRole("link", { name: "Reviewed JSON" }),
    ).toBeVisible();

    const exported = await page.request.get(
      `${apiBase}/pose-event-runs/${eventRunId}/export?format=json`,
    );
    expect(exported.ok()).toBeTruthy();
    const payload = (await exported.json()) as {
      scientific_status: string;
      events: Array<{
        start_frame: number;
        amplitude: number;
        cycle_state: string;
        review_state: string;
      }>;
      measurement_series: Array<{ samples: unknown[] }>;
    };
    expect(payload.scientific_status).toBe("scientist_reviewed");
    expect(payload.events).toHaveLength(2);
    expect(
      payload.events.every(
        (event) =>
          event.cycle_state === "complete" &&
          event.review_state === "confirmed",
      ),
    ).toBeTruthy();
    expect(
      payload.events.find((event) => event.start_frame === 1)?.amplitude,
    ).toBe(7);
    expect(payload.measurement_series[0].samples).toHaveLength(12);
  });
});
