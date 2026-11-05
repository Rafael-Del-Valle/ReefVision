import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EnvironmentalAnalysisWorkspace } from "./EnvironmentalAnalysisWorkspace";

const PROJECT = "00000000-0000-4000-8000-000000000001";
const HASH = "a".repeat(64);

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function result(kind = "lunar_context") {
  return {
    id: "00000000-0000-4000-8000-000000000010",
    project_id: PROJECT,
    definition_id: "00000000-0000-4000-8000-000000000011",
    analysis_kind: kind,
    observed_at: "2024-04-08T18:21:00Z",
    payload: { phase: "new_moon", interpretation: "descriptive_context_only" },
    input_snapshot: { observed_at: "2024-04-08T18:21:00Z" },
    source_record_ids: [],
    source_analysis_result_ids: [],
    quality_control: { status: "accepted", flags: [] },
    uncertainty: { type: "methodological", statement: "Low precision" },
    content_sha256: HASH,
    workflow_run_id: null,
    workflow_node_run_id: null,
    created_at: "2026-11-05T12:00:00Z",
  };
}

function definition(kind = "lunar_context") {
  return {
    id: "00000000-0000-4000-8000-000000000011",
    project_id: PROJECT,
    analysis_kind: kind,
    name: "Saved context",
    configuration: {},
    calculation_version: "test-v1",
    definition_sha256: "b".repeat(64),
    created_at: "2026-11-05T12:00:00Z",
  };
}

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <EnvironmentalAnalysisWorkspace projectId={PROJECT} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("EnvironmentalAnalysisWorkspace", () => {
  it("does not acquire data automatically and explains descriptive-only evidence", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    renderWorkspace();
    expect(fetch).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Observed and predicted water levels remain separate/),
    ).toBeVisible();
    expect(
      screen.getByText(/descriptive context, not causation or significance/),
    ).toBeVisible();
  });

  it("imports explicit NOAA predictions with datum and offline-cache policy", async () => {
    let submitted: unknown;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      expect(String(url)).toContain(
        `/projects/${PROJECT}/environment/noaa/tides`,
      );
      submitted = JSON.parse(String(init?.body));
      return json({
        items: [],
        cache_status: "stale_offline",
        fetched_at: "2026-11-04T12:00:00Z",
        expires_at: "2026-11-05T12:00:00Z",
        source_url: "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
        skipped_missing: 0,
      });
    });
    renderWorkspace();
    fireEvent.change(screen.getByLabelText("Tidal station ID"), {
      target: { value: "8665530" },
    });
    fireEvent.change(screen.getByLabelText("Tidal day (UTC)"), {
      target: { value: "2026-04-03" },
    });
    fireEvent.change(screen.getByLabelText("Tidal product"), {
      target: { value: "predictions" },
    });
    fireEvent.change(screen.getByLabelText("Tidal datum"), {
      target: { value: "MLLW" },
    });
    fireEvent.click(screen.getByLabelText("Use tidal cache only (offline)"));
    fireEvent.click(
      screen.getByRole("button", { name: "Import tidal records" }),
    );
    expect(
      await screen.findByLabelText("Tidal import result"),
    ).toHaveTextContent("Stale cache used offline");
    expect(submitted).toEqual({
      station_id: "8665530",
      day: "2026-04-03",
      product: "predictions",
      datum: "MLLW",
      offline: true,
    });
  });

  it("persists lunar analysis evidence and exposes CSV download", async () => {
    let submitted: unknown;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      expect(String(url)).toContain(`/environment/analyses/lunar-context`);
      submitted = JSON.parse(String(init?.body));
      return json({ definition: definition(), results: [result()] }, 201);
    });
    renderWorkspace();
    fireEvent.change(screen.getByLabelText("Analysis name"), {
      target: { value: "April new moon" },
    });
    fireEvent.change(screen.getByLabelText("Analysis timestamp (UTC)"), {
      target: { value: "2024-04-08T18:21:00Z" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Persist analysis" }));
    const evidence = await screen.findByLabelText(
      "Saved environmental analysis",
    );
    expect(evidence).toHaveTextContent("Lunar context");
    expect(evidence).toHaveTextContent(HASH);
    expect(
      within(evidence).getByRole("link", { name: "Download evidence CSV" }),
    ).toHaveAttribute("href", expect.stringContaining(`${result().id}.csv`));
    expect(submitted).toEqual({
      name: "April new moon",
      observed_at: ["2024-04-08T18:21:00Z"],
    });
  });

  it("loads persisted history only when requested", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        json({ items: [result("lagged_comparison")], total: 1 }),
      );
    renderWorkspace();
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved analyses" }),
    );
    const history = await screen.findByLabelText(
      "Environmental analysis history",
    );
    expect(history).toHaveTextContent("Lagged comparison");
    expect(history).toHaveTextContent("descriptive_context_only");
  });
});
