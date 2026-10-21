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
const vectors = [0, 1].flatMap((hour) =>
  [5, 10].map((depth) => ({
    eastward_velocity_m_s: hour === 0 ? 3 : 0,
    northward_velocity_m_s: hour === 0 ? 4 : 2,
    speed_m_s: hour === 0 ? 5 : 2,
    direction_deg_true: hour === 0 ? 36.8698976458 : 0,
    observed_at: `2026-04-03T0${hour}:00:00Z`,
    depth_m: depth,
    depth_reference: "sea_surface",
    location: {
      crs: "EPSG:4326",
      latitude: 32.5,
      longitude: -79.5,
      horizontal_uncertainty_m: null,
    },
    source_kind: "modeled",
    source: "Copernicus Marine",
    dataset_id: "synthetic",
    dataset_version: "202601",
    component_record_ids: [
      `${hour}-${depth}-eastward`,
      `${hour}-${depth}-northward`,
    ],
  })),
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
    if (
      path ===
      "/api/v1/projects/project/environment/datasets/cache/current-vectors"
    )
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: vectors,
            input_record_count: rows.length,
            exclusions: {
              unsupported_record: 0,
              invalid_metadata_or_unit: 0,
              qc_rejected: 0,
              superseded_snapshot: 0,
              incomplete_pair: 1,
              duplicate_component: 0,
            },
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
it("opens cached vectors offline with time/depth controls and scientific provenance", async () => {
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
  expect(screen.getByText(/incomplete pair: 1/)).toBeInTheDocument();
  expect(screen.getByText(/Modeled.*synthetic.*202601/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Current time (UTC)"), {
    target: { value: "2026-04-03T01:00:00Z" },
  });
  expect(await screen.findByText("2.000 m/s")).toBeInTheDocument();
  fireEvent.change(
    screen.getByLabelText("Current depth (m below sea surface)"),
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

it("imports a local current grid with explicit observed provenance", async () => {
  const fetch = setup();
  fetch.mockImplementation((input: string, init?: RequestInit) => {
    const path = new URL(input).pathname;
    if (path.endsWith("/environment/local-current-grid")) {
      const body = JSON.parse(String(init?.body));
      expect(body.source_kind).toBe("observed");
      expect(body.samples[0].eastward_velocity_m_s).toBe(0.2);
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: [{ source_kind: "observed" }, { source_kind: "observed" }],
            cache_status: "imported",
            skipped_missing: 0,
          }),
        ),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify({ items: [], total: 0 })),
    );
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Open ocean current map" }),
  );
  fireEvent.click(screen.getByText("Import local current grid"));
  fireEvent.change(screen.getByLabelText("Current grid JSON"), {
    target: {
      value: JSON.stringify({
        dataset_id: "field-adcp",
        dataset_version: "deployment-1",
        source: "Field ADCP",
        source_kind: "observed",
        acquired_at: "2026-10-21T15:00:00Z",
        samples: [
          {
            observed_at: "2026-10-21T14:00:00Z",
            latitude: 24.5,
            longitude: -81.8,
            depth_m: 5,
            eastward_velocity_m_s: 0.2,
            northward_velocity_m_s: 0.1,
          },
        ],
      }),
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Import current grid" }));
  expect(
    await screen.findByText(/2 observed values imported/),
  ).toBeInTheDocument();
});
