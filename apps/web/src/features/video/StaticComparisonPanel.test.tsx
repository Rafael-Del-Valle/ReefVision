import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StaticComparisonPanel } from "./StaticComparisonPanel";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

it("submits a reviewed dataset, compatible detector, and explicit agreement settings", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, options) => {
      if (options?.method === "POST" || String(input).includes("/jobs/")) {
        return Response.json({
          id: "count-run",
          status: "queued",
          progress_current: 0,
          progress_total: 2,
        });
      }
      if (String(input).includes("/options")) {
        return Response.json({
          datasets: [
            {
              id: "reference",
              name: "Reviewed reef",
              reviewed_count: 4,
              test_reviewed_count: 2,
              classes: [{ id: "coral", name: "Coral" }],
            },
          ],
          models: [
            {
              id: "detector",
              name: "Reef detector",
              mapped_class_ids: ["coral"],
            },
            {
              id: "different",
              name: "Unrelated detector",
              mapped_class_ids: ["fish"],
            },
          ],
        });
      }
      return Response.json([]);
    });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <StaticComparisonPanel projectId="reef" />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("Static-image human–model comparison"));
  await screen.findByRole("option", { name: /Reviewed reef/ });
  fireEvent.change(screen.getByLabelText("Reviewed reference dataset"), {
    target: { value: "reference" },
  });
  expect(
    screen.queryByRole("option", { name: /Unrelated detector/ }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Primary detector"), {
    target: { value: "detector" },
  });
  fireEvent.click(screen.getByLabelText(/independent sampling units/));
  fireEvent.change(screen.getByLabelText("Intraclass correlation"), {
    target: { value: "A,1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Run count comparison" }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]
        ?.body,
    ).toBe(
      JSON.stringify({
        dataset_version_id: "reference",
        model_ids: ["detector"],
        split: "test",
        class_ids: [],
        inference: {
          confidence_threshold: 0.25,
          iou_threshold: 0.7,
          device: "auto",
        },
        independent_groups: true,
        homoscedastic_normal_differences: false,
        icc: "A,1",
      }),
    ),
  );
});
