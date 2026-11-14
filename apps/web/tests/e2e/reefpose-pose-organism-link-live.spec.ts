import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

const api =
  process.env.REEFVISION_POSE_LINK_API_URL ?? "http://127.0.0.1:8014/api/v1";
const ui = process.env.REEFVISION_POSE_LINK_UI_URL ?? "http://127.0.0.1:5184/";

test("confirms, opens, corrects and unlinks a scoped organism pose identity", async ({
  page,
}) => {
  const source = process.env.REEFVISION_POSE_LINK_TEST_VIDEO;
  test.skip(!source, "Provide an isolated API, UI and a synthetic test video.");
  test.setTimeout(75_000);
  const title = `Reviewed pose link ${Date.now()}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name: title, template: "blank" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const project = await created.json();
  const projectApi = `${api}/projects/${project.id}`;
  const createdClass = await page.request.post(`${projectApi}/classes`, {
    data: { name: "Fish", class_index: 0, display_color: "#20b070" },
  });
  expect(createdClass.status(), await createdClass.text()).toBe(201);
  const fishClass = await createdClass.json();
  const imported = await page.request.post(`${projectApi}/imports/videos`, {
    multipart: {
      file: {
        name: "pose-recording.mp4",
        mimeType: "video/mp4",
        buffer: await readFile(source!),
      },
    },
  });
  expect(imported.status(), await imported.text()).toBe(201);
  const video = await imported.json();
  const schemaResponse = await page.request.post(`${projectApi}/pose-schemas`, {
    data: {
      name: "Fixture fish anatomy",
      landmarks: [{ id: "snout", name: "Snout" }],
      edges: [],
    },
  });
  expect(schemaResponse.status(), await schemaResponse.text()).toBe(201);
  const schema = await schemaResponse.json();
  const tracks: string[] = [];
  for (const [animal, offset] of [
    [0, 20],
    [1, 150],
  ]) {
    const keyframes = [0, 2, 4].map((frame) => ({
      frame,
      bbox: [offset + frame, 20, 24, 18],
      confidence: 0.98,
      pose_observations: [
        {
          id: `${animal}-${frame}`,
          landmark_id: "snout",
          semantic_label: "Snout",
          occurrence_index: 0,
          x: offset + frame + 3,
          y: 28,
          confidence: 0.98,
          status: "visible",
          source: "model",
        },
      ],
    }));
    const trackResponse = await page.request.post(
      `${api}/videos/${video.id}/tracks`,
      {
        data: {
          label_class_id: fishClass.id,
          geometry_kind: "bbox",
          keyframes,
          status: "verified",
          interpolation: "hold",
        },
      },
    );
    expect(trackResponse.status(), await trackResponse.text()).toBe(201);
    const track = await trackResponse.json();
    tracks.push(track.id);
    const bound = await page.request.put(`${api}/video-tracks/${track.id}`, {
      data: {
        base_revision: track.revision,
        label_class_id: fishClass.id,
        keyframes,
        status: "verified",
        interpolation: "hold",
        pose_schema_binding: {
          schema_id: schema.id,
          schema_revision: schema.revision,
          content_hash: schema.content_hash,
        },
      },
    });
    expect(bound.ok(), await bound.text()).toBeTruthy();
  }
  const association = await page.request.post(
    `${projectApi}/pose-identity-runs`,
    {
      data: {
        video_id: video.id,
        source_track_ids: tracks,
        pose_schema_id: schema.id,
        pose_schema_revision: schema.revision,
        pose_schema_content_hash: schema.content_hash,
      },
    },
  );
  expect(association.status(), await association.text()).toBe(202);
  const runId = (await association.json()).result_json.run_id;
  const runApi = `${api}/pose-identity-runs/${runId}`;
  await expect
    .poll(async () => (await (await page.request.get(runApi)).json()).status)
    .toBe("completed");
  const animals = await (await page.request.get(`${runApi}/identities`)).json();
  expect(animals).toHaveLength(2);
  const firstAnimal = animals[0];
  const accepted = await page.request.post(`${runApi}/corrections`, {
    data: {
      action: "accept",
      target_type: "identity",
      target_id: firstAnimal.id,
      actor: "Field scientist",
    },
  });
  expect(accepted.status(), await accepted.text()).toBe(201);
  const organism = await page.request.post(`${projectApi}/ecology/organisms`, {
    data: {
      organism_key: "marked-fish",
      kind: "individual",
      reason: "Field specimen register",
    },
  });
  expect(organism.status(), await organism.text()).toBe(201);

  await page.addInitScript(() =>
    window.localStorage.setItem(
      "reefvision.onboarding.dismissed.1.2.0",
      "true",
    ),
  );
  const openOrganism = async () => {
    await page.goto(ui);
    await page.getByRole("button", { name: `Open ${title}` }).click();
    await page.getByRole("tab", { name: "Organisms & ecology" }).click();
    await page.getByRole("button", { name: "Pose measurements" }).click();
    await expect(
      page.getByRole("region", { name: "Reviewed pose links" }),
    ).toBeVisible();
  };
  await openOrganism();
  const section = page.getByRole("region", { name: "Reviewed pose links" });
  await section.getByRole("button", { name: "Link reviewed pose" }).click();
  const form = section.getByRole("form", { name: "Link reviewed pose" });
  await form.getByLabel(/Reviewed identity run/).selectOption(runId);
  await form.getByLabel(/Animal identity/).selectOption(firstAnimal.id);
  await form.getByLabel("First frame").fill("2");
  await expect(
    form.getByText(/Frames without reviewed observations remain gaps/),
  ).toBeVisible();
  await form.getByLabel("Reviewer").fill("Field scientist");
  await form.getByLabel("Reason").fill("Recognized the marked specimen");
  await form.getByRole("checkbox", { name: /I confirm/ }).check();
  await form.getByRole("button", { name: "Confirm pose link" }).click();
  await expect(section.getByText("Confirmed link")).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("confirmed.png"),
    fullPage: true,
  });
  await section.getByRole("button", { name: "Open pose evidence" }).click();
  const identity = page.getByRole("region", {
    name: "Animal identity tracking",
  });
  await expect(identity.getByLabel(/Identity run/)).toHaveValue(runId);
  await expect(
    identity.getByText(
      new RegExp(
        `Linked organism evidence.*${firstAnimal.stable_identity_key}`,
      ),
    ),
  ).toBeVisible();
  await expect(
    identity.getByRole("img", {
      name: `Animal ${firstAnimal.stable_identity_key} skeleton at frame 2`,
    }),
  ).toBeVisible();

  await page.screenshot({
    path: test.info().outputPath("source-video.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Back to organism marked-fish" })
    .click();
  await expect(section.getByText("Confirmed link")).toBeVisible();

  const rejected = await page.request.post(`${runApi}/corrections`, {
    data: {
      action: "reject",
      target_type: "identity",
      target_id: firstAnimal.id,
      frame_start: 2,
      frame_end: 2,
      actor: "Field scientist",
    },
  });
  expect(rejected.status(), await rejected.text()).toBe(201);
  await openOrganism();
  await expect(section.getByText("Stale evidence")).toBeVisible();
  await section.getByRole("button", { name: "Correct link" }).click();
  const correction = section.getByRole("form", { name: "Correct pose link" });
  await correction.getByLabel("First frame").fill("4");
  await correction.getByLabel("Reviewer").fill("Field scientist");
  await correction.getByLabel("Reason").fill("Exclude the uncertain frame");
  await correction.getByRole("checkbox", { name: /I confirm/ }).check();
  await correction
    .getByRole("button", { name: "Save link correction" })
    .click();
  await expect(
    section.getByRole("heading", { name: "Frames 4–4" }),
  ).toBeVisible();
  await section.getByRole("button", { name: "Unlink" }).click();
  const unlink = section.getByRole("form", { name: "Unlink reviewed pose" });
  await unlink.getByLabel("Reviewer").fill("Field scientist");
  await unlink.getByLabel("Reason").fill("Association withdrawn after review");
  await unlink.getByRole("checkbox", { name: /I confirm/ }).check();
  await unlink.getByRole("button", { name: "Confirm unlink" }).click();
  await expect(section.getByText("Unlinked", { exact: true })).toBeVisible();
  await section.getByText("Link history and provenance").click();
  await expect(section.getByText(/r3 · unlink/)).toBeVisible();
  await expect(section.getByText(/r2 · correct/)).toBeVisible();
  await expect(section.getByText(/r1 · link/)).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("history.png"),
    fullPage: true,
  });
});
