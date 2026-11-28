import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type {
  AcquisitionQualityReport,
  Project,
  QualityControlRunRecord,
} from "../../api/client";
import * as api from "../../api/client";
import { defaultAcquisitionThresholds } from "./AcquisitionQuality";
import { QualityControlDashboard } from "./QualityControlDashboard";

afterEach(() => vi.restoreAllMocks());

test("screens the chosen frozen dataset for similar images across splits", async () => {
  const user = userEvent.setup();
  const project = { id: "field", label_classes: [] } as unknown as Project;
  const version = {
    id: "frozen",
    name: "Site split",
    version_number: 1,
    status: "complete",
  } as api.DatasetVersionRecord;
  vi.spyOn(api, "getDatasetVersions").mockResolvedValue([version]);
  vi.spyOn(api, "getQualityControlRuns").mockResolvedValue([]);
  vi.spyOn(api, "getDatasetVersionQualityControlRuns").mockResolvedValue([]);
  const queue = vi
    .spyOn(api, "createDatasetVersionQualityControlRun")
    .mockRejectedValue(new Error("Could not queue the similarity screen"));
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <QualityControlDashboard project={project} onOpenImage={vi.fn()} />
    </QueryClientProvider>,
  );
  expect(
    screen.queryByRole("button", {
      name: "Check for similar images across splits",
    }),
  ).toBeNull();
  await user.selectOptions(screen.getByLabelText("Scope"), "dataset_version");
  await user.selectOptions(screen.getByLabelText("Dataset version"), "frozen");
  await user.click(
    screen.getByRole("button", {
      name: "Check for similar images across splits",
    }),
  );
  await waitFor(() =>
    expect(queue).toHaveBeenCalledWith(
      "frozen",
      expect.objectContaining({
        rule_categories: ["dataset_versions"],
        selected_rule_ids: ["cross_split_similar_images"],
      }),
    ),
  );
  expect(
    await screen.findByText("Could not queue the similarity screen"),
  ).toBeInTheDocument();
});

test("queues configured acquisition thresholds and reopens flagged image evidence", async () => {
  const user = userEvent.setup();
  const project = { id: "project", label_classes: [] } as unknown as Project;
  const report: AcquisitionQualityReport = {
    method: "acquisition-luminance-0001",
    review_status: "review_required",
    evaluated_image_count: 1,
    unavailable_image_count: 0,
    finding_counts: { dark_clipping: 1 },
    thresholds: { ...defaultAcquisitionThresholds, min_width_px: 400 },
    evidence_sha256: "historical-sha256",
    images: [
      {
        filename: "survey-image.png",
        source_sha256: "survey-source",
        width_px: 300,
        height_px: 200,
        capture_time_utc: null,
        camera_metadata: {},
        calibration_sha256: null,
        measurements: {
          status: "measured",
          dark_fraction: 0.5,
          bright_fraction: 0,
          sharpness: 2.5,
          opaque_sample_count: 60_000,
        },
      },
    ],
  };
  const run = {
    id: "run",
    project_id: "project",
    dataset_version_id: null,
    status: "succeeded",
    created_at: "2026-05-01T12:00:00Z",
    selected_rule_ids_json: ["acquisition_image_review"],
    issue_count: 1,
    summary_json: { acquisition: report },
    acquisition_stale_reasons: ["acquisition_metadata_changed"],
  } as QualityControlRunRecord;
  vi.spyOn(api, "getDatasetVersions").mockResolvedValue([]);
  vi.spyOn(api, "getQualityControlRuns").mockResolvedValue([run]);
  vi.spyOn(api, "getQualityControlRun").mockResolvedValue(run);
  vi.spyOn(api, "getQualityControlIssues").mockResolvedValue({
    items: [],
    page: 1,
    pages: 1,
    page_size: 25,
    total: 0,
  });
  const create = vi
    .spyOn(api, "createQualityControlRun")
    .mockResolvedValue(run);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <QualityControlDashboard project={project} onOpenImage={vi.fn()} />
    </QueryClientProvider>,
  );
  const evidence = await screen.findByRole("region", {
    name: "Acquisition quality evidence",
  });
  expect(within(evidence).getByRole("status")).toHaveTextContent(
    "Capture or calibration metadata has changed.",
  );
  await user.click(within(evidence).getByText("Image measurements"));
  expect(within(evidence).getByText("survey-image.png")).toBeVisible();
  expect(within(evidence).getByText("50.0%")).toBeVisible();
  await user.click(
    within(evidence).getByRole("button", {
      name: "Reuse acquisition thresholds",
    }),
  );
  expect(
    screen.getByRole("spinbutton", { name: "Minimum width (px)" }),
  ).toHaveValue(400);
  const dark = screen.getByRole("spinbutton", { name: "Dark luma maximum" });
  await user.clear(dark);
  await user.type(dark, "250");
  const submit = screen.getByRole("button", { name: "Run quality control" });
  expect(submit).toBeDisabled();
  await user.clear(dark);
  await user.type(dark, "3");
  await user.click(submit);
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      "project",
      expect.objectContaining({
        rule_categories: expect.arrayContaining(["acquisition"]),
        thresholds: expect.objectContaining({
          acquisition: expect.objectContaining({
            min_width_px: 400,
            dark_luma_max: 3,
          }),
        }),
      }),
    ),
  );
});
