const { chromium } = require("playwright");
const { expect } = require("@playwright/test");
const { createHash } = require("node:crypto");
const { readFile, writeFile, realpath } = require("node:fs/promises");
const path = require("node:path");

(async () => {
  const [fixturePath, output] = process.argv.slice(2);
  const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
  const profile = process.env.REEFVISION_RESEARCH_TEST_PROFILE;
  const api = process.env.REEFVISION_GUIDED_TEST_API;

  const sourceCommit = fixture.source_commit;
  expect(sourceCommit).toMatch(/^[a-f0-9]{40}$/);
  expect(api).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/api\/v1$/);
  expect(
    (
      await readFile(
        path.join(profile, ".reefvision-clean-install-acceptance"),
        "utf8",
      )
    ).trim(),
  ).toBe(fixture.profile_marker);
  const project = fixture.project;
  const root = api + "/projects/" + project.id;
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
  const record = {
    source_commit: sourceCommit,
    surface,
    project_id: project.id,
    runs: [],
  };
  const write = async () =>
    await writeFile(
      path.join(output, "pose-predecessor-proof.json"),
      JSON.stringify(record, null, 2) + "\n",
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
    async function read(response, status = 200) {
      const r = await response;
      expect(r.status(), await r.text()).toBe(status);
      return r.json();
    }
    const get = (url) => read(page.request.get(url));
    const version = await get(api + "/system/version");
    expect(version.application_version).toBe(
      process.env.REEFVISION_RESEARCH_TEST_VERSION,
    );
    expect(version.current_schema_revision).toBe(
      process.env.REEFVISION_RESEARCH_TEST_SCHEMA,
    );
    expect(version.expected_schema_revision).toBe(
      version.current_schema_revision,
    );
    expect(version.safe_mode).toBe(false);
    expect(await realpath(version.data_dir)).toBe(await realpath(profile));
    record.version = version.application_version;
    record.schema = version.current_schema_revision;
    await page.addInitScript(
      (appVersion) =>
        localStorage.setItem(
          "reefvision.onboarding.dismissed." + appVersion,
          "true",
        ),
      version.application_version,
    );
    async function open() {
      await page.goto(web);
      await page
        .getByRole("button", { name: "Open " + project.name, exact: true })
        .click();
      await page
        .getByRole("tab", { name: "Video & automation", exact: true })
        .click();
      await page
        .getByRole("tab", { name: "Workflow builder", exact: true })
        .click();
      await expect(
        page.getByRole("heading", {
          name: "Visual workflow editor",
          exact: true,
        }),
      ).toBeVisible();
    }
    await open();
    const templateId = "reefpose-native-reviewed-workflow";
    await page
      .getByRole("combobox", { name: "Template", exact: true })
      .selectOption(templateId);
    const train = fixture.datasets.find((row) => row.name === "recording-101");
    const validation = fixture.datasets.find(
      (row) => row.name === "recording-203",
    );
    async function selectSource(label, visibleOption, expectedId) {
      const picker = page.getByRole("combobox", { name: label, exact: true });
      const option = picker.getByRole("option", { name: visibleOption });
      await expect(option).toHaveAttribute("value", expectedId);
      await picker.selectOption(await option.getAttribute("value"));
    }
    await selectSource("Frozen training dataset", /^recording-101\b/, train.id);
    await selectSource(
      "Frozen validation dataset",
      /^recording-203\b/,
      validation.id,
    );
    await selectSource(
      "Held-out recording",
      fixture.test_video.original_filename,
      fixture.test_video.id,
    );
    function configure(id) {
      return page
        .locator('[data-node-id="' + id + '"]')
        .getByRole("button", { name: "Configure", exact: true })
        .click();
    }
    const inspector = page
      .getByRole("heading", { name: "Selected node parameters", exact: true })
      .locator("..");
    const device = process.env.REEFVISION_POSE_EXPECTED_DEVICE || "cpu";
    const modelName = "Generated guided ReefPose benchmark";
    await configure("train");
    await expect(inspector.getByText("train", { exact: true })).toBeVisible();
    await inspector
      .getByRole("combobox", { name: "Device", exact: true })
      .selectOption(device);
    await inspector
      .getByRole("combobox", { name: "Precision", exact: true })
      .selectOption("fp32");
    for (const [label, value] of Object.entries({
      Epochs: "1",
      "Batch size": "2",
      "Data workers": "0",
      "Input height": "64",
      "Input width": "64",
      "Base channels": "4",
      "Feature pyramid channels": "8",
      random_seed: "71",
    })) {
      await inspector.getByLabel(label, { exact: true }).fill(value);
    }
    await configure("register");
    await inspector.getByLabel("display_name", { exact: true }).fill(modelName);
    await configure("infer");
    await inspector
      .getByRole("combobox", { name: "Inference device", exact: true })
      .selectOption(device);
    await inspector
      .getByLabel("Pose confidence threshold", { exact: true })
      .fill("0");
    const advanced = page
      .getByText("Advanced: edit workflow JSON directly", { exact: true })
      .locator("..");
    await expect(advanced).not.toHaveAttribute("open", "");
    const planning = page.waitForResponse(
      (r) =>
        r.url() === root + "/workflow-graphs/plan" &&
        r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Plan", exact: true }).click();
    const plannedResponse = await planning;
    const plan = await read(plannedResponse);
    const draft = plannedResponse.request().postDataJSON();
    const graph = draft.graph ?? draft;
    expect(graph.graph_id).toBe(templateId);
    expect(graph.nodes).toHaveLength(14);
    const input = (id) =>
      graph.nodes.find((node) => node.node_id === id).parameters;
    expect(input("dataset")).toMatchObject({
      dataset_id: train.id,
      manifest_sha256: train.manifest_sha256,
    });
    expect(input("validation")).toMatchObject({
      dataset_id: validation.id,
      manifest_sha256: validation.manifest_sha256,
    });
    expect(input("recording")).toMatchObject({
      video_id: fixture.test_video.id,
      video_sha256: fixture.test_video.sha256,
    });
    expect(input("train")).toMatchObject({
      device,
      require_validation_dataset: true,
    });
    expect(Number(input("train").random_seed)).toBe(71);
    expect(input("register").display_name).toBe(modelName);
    expect(input("infer")).toMatchObject({
      device,
      confidence: 0,
      require_held_out_recording: true,
    });
    record.guided_configuration = {
      template_id: templateId,
      node_types: graph.nodes.map((node) => node.node_type),
      train: input("dataset"),
      validation: input("validation"),
      held_out: input("recording"),
      device,
      model_display_name: modelName,
      used_advanced_graph_for_composition: false,
    };
    await writeFile(
      path.join(output, "selected-graph.json"),
      JSON.stringify(graph, null, 2) + "\n",
    );
    record.plan = {
      valid: plan.valid,
      executable: plan.executable,
      issues: plan.issues,
    };
    await write();
    expect(plan.valid, JSON.stringify(plan.issues)).toBe(true);
    expect(plan.executable, JSON.stringify(plan.issues)).toBe(true);
    const saving = page.waitForResponse(
      (r) =>
        r.url() === root + "/workflow-graphs" &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Save revision", exact: true })
      .click();
    const saved = await read(saving, 201);
    expect(saved.graph_key).toBe(graph.graph_id);
    record.graph = {
      id: saved.id,
      key: saved.graph_key,
      name: saved.name,
      sha256: saved.graph_sha256,
      revision: saved.revision,
    };
    await write();

    async function openRun() {
      await open();
      const revision = page
        .getByRole("listitem")
        .filter({ hasText: graph.name });
      const queued = page.waitForResponse(
        (r) =>
          r.url() === root + "/workflow-runs" &&
          r.request().method() === "POST",
      );
      await revision
        .getByRole("button", { name: "Run saved revision", exact: true })
        .click();
      const run = await read(queued, 202);
      expect(run.workflow_graph_record_id).toBe(saved.id);
      expect(run.graph_sha256).toBe(saved.graph_sha256);
      return run;
    }
    async function waitUntilStopped(run, phase) {
      const url = api + "/workflow-runs/" + run.id;
      let detail;
      await expect
        .poll(
          async () => {
            detail = await get(url);
            return detail.run.status;
          },
          {
            timeout: 230000,
            intervals: [250, 500, 1000, 2000],
            message: phase,
          },
        )
        .toMatch(/^(waiting_for_review|succeeded|failed|cancelled)$/);
      await writeFile(
        path.join(output, run.id + "-" + phase + ".json"),
        JSON.stringify(detail, null, 2) + "\n",
      );
      return detail;
    }
    const run = await openRun();
    const state = await waitUntilStopped(run, "first-stop");
    const evidence = {
      id: run.id,
      job_id: run.job_id,
      state: state.run.status,
      error: state.run.error_message,
      nodes: state.nodes.map((n) => ({
        id: n.id,
        key: n.node_id,
        status: n.status,
        error: n.error_message,
      })),
      artifacts: state.artifacts.map((a) => ({
        id: a.id,
        type: a.data_type,
        sha256: a.payload_sha256,
        port: a.producer_port_id,
        payload: a.payload_json,
      })),
    };
    record.runs.push(evidence);
    await write();
    expect(state.run.status, state.run.error_message).toBe(
      "waiting_for_review",
    );
    const model = state.artifacts.find(
      (a) => a.data_type === "registered_model",
    );
    const outputPose = state.artifacts.find(
      (a) => a.data_type === "pose_tracks",
    );
    expect(outputPose.payload_json).toMatchObject({
      provider_name: "reefpose",
      video_id: fixture.test_video.id,
      video_sha256: fixture.test_video.sha256,
    });
    expect(outputPose.payload_json.count).toBeGreaterThan(0);
    const registered = await get(
      api + "/models/" + outputPose.payload_json.source_model_id,
    );
    expect(registered.sha256).toBe(outputPose.payload_json.source_model_sha256);
    expect(registered.project_id).toBe(project.id);
    record.registration = registered;
    expect(
      state.artifacts.some((a) => a.data_type === "reviewed_pose_tracks"),
    ).toBe(false);
    await expect(
      page.getByText("This run is safely paused.", { exact: false }),
    ).toBeVisible();
    await page.screenshot({
      path: path.join(output, "first-scientist-gate.png"),
    });
  } finally {
    await write();
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
