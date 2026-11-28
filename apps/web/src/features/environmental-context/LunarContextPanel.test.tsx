import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LunarContextPanel } from "./LunarContextPanel";

const PROJECT = "00000000-0000-4000-8000-000000000001";
const TIMESTAMP = "2024-04-08T18:20:00Z";
const RESPONSE = {
  schema_version: "1.1.0",
  algorithm: "reefvision-low-precision-ecliptic-longitude-1",
  project_id: PROJECT,
  observed_at: TIMESTAMP,
  phase: "new_moon",
  phase_fraction: 0.00014,
  illuminated_fraction: 0.0000002,
  approximate_lunar_age_days: 0.0041,
  reference_frame: "geocentric_approximate",
  computation: "offline_deterministic",
  content_sha256: "c".repeat(64),
  methodological_notes: [
    "Lunar phase alone does not establish local spring or neap tides.",
  ],
};

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <LunarContextPanel projectId={PROJECT} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("LunarContextPanel", () => {
  it("does not infer observation time or make automatic requests", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    renderPanel();
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Observation time (UTC)")).toHaveValue("");
  });

  it("rejects local or malformed timestamps before an API request", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    renderPanel();
    fireEvent.change(screen.getByLabelText("Observation time (UTC)"), {
      target: { value: "2024-04-08T18:20:00" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate lunar phase" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "including seconds and Z",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects impossible UTC calendar dates", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    renderPanel();
    fireEvent.change(screen.getByLabelText("Observation time (UTC)"), {
      target: { value: "2024-02-30T18:20:00Z" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate lunar phase" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "including seconds and Z",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("displays explicit UTC phase and provenance", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify(RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    renderPanel();
    fireEvent.change(screen.getByLabelText("Observation time (UTC)"), {
      target: { value: TIMESTAMP },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate lunar phase" }),
    );

    expect(await screen.findByText("Phase: New moon")).toBeVisible();
    expect(
      screen.getByText("Approximate illumination:", { exact: false }),
    ).toBeVisible();
    expect(screen.getByText(RESPONSE.content_sha256)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Lunar phase alone does not establish local spring or neap tides.",
      ),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[0];
    expect(String(url)).toContain(
      `/projects/${PROJECT}/environment/lunar-context`,
    );
    expect(JSON.parse(String(options?.body))).toEqual({
      observed_at: TIMESTAMP,
    });
  });
});
