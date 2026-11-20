import { readFile, writeFile } from "node:fs/promises";

import { expect } from "@playwright/test";
import { test } from "./spatialDesktop";

test.use({ trace: "off", screenshot: "off", video: "off" });

test("assigns blinded reviews, adjudicates, and replays the sealed agreement", async ({
  desktop,
}, info) => {
  test.setTimeout(95_000);
  const { page, api, web, surface } = desktop;
  const title = "Reviewer Lab synthetic sources";
  const roundName = "Independent suitability";
  const firstReason = "First assessor saw a usable original";
  const secondReason = "Second assessor found insufficient visibility";
  const resolvedReason = "Retain the pair and mark suitability uncertain";
  await page.addInitScript(() => {
    localStorage.setItem("reefvision.onboarding.dismissed.1.4.0", "true");
    localStorage.setItem("reefvision.onboarding.dismissed.1.5.0", "true");
  });

  const created = await page.request.post(api + "/projects", {
    data: { name: title, template: "blank" },
  });
  expect(created.status()).toBe(201);
  const { id: projectId } = (await created.json()) as { id: string };
  const project = api + "/projects/" + projectId;
  await page.goto(web);
  const names = ["review-a.png", "review-b.png"] as const;
  const imageIds: string[] = [];
  for (const [index, name] of names.entries()) {
    const base64 = await page.evaluate((offset) => {
      const canvas = document.createElement("canvas");
      canvas.width = 100 + offset;
      canvas.height = 80;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = "#244f60";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#b79870";
      ctx.fillRect(30, 25, 40, 30);
      return canvas.toDataURL("image/png").split(",")[1];
    }, index);
    const imported = await page.request.post(project + "/imports/images", {
      multipart: {
        files: {
          name,
          mimeType: "image/png",
          buffer: Buffer.from(base64, "base64"),
        },
        relative_paths: name,
      },
    });
    expect(imported.status()).toBe(200);
    imageIds.push((await imported.json()).successful[0].image_id as string);
  }
  const queueResponse = await page.request.post(project + "/review-queues", {
    data: {},
  });
  expect(queueResponse.status()).toBe(201);
  const { id: queueId } = (await queueResponse.json()) as { id: string };
  const itemResponse = await page.request.get(
    api + "/review-queues/" + queueId + "/items",
  );
  expect(itemResponse.ok()).toBe(true);
  const queueItems = (await itemResponse.json()).items as Array<{
    id: string;
    image_id: string;
  }>;
  const queueItem = queueItems.find((item) => item.image_id === imageIds[0])!;

  async function openLab() {
    await page.goto(web);
    await page.getByRole("button", { name: "Open " + title }).click();
    await page.getByRole("tab", { name: "Review", exact: true }).click();
    await page.getByRole("tab", { name: "Reviewer lab", exact: true }).click();
  }

  await openLab();
  const lab = page.getByRole("region", { name: "Reviewer lab", exact: true });
  const keyField = lab.getByLabel("New local role key", { exact: true });
  async function readKey() {
    const key = await keyField.inputValue();
    if (!/^[0-9a-f]{64}$/.test(key))
      throw new Error("Expected one new local credential");
    await lab.getByRole("button", { name: "Dismiss key", exact: true }).click();
    return key;
  }
  await lab.getByLabel("Local manager name").fill("Fixture Manager");
  await lab.getByRole("button", { name: "Create local manager" }).click();
  const managerKey = await readKey();

  const participants: Array<{ name: string; role: string; key: string }> = [];
  for (const [name, role] of [
    ["Fixture Reviewer A", "reviewer"],
    ["Fixture Reviewer B", "reviewer"],
    ["Fixture Adjudicator", "adjudicator"],
  ]) {
    await lab.getByLabel("Participant name").fill(name);
    await lab.getByRole("combobox", { name: /^Local role/ }).selectOption(role);
    await lab.getByRole("button", { name: "Issue local role" }).click();
    participants.push({ name, role, key: await readKey() });
  }
  const end = () =>
    lab.getByRole("button", { name: "End local session" }).click();
  async function signIn(key: string) {
    try {
      await lab.getByLabel("Local role key", { exact: true }).fill(key);
    } catch {
      throw new Error("Could not enter the local session key");
    }
    await lab.getByRole("button", { name: "Open local session" }).click();
    await expect(
      lab.getByRole("region", { name: "Active local review session" }),
    ).toBeVisible();
  }
  const chooseRound = () =>
    lab.getByLabel(/^Review round/).selectOption({ label: roundName });
  await lab.getByLabel("Round title").fill(roundName);
  await lab
    .getByLabel("Review criterion")
    .fill("Check visibility for this synthetic fixture.");
  await lab
    .getByLabel("First reviewer")
    .selectOption({ label: participants[0].name });
  await lab
    .getByLabel("Second reviewer")
    .selectOption({ label: participants[1].name });
  await lab
    .getByLabel(/^Adjudicator/)
    .selectOption({ label: participants[2].name });
  await lab.getByLabel("Source collection").selectOption(queueId);
  await lab.getByLabel("Original to assign").selectOption(queueItem.id);
  await lab.getByRole("button", { name: "Add original" }).click();
  await lab.getByLabel("Source collection").selectOption("");
  await lab.getByLabel("Original to assign").selectOption(imageIds[1]);
  await lab.getByRole("button", { name: "Add original" }).click();
  await lab.getByRole("button", { name: "Assign blinded reviews" }).click();
  const round = lab.getByRole("region", { name: "Selected review round" });
  await expect(round.getByRole("heading", { name: roundName })).toBeVisible();
  await expect(
    round.getByRole("button", { name: "Seal agreement report" }),
  ).toBeDisabled();
  await end();

  for (const [index, reviewer] of participants.slice(0, 2).entries()) {
    await signIn(reviewer.key);
    await chooseRound();
    await expect(
      round.getByRole("img", { name: "Original review-a.png" }),
    ).toBeVisible();
    await expect(
      round.getByText(index ? firstReason : secondReason),
    ).toHaveCount(0);
    await round
      .getByLabel("Independent decision")
      .selectOption(index ? "unusable" : "usable");
    await round
      .getByLabel("Decision reason")
      .fill(index ? secondReason : firstReason);
    await round
      .getByRole("button", { name: "Commit independent decision" })
      .click();
    await expect(round.getByText(/Your committed review/)).toBeVisible();
    await expect(
      round.getByText(index ? firstReason : secondReason),
    ).toHaveCount(0);
    await round
      .getByLabel("Assigned original")
      .selectOption({ label: names[1] });
    await round.getByLabel("Independent decision").selectOption("usable");
    await round
      .getByLabel("Decision reason")
      .fill("Independent agreement on source B");
    await round
      .getByRole("button", { name: "Commit independent decision" })
      .click();
    await expect(round.getByText(/Your committed review/)).toBeVisible();
    await end();
  }

  await signIn(participants[2].key);
  await chooseRound();
  await expect(round.getByText(firstReason, { exact: false })).toBeVisible();
  await expect(round.getByText(secondReason, { exact: false })).toBeVisible();
  await round.getByLabel("Adjudication decision").selectOption("uncertain");
  await round.getByLabel("Decision reason").fill(resolvedReason);
  await round.getByRole("button", { name: "Commit adjudication" }).click();
  await expect(round.getByText(/Adjudication committed/)).toBeVisible();
  await end();

  await signIn(managerKey);
  await chooseRound();
  await round.getByRole("button", { name: "Seal agreement report" }).click();
  const agreement = lab.getByRole("region", {
    name: "Sealed reviewer agreement",
  });
  await expect(agreement.getByText("2 of 2 planned sources")).toBeVisible();
  await expect(agreement.getByText("1 of 2 pairs (50%)")).toBeVisible();

  const download = page.waitForEvent("download");
  await agreement
    .getByRole("link", { name: "Download agreement JSON" })
    .click();
  const downloaded = await download;
  const exported = JSON.parse(
    await readFile((await downloaded.path())!, "utf8"),
  );
  expect(exported.content_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(exported.authority).toBe("local_attribution");
  const archiveText = JSON.stringify(exported);
  if (
    [managerKey, ...participants.map((row) => row.key)].some((key) =>
      archiveText.includes(key),
    )
  ) {
    throw new Error("Agreement unexpectedly contains a local credential");
  }
  expect(exported.subjects[0].first.reason).toBe(firstReason);
  expect(exported.subjects[0].second.reason).toBe(secondReason);
  expect(exported.subjects[0].resolution.reason).toBe(resolvedReason);
  expect(exported.subjects[0].source.queue_item_id).toBe(queueItem.id);
  await openLab();
  await lab.getByLabel(/^Saved report/).selectOption({ label: roundName });
  await expect(agreement.getByText(exported.content_sha256)).toBeVisible();

  await agreement
    .getByRole("button", { name: "Save agreement workflow" })
    .click();
  await agreement
    .getByRole("button", { name: "Open Workflow Builder" })
    .click();
  const revision = page
    .getByRole("listitem")
    .filter({ hasText: "Reviewer agreement · " + roundName });
  const replays: Array<{ id: string; hash: string }> = [];
  for (let index = 0; index < 2; index++) {
    const queuedResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url() === project + "/workflow-runs",
    );
    await revision
      .getByRole("button", { name: "Run saved revision", exact: true })
      .click();
    const queued = await queuedResponse;
    expect(queued.status()).toBe(202);
    const { id } = (await queued.json()) as { id: string };
    const detailPath = api + "/workflow-runs/" + id;
    await expect
      .poll(
        async () =>
          (await (await page.request.get(detailPath)).json()).run.status,
        { timeout: 20_000 },
      )
      .toBe("succeeded");
    const results = await (await page.request.get(detailPath)).json();
    const artifact = results.artifacts.find(
      (row: { data_type: string }) =>
        row.data_type === "reviewer_lab_agreement_report",
    );
    expect(artifact.producer_port_id).toBe("report");
    expect(artifact.payload_json).toEqual(exported);
    replays.push({ id, hash: artifact.payload_sha256 });
  }
  expect(replays[0].id).not.toBe(replays[1].id);
  expect(replays[0].hash).toBe(replays[1].hash);
  await writeFile(
    info.outputPath("reviewer-lab-evidence.json"),
    JSON.stringify(
      {
        surface,
        fixture: "synthetic engineering",
        report: exported,
        replays,
      },
      null,
      2,
    ),
  );
});
