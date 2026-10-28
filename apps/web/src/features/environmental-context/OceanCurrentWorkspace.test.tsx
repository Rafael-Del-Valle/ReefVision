import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { OceanCurrentWorkspace } from "./OceanCurrentWorkspace";
vi.mock("../video/OpenStreetMapView", () => ({
  OpenStreetMapView: () => <div aria-label="Current map" />,
}));
const rows = [0, 1].flatMap((hour) =>
  [5, 10].flatMap((depth) =>
    ["eastward", "northward"].map((direction) => ({
      id: `${hour}-${depth}-${direction}`,
      project_id: "project",
      variable: `current_${direction}_velocity`,
      value:
        hour === 0
          ? direction === "eastward"
            ? 3
            : 4
          : direction === "eastward"
            ? 0
            : 2,
      unit: "m/s",
      normalized_value:
        hour === 0
          ? direction === "eastward"
            ? 3
            : 4
          : direction === "eastward"
            ? 0
            : 2,
      normalized_unit: "m/s",
      normalized_uncertainty:
        hour === 0 && depth === 5 && direction === "eastward" ? 0.25 : null,
      uncertainty:
        hour === 0 && depth === 5 && direction === "eastward"
          ? { value: 0.25, kind: "standard_deviation" }
          : null,
      observed_at: `2026-04-03T0${hour}:00:00Z`,
      depth_m: depth,
      depth_reference: "sea_surface",
      source_kind: "modeled",
      location: { latitude: 32.5, longitude: -79.5 },
      qc: "unassessed",
      provenance: {
        source: "Copernicus Marine",
        dataset_id: "synthetic",
        model_version: "202601",
        acquired_at: "2026-04-04T00:00:00Z",
      },
    })),
  ),
);
function setup() {
  const fetch = vi.fn().mockImplementation((input: string) => {
    const path = new URL(input).pathname;
    if (path === "/api/v1/projects/project/environment/datasets")
      return Promise.resolve(
        new Response(
          JSON.stringify({
            total: 1,
            items: [
              {
                cache_key: "cache",
                provider: "copernicus_marine",
                record_count: rows.length,
                fetched_at: "2026-04-04T00:00:00Z",
                expires_at: "2026-04-05T00:00:00Z",
              },
            ],
          }),
        ),
      );
    if (path === "/api/v1/projects/project/environment/datasets/cache")
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: rows,
            cache_status: "stale_offline",
            fetched_at: "2026-04-04T00:00:00Z",
            expires_at: "2026-04-05T00:00:00Z",
          }),
        ),
      );
    return Promise.resolve(new Response("{}", { status: 404 }));
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <OceanCurrentWorkspace projectId="project" />
    </QueryClientProvider>,
  );
  return fetch;
}
afterEach(() => vi.unstubAllGlobals());
it("opens cached currents with time, depth and provenance", async () => {
  const fetch = setup();
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Open ocean current map" }),
  );
  await screen.findByRole("option", { name: /copernicus_marine/ });
  fireEvent.change(screen.getByLabelText("Cached ocean dataset"), {
    target: { value: "cache" },
  });
  expect(await screen.findByText("5.000 m/s")).toBeInTheDocument();
  expect(screen.getByText(/36.9° toward true north/)).toBeInTheDocument();
  expect(screen.getByText(/stale_offline/)).toBeInTheDocument();
  expect(screen.getByText(/Modeled.*synthetic.*202601/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Export current vector summary CSV" }),
  ).toBeEnabled();
  expect(
    screen.getByText(
      /East component uncertainty: 0\.250 m\/s \(standard deviation\)/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/North component uncertainty: unknown/),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Current time (UTC)"), {
    target: { value: "2026-04-03T01:00:00Z" },
  });
  expect(await screen.findByText("2.000 m/s")).toBeInTheDocument();
  fireEvent.change(
    screen.getByLabelText("Current depth (m; source datum shown per vector)"),
    { target: { value: "10" } },
  );
  expect(screen.getByText(/32.5, -79.5 · 10 m/)).toBeInTheDocument();
  expect(screen.getByLabelText("Online basemap tiles")).not.toBeChecked();
});
it("never presents an empty or failed cache as measured currents", async () => {
  const fetch = setup();
  fetch.mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ detail: "Cache integrity failure" }), {
        status: 409,
      }),
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Open ocean current map" }),
  );
  expect(
    await screen.findByText("Cache integrity failure"),
  ).toBeInTheDocument();
  expect(screen.queryByText("5.000 m/s")).not.toBeInTheDocument();
});
