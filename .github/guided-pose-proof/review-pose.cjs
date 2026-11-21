const { chromium } = require("playwright");
const { expect } = require("@playwright/test");
const { createHash } = require("node:crypto");
const { readFile, writeFile, realpath } = require("node:fs/promises");
const path = require("node:path");

(async () => {
  const [baselinePath, fixturePath, output, oraclePath] = process.argv.slice(2);
  const baseline = JSON.parse(await readFile(baselinePath, "utf8"));
  const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
  const truth = JSON.parse(await readFile(oraclePath, "utf8"));
  const api = process.env.REEFVISION_GUIDED_TEST_API;

  const profile = process.env.REEFVISION_RESEARCH_TEST_PROFILE;
  const endpoint = process.env.REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT;
  const artifactsDir = process.env.REEFVISION_SPATIAL_WEBVIEW2_ARTIFACTS_DIR;
  const surface = endpoint ? "tauri-webview2" : "ordinary source Chromium";
  if (endpoint)
    expect(endpoint).toMatch(
      /^ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[a-z0-9-]+$/i,
    );
  const browser = endpoint
    ? await chromium.connectOverCDP(endpoint, { isLocal: true, artifactsDir })
    : await chromium.launch();
  const receipt = {
    source_commit: baseline.source_commit,
    surface: baseline.surface,
    graph: baseline.graph,
    phases: [],
  };
  const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
  const write = () =>
    writeFile(
      path.join(output, "review-and-replay.json"),
      JSON.stringify(receipt, null, 2) + "\n",
    );
  try {
    const page = endpoint
      ? browser
          .contexts()
          .flatMap((context) => context.pages())
          .find((p) => /^https?:\/\/tauri\.localhost(?:\/|$)/.test(p.url()))
      : await browser.newPage({
          viewport: { width: 2300, height: 1250 },
          acceptDownloads: true,
        });
    expect(page).toBeTruthy();
    if (endpoint)
      await expect
        .poll(() => page.evaluate(() => "__TAURI_INTERNALS__" in window))
        .toBe(true);
    const web = endpoint
      ? new URL("/", page.url()).href
      : process.env.REEFVISION_GUIDED_TEST_WEB;
    page.setDefaultTimeout(12000);
    const project = fixture.project;
    const root = api + "/projects/" + project.id;
    async function read(response, status = 200) {
      const res = await response;
      expect(res.status(), await res.text()).toBe(status);
      return res.json();
    }
    const get = (url) => read(page.request.get(url));
    const runtime = await get(api + "/system/version");
    expect(runtime.application_version).toBe(
      process.env.REEFVISION_RESEARCH_TEST_VERSION,
    );
    expect(runtime.current_schema_revision).toBe(
      process.env.REEFVISION_RESEARCH_TEST_SCHEMA,
    );
    expect(runtime.safe_mode).toBe(false);
    expect(await realpath(runtime.data_dir)).toBe(await realpath(profile));
    expect(
      (
        await readFile(
          path.join(profile, ".reefvision-clean-install-acceptance"),
          "utf8",
        )
      ).trim(),
    ).toBe(fixture.profile_marker);
    expect(baseline.source_commit).toBe(fixture.source_commit);
    expect(baseline.project_id).toBe(project.id);
    expect(surface).toBe(baseline.surface);
    receipt.version = runtime.application_version;
    receipt.schema = runtime.current_schema_revision;
    expect(truth.frozen_evaluation.manifest_sha256).toBe(
      fixture.source_oracle_sha256,
    );
    const sourceTruth = truth.frozen_evaluation.manifest.sources.find(
      (s) => s.recording.id === fixture.test_video.id,
    );
    expect(sourceTruth.split).toBe("test");
    expect(sourceTruth.recording.sha256).toBe(fixture.test_video.sha256);
    receipt.held_out_truth_sha256 = truth.frozen_evaluation.manifest_sha256;

    await page.addInitScript(
      (appVersion) =>
        localStorage.setItem(
          "reefvision.onboarding.dismissed." + appVersion,
          "true",
        ),
      runtime.application_version,
    );
    async function openVideoAutomation() {
      await page.goto(web);
      await page
        .getByRole("button", { name: "Open " + project.name, exact: true })
        .click();
      await page
        .getByRole("tab", { name: "Video & automation", exact: true })
        .click();
    }
    await openVideoAutomation();
    const workflow = page.getByRole("tab", {
      name: "Workflow builder",
      exact: true,
    });
    const checked = page.getByLabel("Enable source-coordinate overlay", {
      exact: true,
    });
    const video = page
      .getByRole("heading", { name: "Managed videos", exact: true })
      .locator("..")
      .getByRole("combobox", { name: "Video", exact: true });
    const track = page.getByRole("combobox", {
      name: "Existing track",
      exact: true,
    });
    const detail = (id) => get(api + "/workflow-runs/" + id);
    const movement = page.getByRole("region", {
      name: "Temporal pose review",
      exact: true,
    });
    const active = page.getByRole("region", {
      name: "Pose Active Learning",
      exact: true,
    });
    const gateLabel = (id) =>
      api + "/workflow-node-runs/" + id + "/resume-review";
    const summary = (id) => get(api + "/video-tracks/" + id + "/pose-temporal");
    const jsonFile = (name, value) =>
      writeFile(path.join(output, name), JSON.stringify(value, null, 2) + "\n");

    async function waitToStop(id, label) {
      let state;
      await expect
        .poll(
          async () => {
            state = await detail(id);
            return state.run.status;
          },
          {
            timeout: 230000,
            intervals: [250, 500, 1000, 2000],
            message: label,
          },
        )
        .toMatch(/^(waiting_for_review|succeeded|failed|cancelled)$/);
      await jsonFile(id + "-" + label + ".json", state);
      return state;
    }
    async function showGate(gate) {
      const back = page.getByRole("button", {
        name: "Back to workflow review",
        exact: true,
      });
      if (await back.isVisible()) {
        await back.click();
      } else {
        await workflow.click();
      }
      const card = page
        .getByRole("heading", { name: "Recent runs", exact: true })
        .locator("..");
      await card
        .getByRole("button", {
          name:
            "waiting_for_review · " + baseline.graph.sha256.slice(0, 12) + "…",
          exact: true,
        })
        .first()
        .click();
      const node = page
        .getByRole("heading", { name: "Run inspection", exact: true })
        .locator("..")
        .locator("ol > li")
        .filter({ has: page.getByText(gate.node_id, { exact: true }) });
      await expect(
        node.getByRole("button", { name: "Resume after review", exact: true }),
      ).toBeVisible();
      return node;
    }
    async function resume(gate, expected) {
      const node = await showGate(gate);
      const request = page.waitForResponse(
        (r) =>
          r.url() === gateLabel(gate.id) && r.request().method() === "POST",
      );
      await node
        .getByRole("button", { name: "Resume after review", exact: true })
        .click();
      return read(request, expected);
    }
    async function verifyLinkedTrack(trackId) {
      await expect(video).toHaveValue(fixture.test_video.id);
      await expect(checked).toBeChecked();
      await expect(track).toHaveValue(trackId);
      await expect(
        page.getByRole("combobox", { name: "Saved template", exact: true }),
      ).toHaveValue("");
      await expect(
        movement.getByRole("heading", {
          name: "Repeated-landmark identity review",
          exact: true,
        }),
      ).toBeVisible();
    }
    async function browserExport(name, file) {
      const download = page.waitForEvent("download", { timeout: 30000 });
      await page.getByRole("link", { name, exact: true }).click();
      const dl = await download;
      const target = path.join(output, file);
      await dl.saveAs(target);
      const bytes = await readFile(target);
      expect(bytes.length).toBeGreaterThan(0);
      return {
        name: dl.suggestedFilename(),
        bytes: bytes.length,
        sha256: hash(bytes),
      };
    }
    async function loadTrainingPackage(state, part) {
      const artifact = state.artifacts.find(
        (a) => a.data_type === "results_package",
      );
      const training = state.artifacts.find(
        (a) => a.data_type === "training_result",
      );
      const model = state.artifacts.find(
        (a) => a.data_type === "model_reference",
      );
      const pose = state.artifacts.find((a) => a.data_type === "pose_tracks");
      const pkg = artifact.payload_json;
      expect(pkg.verification_valid).toBe(true);
      const response = await page.request.get(api + pkg.download_url);
      expect(response.ok()).toBe(true);
      const bytes = await response.body();
      expect(hash(bytes)).toBe(pkg.archive_sha256);
      expect(model.payload_json.model_sha256).toBe(
        training.payload_json.result_checkpoint_sha256,
      );
      expect(pose.payload_json.source_model_sha256).toBe(
        model.payload_json.model_sha256,
      );
      const checkpoint = await readFile(
        path.join(profile, training.payload_json.result_checkpoint_path),
      );
      expect(hash(checkpoint)).toBe(model.payload_json.model_sha256);
      const registered = await get(
        api + "/models/" + model.payload_json.model_id,
      );
      expect(
        hash(await readFile(path.join(profile, registered.managed_path))),
      ).toBe(model.payload_json.model_sha256);
      const sourceRun = await get(
        api + "/training-runs/" + training.payload_json.training_run_id,
      );
      expect(sourceRun.registered_model_id).toBe(registered.id);
      expect(model.payload_json.source_training_run_id).toBe(sourceRun.id);
      expect(registered.display_name).toContain(
        baseline.guided_configuration.model_display_name,
      );
      const expectedDevice =
        process.env.REEFVISION_POSE_EXPECTED_DEVICE || "cuda";
      expect(training.payload_json.device).toBe(expectedDevice);
      const trainingJob = await get(
        api + "/jobs/" + training.payload_json.training_job_id,
      );
      const trackingJob = await get(
        api + "/jobs/" + pose.payload_json.tracking_job_id,
      );
      expect(trainingJob.status).toBe("succeeded");
      expect(trackingJob.status).toBe("succeeded");
      expect(trackingJob.result_json.device).toBe(expectedDevice);
      expect(trackingJob.result_json.pose_input_hashes).toMatchObject({
        video_sha256: fixture.test_video.sha256,
        model_sha256: registered.sha256,
      });
      part.runtime_device = expectedDevice;
      part.registration_relation = {
        training_run_id: sourceRun.id,
        model_id: sourceRun.registered_model_id,
        model_original_run_id: model.payload_json.model_source_training_run_id,
        display_name: registered.display_name,
        original_registered_bytes_sha256: registered.sha256,
      };
      part.job_timing = {
        training: {
          id: trainingJob.id,
          started_at: trainingJob.started_at,
          completed_at: trainingJob.completed_at,
        },
        inference: {
          id: trackingJob.id,
          started_at: trackingJob.started_at,
          completed_at: trackingJob.completed_at,
        },
      };
      part.training = {
        training_id: training.payload_json.training_run_id,
        job_id: training.payload_json.training_job_id,
        training_dataset_id: training.payload_json.pose_training_dataset_id,
        validation_dataset_id: training.payload_json.pose_validation_dataset_id,
        split_manifest_sha256: training.payload_json.split_manifest_sha256,
        device: training.payload_json.device,
        initialization: training.payload_json.initialization_mode,
        checkpoint_sha256: model.payload_json.model_sha256,
        registered_model_id: registered.id,
        verified_package_sha256: pkg.archive_sha256,
        package_bytes: bytes.length,
      };
      part.inference = {
        job_id: pose.payload_json.tracking_job_id,
        artifact_id: pose.id,
        artifact_sha256: pose.payload_sha256,
        held_out_video: pose.payload_json.video_id,
        held_out_sha256: pose.payload_json.video_sha256,
        track_ids: pose.payload_json.track_ids,
        tracks: pose.payload_json.count,
      };
      await write();
    }

    async function inReview(state, part) {
      let gate = state.nodes.find(
        (n) =>
          n.node_type === "pose_review_gate" &&
          n.status === "waiting_for_review",
      );
      expect(gate).toBeTruthy();
      const readiness = gate.result_json.review.review_readiness;
      const [trackId] = readiness.track_ids;
      expect(trackId).toBeTruthy();
      const before = await summary(trackId);
      part.temporal_before = {
        observations: before.observations.length,
        automatic_breaks: readiness.unverified_identity_break_ids.length,
        unresolved: readiness.unreviewed_unresolved_observation_ids.length,
      };
      if (!readiness.ready && before.corrections.length === 0) {
        const blocked = await resume(gate, 400);
        expect(blocked.detail).toContain("Pose review cannot be approved");
        part.pre_review_refusal = blocked.detail;
        await write();
      }
      const step = await showGate(gate);
      part.training.browser_download = await browserExport(
        "Download verified training results",
        part.run_id + "-training-results.zip",
      );
      expect(part.training.browser_download.sha256).toBe(
        part.training.verified_package_sha256,
      );
      await step
        .getByRole("button", {
          name: "Review temporal associations",
          exact: true,
        })
        .click();
      await verifyLinkedTrack(trackId);
      part.temporal_shortcut = {
        video_id: await video.inputValue(),
        track_id: await track.inputValue(),
      };

      const stillUnreviewed =
        readiness.unreviewed_unresolved_observation_ids.filter(
          (id) =>
            !before.association_decisions.some(
              (d) =>
                d.observation_id === id &&
                d.verification_state !== "unreviewed",
            ),
        );
      for (const id of stillUnreviewed) {
        const observation = before.observations.find((o) => o.id === id);
        const slider = page
          .getByRole("heading", {
            name: "Source-coordinate overlay",
            exact: true,
          })
          .locator("..")
          .getByRole("slider");
        const current = Number(await slider.inputValue());
        const direction =
          observation.frame_index >= current
            ? "Next pose frame"
            : "Previous pose frame";
        for (
          let f = current, attempts = 0;
          f !== observation.frame_index && attempts < 26;
          attempts++
        ) {
          await movement
            .getByRole("button", { name: direction, exact: true })
            .click();
          f = Number(await slider.inputValue());
        }
        expect(Number(await slider.inputValue())).toBe(observation.frame_index);
        const target = movement.getByRole("combobox", {
          name:
            "Temporal identity for " +
            observation.semantic_label +
            " " +
            (observation.occurrence_index + 1),
          exact: true,
        });
        const row = target.locator("../..");
        const response = page.waitForResponse(
          (r) =>
            r.url() ===
              api +
                "/pose-landmark-observations/" +
                id +
                "/association-corrections" && r.request().method() === "POST",
        );
        await row
          .getByRole("button", { name: "Mark unresolved", exact: true })
          .click();
        const corrected = await read(response);
        expect(corrected.association_state).toBe("unresolved");
        expect(corrected.verification_state).not.toBe("unreviewed");
      }
      const unverified = before.identity_breaks.filter(
        (b) => !b.human_verified,
      );
      if (unverified.length)
        await movement
          .getByText("Identity break review", { exact: true })
          .click();
      for (const item of unverified) {
        const row = movement
          .locator("details .annotation-selection-row")
          .filter({
            has: page.getByText(
              item.predecessor_landmark_track_id.slice(0, 8) +
                " · frame " +
                item.break_after_frame,
              { exact: true },
            ),
          });
        const response = page.waitForResponse(
          (r) =>
            r.url() ===
              api + "/pose-landmark-identity-breaks/" + item.id + "/review" &&
            r.request().method() === "POST",
        );
        await row
          .getByRole("button", { name: "Confirm break", exact: true })
          .click();
        const result = await read(response);
        expect(result.human_verified).toBe(true);
      }
      const after = await summary(trackId);
      expect(after.identity_breaks.every((b) => b.human_verified)).toBe(true);
      part.temporal_after = {
        correction_ids: after.corrections.map((row) => row.id),
        verified_breaks: after.identity_breaks.length,
      };
      part.pose_csv = await browserExport(
        "Export pose CSV",
        part.run_id + "-pose.csv",
      );
      part.pose_audit = await browserExport(
        "Export pose audit JSON",
        part.run_id + "-pose-audit.json",
      );
      await write();
      const resumed = await resume(gate, 202);
      expect(resumed.id).toBe(part.run_id);
      state = await waitToStop(resumed.id, "second-gate");
      part.after_temporal_review = state.run.status;
      part.reviewed_artifact = state.artifacts.find(
        (a) => a.data_type === "reviewed_pose_tracks",
      )?.payload_sha256;
      await write();
      return state;
    }

    async function approveActiveLearning(state, part) {
      const gate = state.nodes.find(
        (n) =>
          n.node_type === "pose_active_learning_review_gate" &&
          n.status === "waiting_for_review",
      );
      expect(gate).toBeTruthy();
      const roundArtifact = state.artifacts.find(
        (a) => a.data_type === "pose_active_learning_round",
      );
      const roundId = roundArtifact.payload_json.round_id;
      const candidatesUrl =
        api + "/pose-active-learning-rounds/" + roundId + "/candidates";
      const blocked = await resume(gate, 400);
      expect(blocked.detail).toContain("not retraining-ready");
      part.pre_acquisition_refusal = blocked.detail;
      const step = await showGate(gate);
      await step
        .getByRole("button", {
          name: "Open pose acquisition review",
          exact: true,
        })
        .click();
      await verifyLinkedTrack(part.inference.track_ids[0]);
      const selectedVideo = await get(api + "/videos/" + fixture.test_video.id);
      if (!selectedVideo.frame_directory_path) {
        const extraction = page.waitForResponse(
          (r) =>
            r.url().endsWith("/extract") && r.request().method() === "POST",
        );
        await page
          .getByLabel("Extract every N frames", { exact: true })
          .fill("1");
        await page
          .getByRole("button", { name: "Extract review frames", exact: true })
          .click();
        const result = await extraction;
        expect(result.ok(), await result.text()).toBe(true);
        await expect
          .poll(
            async () =>
              (await get(api + "/videos/" + fixture.test_video.id))
                .frame_directory_path,
            { timeout: 40000 },
          )
          .toBeTruthy();
      }
      const rounds = await get(
        root + "/pose-active-learning-rounds?video_id=" + fixture.test_video.id,
      );
      expect(rounds.some((r) => r.id === roundId)).toBe(true);
      await expect(
        active.getByRole("combobox", {
          name: "Pose Active Learning round",
          exact: true,
        }),
      ).toHaveValue(roundId);
      part.acquisition_shortcut = {
        video_id: await video.inputValue(),
        track_id: await track.inputValue(),
        round_id: roundId,
      };
      const candidates = await get(candidatesUrl);
      const pending = candidates.filter(
        (c) => !["verified", "skipped"].includes(c.review_status),
      );
      const fulfilled = candidates.find((c) => c.review_status === "verified");
      const reviewed = fulfilled || pending[0];
      expect(reviewed).toBeTruthy();
      if (!fulfilled) {
        const review = active.getByTestId("pose-al-candidate-" + reviewed.id);
        await review
          .getByRole("button", {
            name: "Review in Pose Annotation Editor",
            exact: true,
          })
          .click();
        const exactFrame = page.locator(
          'image[href$="/frames/' + reviewed.focus_frame + '"]',
        );
        const canvas = page
          .getByRole("img", { name: "Pose annotation canvas", exact: true })
          .filter({ has: exactFrame });
        await expect(canvas).toBeVisible();
        await expect(
          review.getByText(/Saving the reviewed pose verifies this candidate/),
        ).toBeVisible();
        const truth = sourceTruth.frames.find(
          (f) => f.frame_index === reviewed.focus_frame,
        );
        expect(truth.target_points).toHaveLength(2);
        part.landmark_view = [];
        for (const point of truth.target_points) {
          const label = point.landmark_id === "jaw-a" ? "Jaw A 1" : "Jaw B 1";

          const circle = canvas.locator('circle[aria-label="' + label + '"]');
          await circle.click();
          await expect(
            page.getByTestId("selected-landmark-occurrence"),
          ).toBeVisible();
          await circle.scrollIntoViewIfNeeded();
          const locate = () =>
            circle.evaluate((node, point) => {
              const matrix = node.getScreenCTM();
              const a = new DOMPoint(
                node.cx.baseVal.value,
                node.cy.baseVal.value,
              ).matrixTransform(matrix);
              const b = new DOMPoint(point.x, point.y).matrixTransform(matrix);
              const { x, y, width, height } =
                node.ownerSVGElement.getBoundingClientRect();
              const target = document.elementFromPoint(b.x, b.y);
              return [
                a.x,
                a.y,
                b.x,
                b.y,
                {
                  x,
                  y,
                  width,
                  height,
                  scale: matrix.a,
                  actualBefore: [node.cx.baseVal.value, node.cy.baseVal.value],
                  targetHitsCanvas: node.ownerSVGElement.contains(target),
                  targetHitsInspector: Boolean(
                    target?.closest(".rv-workbench-inspector"),
                  ),
                  viewport: [
                    window.innerWidth,
                    window.innerHeight,
                    window.devicePixelRatio,
                  ],
                },
              ];
            }, point);
          const initial = await locate();
          const inspectorCollapsed = initial[4].targetHitsInspector;
          if (inspectorCollapsed) {
            await page
              .getByRole("button", { name: "Hide inspector", exact: true })
              .click();
            await circle.scrollIntoViewIfNeeded();
          }
          const coords = inspectorCollapsed ? await locate() : initial;
          expect(coords[4].targetHitsCanvas).toBe(true);
          part.landmark_view.push({
            landmark_id: point.landmark_id,
            inspector_collapsed_for_pointer: inspectorCollapsed,
            target_hit_canvas_before: initial[4].targetHitsCanvas,
            target_hits_canvas: coords[4].targetHitsCanvas,
            viewport: coords[4].viewport,
          });
          await page.mouse.move(coords[0], coords[1]);
          await page.mouse.down();
          await page.mouse.move(coords[2], coords[3], { steps: 5 });
          await page.mouse.up();
          await jsonFile(
            part.run_id +
              "-pose-pointer-" +
              label.replaceAll(" ", "-") +
              ".json",
            {
              desired: point,
              initial,
              coords,
              after: [
                Number(await circle.getAttribute("cx")),
                Number(await circle.getAttribute("cy")),
              ],
            },
          );
          expect(
            Math.abs(Number(await circle.getAttribute("cx")) - point.x),
          ).toBeLessThan(0.55);
          expect(
            Math.abs(Number(await circle.getAttribute("cy")) - point.y),
          ).toBeLessThan(0.55);
        }
        const verified = page.waitForResponse(
          (r) =>
            r.url() ===
              api +
                "/pose-active-learning-candidates/" +
                reviewed.id +
                "/review" && r.request().method() === "PUT",
        );
        await page
          .getByRole("button", { name: "Save pose", exact: true })
          .click();
        expect((await read(verified)).review_status).toBe("verified");
        part.reviewed_reference = {
          candidate_id: reviewed.id,
          frame: reviewed.focus_frame,
          declared_source_pixels: truth.target_points,
        };
      }
      for (const candidate of pending.filter((c) => c.id !== reviewed.id)) {
        const response = page.waitForResponse(
          (r) =>
            r.url() ===
              api +
                "/pose-active-learning-candidates/" +
                candidate.id +
                "/review" && r.request().method() === "PUT",
        );
        await active
          .getByTestId("pose-al-candidate-" + candidate.id)
          .getByRole("button", { name: "Skip candidate", exact: true })
          .click();
        expect((await read(response)).review_status).toBe("skipped");
      }
      part.active_learning = (await get(candidatesUrl)).map((c) => ({
        id: c.id,
        status: c.review_status,
      }));
      await write();
      await resume(gate, 202);
      const done = await waitToStop(part.run_id, "after-active-learning");
      part.final_status = done.run.status;
      if (done.run.status === "succeeded") {
        const posePackage = done.artifacts.find(
          (a) => a.data_type === "pose_training_package",
        );
        const poseBytes = await readFile(
          path.join(profile, posePackage.payload_json.managed_path),
        );
        expect(hash(poseBytes)).toBe(posePackage.payload_json.bundle_sha256);
        expect(poseBytes.length).toBe(posePackage.payload_json.size_bytes);
        const downloaded = await page.request.get(
          api +
            "/pose-training-datasets/" +
            posePackage.payload_json.dataset_id +
            "/native-package",
        );
        expect(downloaded.ok(), await downloaded.text()).toBe(true);
        expect(hash(await downloaded.body())).toBe(
          posePackage.payload_json.bundle_sha256,
        );
        part.native_pose_package = {
          dataset_id: posePackage.payload_json.dataset_id,
          size_bytes: poseBytes.length,
          sha256: hash(poseBytes),
          artifact_id: posePackage.id,
          lossy: posePackage.payload_json.lossy,
        };
        const browserDownload = await browserExport(
          "Download reviewed native poses",
          part.run_id + "-poses.zip",
        );
        expect(browserDownload.sha256).toBe(part.native_pose_package.sha256);
        part.native_pose_package.browser_download = browserDownload;
      }
      part.final_error = done.run.error_message;
      part.final_artifacts = done.artifacts.map((a) => ({
        type: a.data_type,
        id: a.id,
        sha256: a.payload_sha256,
      }));
      await write();
      return done;
    }

    const first = baseline.runs[0];
    let state = await detail(first.id);
    const part = {
      run_id: first.id,
      parent_job_id: first.job_id,
      status_on_reopen: state.run.status,
    };
    receipt.phases.push(part);
    await write();
    await loadTrainingPackage(state, part);
    if (
      state.nodes.some(
        (n) =>
          n.node_type === "pose_review_gate" &&
          n.status === "waiting_for_review",
      )
    )
      state = await inReview(state, part);
    if (
      state.nodes.some(
        (n) =>
          n.node_type === "pose_active_learning_review_gate" &&
          n.status === "waiting_for_review",
      )
    )
      state = await approveActiveLearning(state, part);
    expect(state.run.status, state.run.error_message).toBe("succeeded");
    await workflow.click();
    const revision = page
      .getByRole("listitem")
      .filter({ hasText: baseline.graph.name });
    const pending = page.waitForResponse(
      (r) =>
        r.url() === root + "/workflow-runs" && r.request().method() === "POST",
    );
    await revision
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const second = await read(pending, 202);
    expect(second.id).not.toBe(first.id);
    expect(second.graph_sha256).toBe(baseline.graph.sha256);
    state = await waitToStop(second.id, "replay-first-stop");
    const replay = {
      run_id: second.id,
      parent_job_id: second.job_id,
      status_on_first_stop: state.run.status,
      error: state.run.error_message,
      failed_nodes: state.nodes.filter((n) => n.status === "failed"),
    };
    receipt.phases.push(replay);
    await write();
    expect(state.run.status, state.run.error_message).toBe(
      "waiting_for_review",
    );
    await loadTrainingPackage(state, replay);
    state = await inReview(state, replay);
    if (
      state.nodes.some(
        (n) =>
          n.node_type === "pose_active_learning_review_gate" &&
          n.status === "waiting_for_review",
      )
    )
      state = await approveActiveLearning(state, replay);
    expect(state.run.status, state.run.error_message).toBe("succeeded");
    expect(replay.registration_relation.training_run_id).not.toBe(
      part.registration_relation.training_run_id,
    );
    const reusedIdenticalBytes =
      replay.registration_relation.original_registered_bytes_sha256 ===
      part.registration_relation.original_registered_bytes_sha256;
    expect(
      replay.registration_relation.model_id ===
        part.registration_relation.model_id,
    ).toBe(reusedIdenticalBytes);
    receipt.registration_comparison = {
      explicit_display_name: baseline.guided_configuration.model_display_name,
      reused_identical_bytes: reusedIdenticalBytes,
    };
  } finally {
    await write();
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
