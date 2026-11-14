import { expect, test } from "@playwright/test";

test("freezes independent references and reviews an actual validation job", async ({
  page,
}) => {
  test.skip(
    process.env.REEFPOSE_PHASE6_LIVE_ACCEPTANCE !== "1",
    "Requires isolated local API and Vite.",
  );
  const api = "http://127.0.0.1:8000/api/v1";
  const projectName = "Phase 5 synthetic gape acceptance";
  const projects = await (await page.request.get(`${api}/projects`)).json();
  const project = projects.find(
    (row: { name: string }) => row.name === projectName,
  );
  expect(project).toBeTruthy();
  const base = `${api}/projects/${project.id}`;
  const [video] = await (await page.request.get(`${base}/videos`)).json();
  const schemaResponse = await page.request.post(`${base}/pose-schemas`, {
    data: {
      name: "Synthetic jaw markers",
      landmarks: [
        { id: "upper", name: "Upper jaw" },
        { id: "lower", name: "Lower jaw" },
      ],
      edges: [],
    },
  });
  expect(schemaResponse.status()).toBe(201);
  const schema = await schemaResponse.json();
  const values = [1, 2, 7, 9, 8, 2, 1, 7, 10, 9, 2, 1];
  const box = [20, 20, 40, 30];
  const keyframes = values.map((gape, frame) => ({
    frame,
    bbox: box,
    confidence: 0.95,
    pose_observations: ["upper", "lower"].map((id, index) => ({
      id: `${id}-${frame}`,
      landmark_id: id,
      semantic_label: id,
      occurrence_index: 0,
      x: 35,
      y: 30 + (index ? gape : 0),
      confidence: 0.95,
      status: "visible",
      source: "model",
    })),
  }));
  const trackRequest = {
    label_class_id: project.label_classes[0].id,
    keyframes,
    interpolation: "hold",
    status: "verified",
  };
  const created = await page.request.post(`${api}/videos/${video.id}/tracks`, {
    data: { ...trackRequest, geometry_kind: "bbox" },
  });
  expect(created.status()).toBe(201);
  const track = await created.json();
  const bound = await page.request.put(`${api}/video-tracks/${track.id}`, {
    data: {
      ...trackRequest,
      base_revision: track.revision,
      pose_schema_binding: {
        schema_id: schema.id,
        schema_revision: schema.revision,
        content_hash: schema.content_hash,
      },
    },
  });
  expect(bound.ok()).toBeTruthy();
  const association = await page.request.post(`${base}/pose-identity-runs`, {
    data: {
      video_id: video.id,
      source_track_ids: [track.id],
      pose_schema_id: schema.id,
      pose_schema_revision: schema.revision,
      pose_schema_content_hash: schema.content_hash,
    },
  });
  expect(association.status(), await association.text()).toBe(202);
  const runId = (await association.json()).result_json.run_id;
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`${api}/pose-identity-runs/${runId}`)
          ).json()
        ).status,
    )
    .toBe("completed");

  const annotations = ["rater-a", "rater-b"].map((rater_id) => ({
    rater_id,
    blinded: true,
    poses: values.map((gape, frame) => ({
      individual_id: "fish-a",
      frame,
      bbox: box,
      landmarks: [
        { id: "upper", x: 35, y: 30, visibility: "visible" },
        { id: "lower", x: 35, y: 30 + gape, visibility: "visible" },
      ],
    })),
    measurements: values.map((value, frame) => ({
      individual_id: "fish-a",
      frame,
      definition_id: "gape",
      value,
      unit: "pixels",
    })),
    events: [
      { id: "cycle-a", start_s: 0.2, end_s: 0.5, peak_s: 0.3 },
      { id: "cycle-b", start_s: 0.7, end_s: 1, peak_s: 0.8 },
    ].map((event) => ({ ...event, label: "gape", individual_id: "fish-a" })),
  }));
  const manifest = {
    name: "Chromium reference fixture",
    data_kind: "synthetic",
    recordings: [
      {
        video_id: video.id,
        video_sha256: video.sha256,
        schema_id: schema.id,
        schema_revision: schema.revision,
        schema_sha256: schema.content_hash,
        group_id: "synthetic-recording",
        exhaustive_identity_coverage: true,
        split: "development",
        annotations,
        individuals: [{ id: "fish-a", species: "synthetic fish" }],
        event_windows: [
          { individual_id: "fish-a", label: "gape", start_s: 0, end_s: 1.2 },
        ],
      },
    ],
  };
  await page.addInitScript(() =>
    localStorage.setItem("reefvision.onboarding.dismissed.1.0.3", "true"),
  );
  await page.goto("http://127.0.0.1:5173/");
  await page.getByRole("button", { name: `Open ${projectName}` }).click();
  await page.getByRole("tab", { name: "Video & automation" }).click();
  await page.getByRole("tab", { name: "Video & tracking" }).click();
  await page
    .getByText("ReefPose scientific validation", { exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "ReefPose scientific validation",
  });
  await panel
    .getByLabel("Independent reference manifest")
    .fill(JSON.stringify(manifest));
  await panel.getByRole("button", { name: "Freeze reference" }).click();
  await panel.getByLabel("Reference rater").selectOption("rater-b");
  await panel.getByLabel(/Original identity run/).selectOption(runId);
  await panel.getByLabel("Development configurations (JSON)").fill(
    JSON.stringify([
      {
        definitions: [
          {
            id: "gape",
            name: "Gape distance",
            kind: "distance",
            landmark_ids: ["upper", "lower"],
          },
        ],
        events: [
          {
            label: "gape",
            definition_id: "gape",
            unit: "pixels",
            open_threshold: 6,
            close_threshold: 3,
          },
        ],
      },
    ]),
  );
  await panel
    .getByRole("button", { name: "Run scientific validation" })
    .click();
  await expect(panel.getByText("Validation succeeded (1/1)")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    panel.getByText(/Complete event precision.*2 TP, 0 FP, 0 FN/),
  ).toBeVisible();
  await panel
    .getByText("fish-a · gape · 2 TP, 0 FP, 0 FN", { exact: true })
    .click();
  await expect(panel.getByText(/cycle-a.*Onset error 0\.000 s/)).toBeVisible();
  await panel
    .getByRole("button", { name: "Go to reference event" })
    .first()
    .click();
  await expect(panel.getByText(/Inter-observer ICC.*1\.000/)).toBeVisible();
  await expect(
    panel.getByRole("img", { name: "Paired mean versus signed difference" }),
  ).toBeVisible();
  const url = await panel
    .getByRole("link", { name: "Validation JSON" })
    .getAttribute("href");
  const exported = await page.request.get(url!);
  expect(exported.ok()).toBeTruthy();
  expect((await exported.json()).result_sha256).toMatch(/^[0-9a-f]{64}$/);
});
