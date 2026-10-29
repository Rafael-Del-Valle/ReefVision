import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { EnvironmentalSubjectInspector } from "./EnvironmentalSubjectInspector";
const subject = { image_id: "image-1" };
const position = {
  id: "position-1",
  variable: "geographic_position",
  subject,
  location: { latitude: 32.76, longitude: -79.93 },
  observed_at: "2026-04-03T13:00:00Z",
  provenance: { source: "Survey GPS" },
};
const record = {
  id: "record-1",
  variable: "water_temperature",
  value: 20,
  unit: "degC",
  normalized_value: 20,
  normalized_unit: "degC",
  observed_at: "2026-04-03T13:10:00Z",
  source_kind: "observed",
  qc: "accepted",
  qc_flags: [],
  location: { latitude: 32.75, longitude: -79.93 },
  uncertainty: { value: 0.2, kind: "bound" },
  provenance: {
    source: "NOAA CO-OPS",
    acquired_at: "2026-04-04T00:00:00Z",
    dataset_id: "station-8665530",
  },
};
function setup(value: unknown) {
  const fetch = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(value), { status: 200 })),
    );
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <EnvironmentalSubjectInspector projectId="project-1" subject={subject} />
    </QueryClientProvider>,
  );
  return fetch;
}
afterEach(() => vi.unstubAllGlobals());
it("queries the selected image only on demand and shows an explicit unavailable state", async () => {
  const fetch = setup({
    status: "unavailable",
    reason: "No valid subject position and UTC timestamp.",
    positions: [],
    matches: {},
  });
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect environmental context" }),
  );
  expect(
    await screen.findByText("No valid subject position and UTC timestamp."),
  ).toBeInTheDocument();
  expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(
    "/api/v1/projects/project-1/environment/subject-context",
  );
  const body = JSON.parse(fetch.mock.calls[0][1].body);
  expect(body.subject).toEqual(subject);
  expect(body.max_distance_m).toBe(1000);
  expect(body.max_time_delta_s).toBe(3600);
});
it("shows separation, observed provenance, uncertainty and stale offline cache", async () => {
  setup({
    status: "available",
    positions: [position],
    position,
    matches: {
      water_temperature: [
        {
          record,
          distance_m: 1109,
          time_delta_s: 600,
          depth_delta_m: null,
          cache_age_s: 172800,
          cache_fetched_at: "2026-04-04T00:00:00Z",
          cache_expires_at: "2026-04-05T00:00:00Z",
          offline_available: true,
        },
      ],
      practical_salinity: [],
    },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect environmental context" }),
  );
  expect(await screen.findByText(/1109.0 m away/)).toBeInTheDocument();
  expect(screen.getByText(/600 s after/)).toBeInTheDocument();
  expect(screen.getByText(/48.0 h old/)).toBeInTheDocument();
  expect(screen.getByText(/Available offline/)).toBeInTheDocument();
  expect(screen.getByText("Observed", { selector: "dd" })).toBeInTheDocument();
  expect(
    screen.getByText(/practical_salinity: unavailable/),
  ).toBeInTheDocument();
  expect(screen.getByText(/0.2 degC/)).toBeInTheDocument();
  expect(
    screen.getByText(/Nearby context is not an exact measurement/),
  ).toBeInTheDocument();
});
it("requires an explicit reference choice when positions conflict", async () => {
  const fetch = setup({
    status: "ambiguous",
    reason: "Choose a position reference",
    positions: [position, { ...position, id: "position-2" }],
    matches: {},
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect environmental context" }),
  );
  fireEvent.change(await screen.findByLabelText("Position/time reference"), {
    target: { value: "position-2" },
  });
  await waitFor(() =>
    expect(
      JSON.parse(fetch.mock.calls.at(-1)![1].body).position_record_id,
    ).toBe("position-2"),
  );
});
it("shows API failures without inserting estimated observations", async () => {
  setup({ detail: "Cache integrity failure" });
  vi.mocked(fetch).mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ detail: "Cache integrity failure" }), {
        status: 409,
      }),
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect environmental context" }),
  );
  expect(
    await screen.findByText("Cache integrity failure"),
  ).toBeInTheDocument();
  expect(screen.queryByText("20 degC")).not.toBeInTheDocument();
});

it("saves a documented UTC position for the selected image without changing observations", async () => {
  const fetch = setup({
    status: "unavailable",
    reason: "No position",
    positions: [],
    matches: {},
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect environmental context" }),
  );
  await screen.findByText("No position");
  fireEvent.change(screen.getByLabelText("Subject latitude"), {
    target: { value: "32.76" },
  });
  fireEvent.change(screen.getByLabelText("Subject longitude"), {
    target: { value: "-79.93" },
  });
  fireEvent.change(screen.getByLabelText("Capture time (UTC)"), {
    target: { value: "2026-04-03T13:00" },
  });
  fireEvent.change(screen.getByLabelText("Position evidence/source"), {
    target: { value: "Survey GPS" },
  });
  fetch.mockImplementation((url: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          url.endsWith("scientific-records")
            ? { items: [position] }
            : {
                status: "unavailable",
                positions: [position],
                position,
                matches: {},
              },
        ),
        { status: 200 },
      ),
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save position reference" }),
  );
  await waitFor(() =>
    expect(
      fetch.mock.calls.some((call) =>
        String(call[0]).endsWith("scientific-records"),
      ),
    ).toBe(true),
  );
  const save = fetch.mock.calls.find((call) =>
    String(call[0]).endsWith("scientific-records"),
  )!;
  const payload = JSON.parse(save[1].body);
  expect(payload.records[0]).toMatchObject({
    variable: "geographic_position",
    subject,
    observed_at: "2026-04-03T13:00:00.000Z",
    location: { latitude: 32.76, longitude: -79.93 },
    provenance: { source: "Survey GPS" },
  });
});
