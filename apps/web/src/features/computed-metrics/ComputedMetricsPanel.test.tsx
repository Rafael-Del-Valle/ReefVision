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
import { ComputedMetricsPanel } from "./ComputedMetricsPanel";

const project = {
  id: "00000000-0000-4000-8000-000000000001",
  name: "Reef survey",
  slug: "reef-survey",
  description: null,
  storage_root: "projects/reef-survey",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: "2026-10-28T00:00:00Z",
  archived_at: null,
  label_classes: [],
} satisfies Project;

const definition = {
  id: "00000000-0000-4000-8000-000000000010",
  project_id: project.id,
  name: "Fish density",
  expression: "fish / area",
  inputs: [
    { symbol: "fish", dimension: "count" },
    { symbol: "area", dimension: "area" },
  ],
  output_unit: "count/m2",
  formula_version: "reefvision.metric-expression.v1",
  definition_sha256: "d".repeat(64),
  created_at: "2026-10-28T12:00:00Z",
};

const result = {
  schema_version: "1.1.0",
  id: "00000000-0000-4000-8000-000000000020",
  project_id: project.id,
  definition_id: definition.id,
  definition_name: definition.name,
  expression: definition.expression,
  formula_version: definition.formula_version,
  definition_sha256: definition.definition_sha256,
  value: 6,
  unit: "count/m2",
  normalized_value: 6,
  normalized_unit: "count/m2",
  uncertainty: 0.4,
  normalized_uncertainty: 0.4,
  dimension: { count: 1, length: -2 },
  observed_at: "2026-10-28T11:30:00Z",
  subject: { image_id: "00000000-0000-4000-8000-000000000030" },
  input_record_ids: {
    fish: "00000000-0000-4000-8000-000000000040",
    area: "00000000-0000-4000-8000-000000000041",
  },
  input_snapshot: {},
  provenance: {
    engine: "safe_ast",
    source_categories: ["verified_annotation"],
  },
  content_sha256: "c".repeat(64),
  workflow_run_id: null,
  workflow_node_run_id: null,
  created_at: "2026-10-28T12:05:00Z",
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
      <ComputedMetricsPanel project={project} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ComputedMetricsPanel", () => {
  it("creates and calculates a definition with visible immutable provenance and CSV export", async () => {
    let savedDefinition = false;
    let savedResult = false;
    const submitted: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const path = String(url);
      if (init?.method === "POST") {
        submitted.push(JSON.parse(String(init.body)));
        if (path.endsWith("/computed-metric-definitions")) {
          savedDefinition = true;
          return json(definition, 201);
        }
        savedResult = true;
        return json(result, 201);
      }
      if (path.includes("computed-metric-definitions")) {
        return json({
          items: savedDefinition ? [definition] : [],
          total: savedDefinition ? 1 : 0,
        });
      }
      return json({
        items: savedResult ? [result] : [],
        total: savedResult ? 1 : 0,
      });
    });

    renderPanel();
    expect(await screen.findByText("No metric definitions yet")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Metric name"), {
      target: { value: "Fish density" },
    });
    fireEvent.change(screen.getByLabelText("Expression"), {
      target: { value: "fish / area" },
    });
    fireEvent.change(screen.getByLabelText("Input symbols and dimensions"), {
      target: { value: "fish: count\narea: area" },
    });
    fireEvent.change(screen.getByLabelText("Output unit"), {
      target: { value: "count/m2" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save immutable definition" }),
    );

    expect(await screen.findByText("Definition saved.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Input symbols and record IDs"), {
      target: {
        value:
          "fish: 00000000-0000-4000-8000-000000000040\narea: 00000000-0000-4000-8000-000000000041",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Calculate metric" }));

    const card = await screen.findByLabelText("Computed result Fish density");
    expect(card).toHaveTextContent("6 count/m2 ± 0.4");
    expect(card).toHaveTextContent(definition.expression);
    expect(card).toHaveTextContent(definition.formula_version);
    expect(card).toHaveTextContent(definition.definition_sha256);
    expect(card).toHaveTextContent(result.input_record_ids.fish);
    expect(card).toHaveTextContent("verified_annotation");
    expect(within(card).getByText(/Standalone calculation/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Export results as CSV" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining(
        `/projects/${project.id}/computed-metric-results.csv`,
      ),
    );
    expect(submitted).toEqual([
      {
        name: "Fish density",
        expression: "fish / area",
        inputs: [
          { symbol: "fish", dimension: "count" },
          { symbol: "area", dimension: "area" },
        ],
        output_unit: "count/m2",
      },
      { inputs: result.input_record_ids },
    ]);
  });

  it("shows calculation validation failures without adding a result", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const path = String(url);
      if (init?.method === "POST") {
        return json(
          { detail: "Inputs must share the same subject and observation time" },
          422,
        );
      }
      if (path.includes("computed-metric-definitions")) {
        return json({ items: [definition], total: 1 });
      }
      return json({ items: [], total: 0 });
    });
    renderPanel();
    await screen.findByRole("option", { name: "Fish density" });
    fireEvent.change(screen.getByLabelText("Input symbols and record IDs"), {
      target: {
        value: `fish: ${result.input_record_ids.fish}\narea: ${result.input_record_ids.area}`,
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Calculate metric" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Inputs must share the same subject and observation time",
    );
    expect(screen.getByText("No computed results yet")).toBeVisible();
  });
});
