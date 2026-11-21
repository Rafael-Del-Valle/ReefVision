import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { expect } from "@playwright/test";
import { verifyResearchDesktop } from "./disposableResearchDesktop";
import { test } from "./spatialDesktop";

test("holds and releases a real imported image in Jobs and resources", async ({
  desktop,
}, info) => {
  const { page, api, web, surface } = desktop;
  const runtime = await verifyResearchDesktop(page, api);
  const name = `Compute queue ${randomUUID().slice(0, 8)}`;
  const created = await page.request.post(`${api}/projects`, {
    data: { name, template: "blank" },
  });
  expect(created.status()).toBe(201);
  const project = await created.json();
  await page.addInitScript(
    (version) =>
      localStorage.setItem(
        `reefvision.onboarding.dismissed.${version}`,
        "true",
      ),
    runtime.application_version,
  );
  const initial = await (
    await page.request.get(`${api}/compute/resources`)
  ).json();
  expect(initial.cpu_slots).toBeGreaterThan(0);
  const limits = `${api}/compute/resources`;
  const list = `${api}/projects/${project.id}/compute/jobs`;
  const open = async () => {
    await page.goto(web);
    await page
      .getByRole("button", { name: `Open ${name}`, exact: true })
      .click();
  };
  const jobs = async () => {
    await page.getByRole("tab", { name: "Models & AI", exact: true }).click();
    await page
      .getByRole("tab", { name: "Jobs and resources", exact: true })
      .click();
  };
  const change = async (value: number) => {
    await page
      .getByRole("combobox", { name: "CPU slots", exact: true })
      .selectOption(String(value));
    const saved = page.waitForResponse(
      (r) => r.url() === limits && r.request().method() === "PUT",
    );
    await page.getByRole("button", { name: "Save resource limits" }).click();
    expect((await saved).status()).toBe(200);
  };
  try {
    await open();
    await jobs();
    await change(0);
    await page
      .getByRole("tab", { name: "Data & annotation", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Images & annotation", exact: true })
      .click();
    const imported = page.waitForResponse(
      (r) =>
        r.url().endsWith("/imports/images") && r.request().method() === "POST",
    );
    await page.getByLabel("Import files", { exact: true }).setInputFiles({
      name: "queue-original.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAIAAAASFvFNAAAAHElEQVR4nGPkZmBlM2ZiM2ZlEZnJy2XMzmbMAgAPggHKzuzZ0gAAAABJRU5ErkJggg==",
        "base64",
      ),
    });
    const source = (await (await imported).json()).successful[0];
    await jobs();
    await expect(
      page.getByText("The CPU queue is paused.", { exact: true }),
    ).toBeVisible();
    const paused = (await (await page.request.get(list)).json()).items.find(
      (row: { job: { job_type: string } }) => row.job.job_type === "thumbnail",
    );
    expect(paused.job.request_json.image_id).toBe(source.image_id);
    expect(paused.admission).toBe("waiting");
    await open();
    await jobs();
    await expect(
      page.getByRole("combobox", { name: "CPU slots", exact: true }),
    ).toHaveValue("0");
    await change(initial.cpu_slots);
    await expect
      .poll(
        async () =>
          (
            await (
              await page.request.get(`${api}/jobs/${paused.job.id}`)
            ).json()
          ).status,
      )
      .toBe("succeeded");
    await expect(
      page.getByRole("article", { name: `thumbnail ${paused.job.id}` }),
    ).toContainText("succeeded");
    const final = await (await page.request.get(list)).json();
    expect(
      final.items.filter(
        (entry: { job: { id: string } }) => entry.job.id === paused.job.id,
      ),
    ).toHaveLength(1);
    const image = await (
      await page.request.get(`${api}/images/${source.image_id}`)
    ).json();
    expect(image.sha256).toBe(
      "1f5a78f96eab21377ff77e71ac971e3c73e9fa843223bebb62c67c15d64546c5",
    );
    await writeFile(
      info.outputPath("compute-resources.json"),
      JSON.stringify(
        {
          surface,
          runtime,
          project_id: project.id,
          job_id: paused.job.id,
          image_id: image.id,
          image_sha256: image.sha256,
          queued: paused.admission,
          after: "succeeded",
          initial,
        },
        null,
        2,
      ),
    );
  } finally {
    await page.request.put(limits, {
      data: { cpu_slots: initial.cpu_slots, gpu_slots: initial.gpu_slots },
    });
  }
});
