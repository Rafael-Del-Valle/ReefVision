import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { JobRecord } from "../../api/client";
import { ScientificComparisonPanel } from "./ScientificComparisonPanel";

const source = (id: string, split: string): JobRecord => ({
  id,
  project_id: "reef",
  job_type: "reefpose_validation",
  status: "succeeded",
  progress_current: 1,
  progress_total: 1,
  request_json: {},
  result_json: { split, models: { model: { name: id } } },
  error_message: null,
  created_at: "2026-11-14T12:00:00Z",
  started_at: null,
  completed_at: null,
});

const fixture = {
  id: "comparison",
  content_sha256: "a".repeat(64),
  stale: false,
  source_id_map: {},
  snapshot: {
    data_kind: "synthetic",
    reference_sha256: "b".repeat(64),
    rater_id: "rater",
    method: "fixture",
    software_version: "1.3.0",
    options: { metric: "event_count", name: "gape", unit: null, icc: null },
    models: [
      {
        source_job_id: "model-one",
        source_result_sha256: "c".repeat(64),
        model_name: "Fixture model",
        checkpoint_sha256: "d".repeat(64),
        pairs: [
          {
            video_id: "video",
            group_id: "tank",
            individual_id: "fish",
            frame: null,
            start_s: 0,
            end_s: 1,
            reference: 0,
            estimate: 2,
          },
        ],
        statistics: {
          sample_count: 1,
          independent_groups: 1,
          zero_reference_count: 1,
          bias: 2,
          mean_absolute_error: 2,
          mean_absolute_percentage_error: null,
          limits_of_agreement: null,
          icc: null,
          bias_ci95: null,
          mae_ci95: null,
        },
      },
    ],
    exclusions: [],
    pairing: null,
    limitations: ["Synthetic provenance fixture."],
  },
};

afterEach(() => vi.restoreAllMocks());

it("uses held-out reports and saves a comparison with plot, zero-reference and download evidence", async () => {
  let persisted = false;
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (_url, options) => {
      if (options?.method === "POST") {
        persisted = true;
        expect(JSON.parse(String(options.body))).toMatchObject({
          source_job_ids: ["model-one", "model-two"],
          metric: "event_count",
          name: "gape",
          independent_groups: false,
        });
        return new Response(JSON.stringify(fixture), { status: 201 });
      }
      return new Response(JSON.stringify(persisted ? [fixture] : []));
    });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ScientificComparisonPanel
        projectId="reef"
        jobs={[
          source("model-one", "test"),
          source("model-two", "test"),
          source("development-case", "development"),
        ]}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("Scientific human–model comparison"));
  expect(
    screen.queryByRole("option", { name: /development-case/ }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Primary held-out report"), {
    target: { value: "model-one" },
  });
  fireEvent.change(screen.getByLabelText("Second held-out report"), {
    target: { value: "model-two" },
  });
  fireEvent.change(screen.getByLabelText("Event label"), {
    target: { value: "gape" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save scientific comparison" }),
  );
  expect(
    await screen.findByRole("img", {
      name: "Reference against estimate for Fixture model",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("img", {
      name: "Bland–Altman difference plot for Fixture model",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText(/1 zero references/)).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Download paired CSV" }),
  ).toHaveAttribute(
    "href",
    expect.stringContaining(
      "/scientific-comparisons/comparison/export?format=csv",
    ),
  );
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
});
