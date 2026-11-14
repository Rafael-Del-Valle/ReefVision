import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { EnvironmentalContextPanel } from "./EnvironmentalContextPanel";

const project: Project = {
  id: "project-reef",
  name: "Reef survey",
  slug: "reef-survey",
  description: null,
  storage_root: "projects/project-reef",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-18T00:00:00Z",
  updated_at: "2026-10-18T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

const sensorRecord = {
  variable: "water_temperature",
  value: 68,
  unit: "degF",
  observed_at: "2026-10-17T14:30:00+02:00",
  source_kind: "observed",
  subject: {},
  depth_m: null,
  depth_reference: null,
  qc: "suspect",
  qc_flags: ["sensor_drift"],
  provenance: {
    source: "Reef logger 7",
    acquired_at: "2026-10-18T09:00:00Z",
    method: "temperature_logger",
    processing_parameters: {},
    source_metadata: { instrument: "logger-7" },
  },
};

const storedRecord = {
  ...sensorRecord,
  schema_version: "1.1.0",
  id: "record-1",
  project_id: project.id,
  normalized_value: 20,
  normalized_unit: "degC",
  normalized_uncertainty: null,
  content_sha256: "a".repeat(64),
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <EnvironmentalContextPanel project={project} />
    </QueryClientProvider>,
  );
}

function chooseJson(content: string) {
  fireEvent.click(
    screen.getByRole("button", { name: "Add environmental data" }),
  );
  fireEvent.change(screen.getByLabelText("Sensor JSON file"), {
    target: {
      files: [new File([content], "sensor.json", { type: "application/json" })],
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Import sensor JSON" }));
}

function openNoaa() {
  fireEvent.click(
    screen.getByRole("button", { name: "Add environmental data" }),
  );
  fireEvent.change(screen.getByLabelText("Data source"), {
    target: { value: "noaa" },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("EnvironmentalContextPanel", () => {
  it("keeps acquisition drafts across views and resets them for another project", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      json({ items: [], total: 0 }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const renderProject = (value: Project) => (
      <QueryClientProvider client={client}>
        <EnvironmentalContextPanel project={value} />
      </QueryClientProvider>
    );
    const panel = render(renderProject(project));
    expect(await screen.findByText("No scientific records yet")).toBeVisible();
    expect(
      screen.queryByRole("textbox", { name: "NOAA station ID" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Add environmental data" }),
    );
    fireEvent.change(screen.getByLabelText("Data source"), {
      target: { value: "noaa" },
    });
    fireEvent.change(screen.getByLabelText("NOAA station ID"), {
      target: { value: "8724580" },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Analyses" }));
    fireEvent.click(screen.getByRole("tab", { name: "Data sources" }));
    expect(screen.getByLabelText("NOAA station ID")).toHaveValue("8724580");
    panel.rerender(renderProject({ ...project, id: "other-project" }));
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.queryByRole("textbox", { name: "NOAA station ID" }),
    ).not.toBeInTheDocument();
  });

  it("shows one record inspector and reports coverage scope", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({
        items: [
          storedRecord,
          {
            ...storedRecord,
            id: "record-2",
            value: 72,
            calibration_current: false,
          },
        ],
        total: 102,
      }),
    );
    renderPanel();
    expect(await screen.findByText("102")).toBeVisible();
    expect(screen.getByText(/showing 2 of 102 saved records/i)).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Data sources" }));
    const table = screen.getByRole("table", {
      name: "Saved scientific records",
    });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    fireEvent.click(within(table).getAllByRole("button")[1]);
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText(/source calibration has changed/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close record" }));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("keeps pending imports visible when another environmental view opens", async () => {
    let complete: (response: Response) => void = () => {};
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) =>
      init?.method === "POST"
        ? new Promise((resolve) => {
            complete = resolve;
          })
        : json({ items: [], total: 0 }),
    );
    renderPanel();
    chooseJson(JSON.stringify({ records: [sensorRecord] }));
    expect(
      await screen.findByText("In progress: Sensor JSON import"),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Analyses" }));
    expect(screen.getByText("In progress: Sensor JSON import")).toBeVisible();
    complete(json({ items: [storedRecord], total: 1 }, 201));
    fireEvent.click(screen.getByRole("tab", { name: "Data sources" }));
    expect(
      await screen.findByText("Imported 1 scientific record."),
    ).toBeVisible();
  });

  it("labels superseded provider observations as historical", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({
        items: [{ ...storedRecord, environmental_snapshot_current: false }],
        total: 1,
      }),
    );
    renderPanel();
    fireEvent.click(screen.getByRole("tab", { name: "Data sources" }));
    fireEvent.click(
      await screen.findByRole("button", { name: /Water temperature/ }),
    );
    expect(
      await screen.findByText(
        "Historical provider snapshot; excluded from current environmental lookup.",
      ),
    ).toBeVisible();
  });

  it("loads original and normalized quantities with UTC time, unknown depth, QC, and provenance", async () => {
    let complete!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    );
    renderPanel();
    expect(screen.getByText("Loading scientific records")).toBeInTheDocument();
    complete(json({ items: [storedRecord], total: 1 }));
    fireEvent.click(screen.getByRole("tab", { name: "Data sources" }));
    fireEvent.click(
      await screen.findByRole("button", { name: /Water temperature/ }),
    );
    const inspector = within(
      screen.getByRole("region", { name: "Selected record" }),
    );

    expect(inspector.getByText("68 degF")).toBeInTheDocument();
    expect(screen.getByText("20 degC")).toBeInTheDocument();
    expect(screen.getByText("2026-10-17 12:30:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("Unknown depth")).toBeInTheDocument();
    expect(screen.getByText("Observed")).toBeInTheDocument();
    expect(screen.getByText("Suspect")).toBeInTheDocument();
    expect(screen.getByText("sensor_drift")).toBeInTheDocument();
    expect(inspector.getByText("Reef logger 7")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Provenance and record details"));
    expect(screen.getByText(storedRecord.content_sha256)).toBeInTheDocument();
    expect(screen.getByText(/logger-7/)).toBeInTheDocument();
  });

  it("renders validation details with their field location and lets reads retry", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        json(
          {
            detail: [
              {
                loc: ["query", "source_kind"],
                msg: "Input should be observed, remotely_sensed, modeled or derived",
              },
            ],
          },
          422,
        ),
      )
      .mockResolvedValueOnce(json({ items: [], total: 0 }));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "source_kind: Input should be observed",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText("No scientific records yet"),
    ).toBeInTheDocument();
  });

  it("imports a local JSON batch and refreshes persisted project records", async () => {
    let imported = false;
    let submitted: unknown;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
      if (init?.method === "POST") {
        submitted = JSON.parse(String(init.body));
        imported = true;
        return json({ items: [storedRecord], total: 1 }, 201);
      }
      return json({
        items: imported ? [storedRecord] : [],
        total: imported ? 1 : 0,
      });
    });
    renderPanel();
    await screen.findByText("No scientific records yet");
    chooseJson(JSON.stringify({ records: [sensorRecord] }));

    expect(
      await screen.findByText("Imported 1 scientific record."),
    ).toBeInTheDocument();
    expect(await screen.findByText("68 degF")).toBeInTheDocument();
    expect(submitted).toEqual({ records: [sensorRecord] });
  });

  it.each([
    ["{broken", "The selected file is not valid JSON."],
    [
      "[]",
      "The JSON file must contain a records array with 1 to 5000 records.",
    ],
    [
      '{"records":[]}',
      "The JSON file must contain a records array with 1 to 5000 records.",
    ],
  ])("shows local import errors for %s", async (content, message) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ items: [], total: 0 }),
    );
    renderPanel();
    chooseJson(content);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("shows backend validation errors for an imported sensor record", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) =>
      init?.method === "POST"
        ? json(
            {
              detail: [
                {
                  loc: ["body", "records", 0, "unit"],
                  msg: "Unsupported unit",
                },
              ],
            },
            422,
          )
        : json({ items: [], total: 0 }),
    );
    renderPanel();
    chooseJson(
      JSON.stringify({ records: [{ ...sensorRecord, unit: "unspecified" }] }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "records.0.unit: Unsupported unit",
    );
  });

  it.each([
    ["downloaded", "Downloaded from NOAA"],
    ["fresh", "Fresh cached data"],
    ["stale_offline", "Stale cache used offline"],
  ])(
    "reports NOAA %s acquisition and cache timestamps",
    async (cacheStatus, label) => {
      let submitted: unknown;
      vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
        if (String(url).endsWith("/environment/noaa")) {
          submitted = JSON.parse(String(init?.body));
          return json({
            items: [storedRecord],
            cache_status: cacheStatus,
            fetched_at: "2026-10-17T10:00:00Z",
            expires_at: "2026-10-18T10:00:00Z",
            source_url:
              "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=8724580",
            skipped_missing: 2,
          });
        }
        return json({ items: [], total: 0 });
      });
      renderPanel();
      openNoaa();
      fireEvent.change(screen.getByLabelText("NOAA station ID"), {
        target: { value: "8724580" },
      });
      fireEvent.change(screen.getByLabelText("Observation day (UTC)"), {
        target: { value: "2026-10-17" },
      });
      fireEvent.click(screen.getByLabelText("Use cached data only (offline)"));
      fireEvent.click(screen.getByRole("button", { name: "Import NOAA data" }));

      const status = await screen.findByLabelText("NOAA import result");
      expect(status).toHaveTextContent(label);
      expect(status).toHaveTextContent("2026-10-17 10:00:00 UTC");
      expect(status).toHaveTextContent("2026-10-18 10:00:00 UTC");
      expect(status).toHaveTextContent("Missing values skipped: 2");
      expect(
        within(status).getByRole("link", { name: "NOAA source" }),
      ).toHaveAttribute("href", expect.stringContaining("station=8724580"));
      expect(submitted).toEqual({
        station_id: "8724580",
        day: "2026-10-17",
        offline: true,
      });
    },
  );

  it("shows NOAA service failures without a success state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      String(url).endsWith("/environment/noaa")
        ? json(
            {
              detail:
                "No cached NOAA data is available for this station and day",
            },
            400,
          )
        : json({ items: [], total: 0 }),
    );
    renderPanel();
    openNoaa();
    fireEvent.change(screen.getByLabelText("NOAA station ID"), {
      target: { value: "8724580" },
    });
    fireEvent.change(screen.getByLabelText("Observation day (UTC)"), {
      target: { value: "2026-10-17" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import NOAA data" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No cached NOAA data is available",
    );
    expect(
      screen.queryByLabelText("NOAA import result"),
    ).not.toBeInTheDocument();
  });

  it("paginates server records and resets pagination when filters change", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const query = new URL(String(url)).searchParams;
      if (query.get("source_kind") === "modeled") {
        expect(query.get("offset")).toBe("0");
        expect(query.get("variable")).toBe("current_speed");
        return json({ items: [], total: 0 });
      }
      if (query.get("offset") === "100") {
        return json({
          items: [{ ...storedRecord, id: "record-last", value: 72 }],
          total: 101,
        });
      }
      return json({
        items: Array.from({ length: 100 }, (_, index) => ({
          ...storedRecord,
          id: `record-${index}`,
        })),
        total: 101,
      });
    });
    renderPanel();
    fireEvent.click(screen.getByRole("tab", { name: "Data sources" }));
    expect(await screen.findByText("Records 1–100 of 101")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("72 degF")).toBeInTheDocument();
    expect(screen.getByText("Records 101–101 of 101")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Variable filter"), {
      target: { value: "current_speed" },
    });
    fireEvent.change(screen.getByLabelText("Source kind filter"), {
      target: { value: "modeled" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(
      await screen.findByText("No records match these filters"),
    ).toBeInTheDocument();
  });

  it("cancels the project record request when the panel unmounts", async () => {
    let signal: AbortSignal | null | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => {
      signal = init?.signal;
      return new Promise(() => {});
    });
    const panel = renderPanel();
    await waitFor(() => expect(signal).toBeDefined());
    panel.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
