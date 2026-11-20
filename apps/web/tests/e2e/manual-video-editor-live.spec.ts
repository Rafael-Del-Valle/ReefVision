import { expect } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { test } from "./spatialDesktop";

test("edits video tracks reversibly while hidden tracks and original pixels survive", async ({
  desktop,
}, info) => {
  test.setTimeout(120_000);
  const { page, web, api, surface } = desktop;
  const name = `Synthetic manual video ${randomUUID().slice(0, 8)}`;
  // Baseline H.264 transcode of synthetic-ordinary-clip.mp4 for Windows playback.
  const clip = await readFile(
    new URL("./fixtures/synthetic-manual-track-h264.mp4", import.meta.url),
  );
  const sha = (blob: Buffer) => createHash("sha256").update(blob).digest("hex");
  const originalSha = sha(clip);
  expect(originalSha).toBe(
    "f2633700e978471bfad9d33f87e539d02f9658afeeacfce340fd9d34c9c91b92",
  );
  async function json(response: Awaited<ReturnType<typeof page.request.get>>) {
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  }
  const get = async (url: string) => json(await page.request.get(url));
  const waitFor = (method: string, url: string) =>
    page.waitForResponse(
      (response) =>
        response.request().method() === method && response.url() === url,
    );
  const project = await json(
    await page.request.post(`${api}/projects`, {
      data: { name, template: "blank" },
    }),
  );
  const projectUrl = `${api}/projects/${project.id}`;
  const createClass = async (name: string, class_index: number) =>
    json(
      await page.request.post(`${projectUrl}/classes`, {
        data: { class_index, name, display_color: "#28A95C" },
      }),
    );
  const primary = await createClass("Fixture animal", 0);
  const background = await createClass("Fixture masked animal", 1);

  const health = await get(`${api}/health`);
  await page.addInitScript((version) => {
    localStorage.setItem(`reefvision.onboarding.dismissed.${version}`, "true");
  }, health.version);
  async function openWorkspace() {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & automation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Video & tracking", exact: true })
      .click();
  }
  await openWorkspace();
  const workspace = page.getByTestId("video-tracking-workspace");
  const editor = workspace.locator("section").filter({
    has: page.getByRole("heading", {
      name: "Identities and keyframes",
      exact: true,
    }),
  });
  const player = workspace.locator("video").first();
  const overlay = workspace.getByRole("checkbox", {
    name: "Enable source-coordinate overlay",
  });
  const picker = editor.getByRole("combobox", { name: /^Existing track/ });
  const undo = editor.getByRole("button", { name: "Undo", exact: true });
  const redo = editor.getByRole("button", { name: "Redo", exact: true });
  const save = editor.getByRole("button", { name: "Save track", exact: true });
  const cancel = editor.getByRole("button", {
    name: "Cancel track edits",
    exact: true,
  });
  const changeX = editor.getByRole("spinbutton", {
    name: "x for keyframe 4",
    exact: true,
  });
  function classButton(name: string) {
    return editor.getByRole("button", { name, exact: true });
  }
  async function goToFrame(frame: number) {
    if (!(await overlay.isChecked())) await overlay.check();
    const slider = workspace.getByRole("slider", { name: /^Frame \d+$/ });
    await slider.press("Home");
    for (let step = 0; step < frame; step++) await slider.press("ArrowRight");
    await expect(
      workspace.getByRole("img", { name: `Frame ${frame}`, exact: true }),
    ).toBeVisible();
  }

  await workspace.getByLabel("Video file", { exact: true }).setInputFiles({
    name: "synthetic-manual-track.mp4",
    mimeType: "video/mp4",
    buffer: clip,
  });
  const imported = waitFor("POST", `${projectUrl}/imports/videos`);
  await workspace
    .getByRole("button", { name: "Import video", exact: true })
    .click();
  const video = await json(await imported);
  expect(video).toMatchObject({
    sha256: originalSha,
    width_px: 96,
    height_px: 64,
    fps: 10,
    frame_count: 12,
  });
  const videoUrl = `${api}/videos/${video.id}`;
  const tracksUrl = `${videoUrl}/tracks`;
  const actualPlayback = () =>
    player.evaluate((media: HTMLVideoElement) => ({
      loaded: media.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA,
      error: media.error?.code ?? null,
      width: media.videoWidth,
      height: media.videoHeight,
    }));
  await expect
    .poll(actualPlayback)
    .toEqual({ loaded: true, error: null, width: 96, height: 64 });

  const extraction = waitFor("POST", `${videoUrl}/extract`);
  await workspace
    .getByRole("button", { name: "Extract review frames" })
    .click();
  const job = await json(await extraction);
  await expect
    .poll(async () => (await get(`${api}/jobs/${job.id}`)).status, {
      timeout: 30_000,
    })
    .toBe("succeeded");
  await goToFrame(4);
  await editor
    .getByRole("combobox", { name: /^Identity class/ })
    .selectOption(primary.id);
  const addFrame = editor.getByRole("button", {
    name: "Add keyframe at frame 4",
    exact: true,
  });
  await addFrame.click();
  const coordinateLabels = ["x", "y", "width", "height"];
  for (const [index, value] of [8, 7, 24, 19].entries()) {
    await editor
      .getByRole("spinbutton", {
        name: `${coordinateLabels[index]} for keyframe 4`,
        exact: true,
      })
      .fill(String(value));
  }
  await expect(addFrame).toBeDisabled();
  await goToFrame(8);
  await editor
    .getByRole("button", { name: "Add keyframe at frame 8", exact: true })
    .click();
  const creation = waitFor("POST", tracksUrl);
  await save.click();
  const initial = await json(await creation);
  expect(initial).toMatchObject({
    revision: 1,
    label_class_id: primary.id,
    status: "verified",
  });
  expect(initial.keyframes_json[0].bbox).toEqual([8, 7, 24, 19]);
  const manualUrl = `${api}/video-tracks/${initial.id}`;
  const untouched = initial.keyframes_json[1];

  const hidden = await json(
    await page.request.post(tracksUrl, {
      data: {
        label_class_id: background.id,
        status: "verified",
        interpolation: "hold",
        geometry_kind: "bbox",
        keyframes: [
          {
            frame: 4,
            bbox: [40, 12, 17, 20],
            mask_polygons: [
              [
                [41, 13],
                [52, 14],
                [49, 29],
              ],
            ],
          },
        ],
      },
    }),
  );
  await goToFrame(4);
  await expect(picker.locator(`option[value="${hidden.id}"]`)).toHaveCount(1);
  await picker.selectOption(hidden.id);
  const mask = workspace.getByLabel(
    `Segmentation mask 1 for track ${hidden.track_number}`,
    { exact: true },
  );
  await expect(mask).toHaveAttribute("points", "41,13 52,14 49,29");
  await classButton("Hide class Fixture masked animal").click();
  await expect(mask).toHaveCount(0);
  await expect(save).toBeDisabled();
  await expect(editor.getByRole("status")).toContainText(
    "Show the selected track",
  );
  await picker.selectOption(initial.id);
  await expect(picker.locator(`option[value="${hidden.id}"]`)).toHaveCount(0);
  await classButton("Solo class Fixture masked animal").click();
  await expect(classButton("Solo class Fixture masked animal")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(mask).toBeVisible();
  const selectedBox = workspace.locator(`rect[data-track-id="${initial.id}"]`);
  await expect(selectedBox).toHaveCount(0);
  await classButton("Solo class Fixture masked animal").click();
  await expect(mask).toHaveCount(0);
  await expect(selectedBox).toHaveAttribute("x", "8");

  await changeX.fill("13");
  await expect(selectedBox).toHaveAttribute("x", "13");
  await undo.click();
  await expect(changeX).toHaveValue("8");
  await expect(selectedBox).toHaveAttribute("x", "8");
  await redo.click();
  await expect(changeX).toHaveValue("13");
  await expect(selectedBox).toHaveAttribute("x", "13");
  await cancel.click();
  await expect(changeX).toHaveValue("8");
  expect(
    (await get(tracksUrl)).find(
      (track: { id: string }) => track.id === initial.id,
    ).revision,
  ).toBe(1);

  await changeX.fill("14");
  const update = waitFor("PUT", manualUrl);
  await save.click();
  const updated = await json(await update);
  expect(updated.revision).toBe(2);
  expect(updated.keyframes_json[0].bbox).toEqual([14, 7, 24, 19]);
  expect(updated.keyframes_json[1]).toEqual(untouched);
  await expect(undo).toBeDisabled();
  await expect(changeX).toHaveValue("14");

  await changeX.fill("17");
  const independent = await json(
    await page.request.put(manualUrl, {
      data: {
        base_revision: 2,
        label_class_id: primary.id,
        status: "verified",
        interpolation: updated.interpolation,
        keyframes: [
          { ...updated.keyframes_json[0], bbox: [16, 7, 24, 19] },
          untouched,
        ],
      },
    }),
  );
  expect(independent.revision).toBe(3);
  await expect(
    editor.getByText("A newer track revision is available.", { exact: false }),
  ).toBeVisible();
  await expect(changeX).toHaveValue("17");
  const stale = waitFor("PUT", manualUrl);
  await save.click();
  const conflict = await stale;
  expect(conflict.status()).toBe(409);
  expect(conflict.request().postDataJSON().base_revision).toBe(2);
  await expect(editor.getByRole("alert")).toContainText(
    "Video track revision conflict",
  );
  await expect(changeX).toHaveValue("17");
  await cancel.click();
  await expect(changeX).toHaveValue("16");
  await expect(editor.getByRole("alert")).toHaveCount(0);

  const exchange = page.getByTestId("video-track-exchange-panel");
  const exportLink = exchange.getByRole("link", {
    name: "Export active tracks",
  });
  const downloadEvent = page.waitForEvent("download");
  await exportLink.click();
  const download = await downloadEvent;
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  const bytes = await readFile(downloadPath!);
  const exported = JSON.parse(bytes.toString());
  function omitUnsetFields(keyframe: object) {
    return Object.fromEntries(
      Object.entries(keyframe).filter(([, value]) => value !== null),
    );
  }
  expect(exported.source_video_sha256).toBe(originalSha);
  expect(exported.tracks).toHaveLength(2);
  expect(
    exported.tracks.find(
      (track: { original_track_id: string }) =>
        track.original_track_id === hidden.id,
    ),
  ).toMatchObject({
    label_class_id: background.id,
    keyframes: hidden.keyframes_json.map(omitUnsetFields),
  });
  expect(
    exported.tracks.find(
      (track: { original_track_id: string }) =>
        track.original_track_id === initial.id,
    ),
  ).toMatchObject({
    label_class_id: primary.id,
    keyframes: independent.keyframes_json.map(omitUnsetFields),
  });

  await openWorkspace();
  await expect(picker.locator(`option[value="${hidden.id}"]`)).toHaveCount(1);
  await picker.selectOption(initial.id);
  await goToFrame(4);
  await expect
    .poll(actualPlayback)
    .toMatchObject({ loaded: true, width: 96, height: 64 });
  await expect(selectedBox).toHaveAttribute("x", "16");
  await expect(changeX).toHaveValue("16");
  await expect(mask).toBeVisible();
  const content = await page.request.get(`${videoUrl}/content`);
  expect(content.ok()).toBe(true);
  expect(sha(await content.body())).toBe(originalSha);
  const reopened = await get(tracksUrl);
  expect(
    reopened.find((track: { id: string }) => track.id === initial.id),
  ).toMatchObject(independent);
  expect(
    reopened.find((track: { id: string }) => track.id === hidden.id),
  ).toMatchObject(hidden);
  await writeFile(
    info.outputPath("manual-video-editor-evidence.json"),
    JSON.stringify(
      {
        surface,
        video: {
          id: video.id,
          sha256: originalSha,
          width: 96,
          height: 64,
          frames: 12,
          fps: 10,
        },
        track: {
          id: initial.id,
          from_rev: 1,
          saved_rev: 2,
          reopened_rev: 3,
          initial_bbox: [8, 7, 24, 19],
          final_bbox: [16, 7, 24, 19],
          untouched_keyframe: untouched,
        },
        hidden_track: {
          id: hidden.id,
          revision: hidden.revision,
          keyframes: hidden.keyframes_json,
        },
        stale_http_status: conflict.status(),
        export_sha256: sha(bytes),
      },
      null,
      2,
    ) + "\n",
  );
});
