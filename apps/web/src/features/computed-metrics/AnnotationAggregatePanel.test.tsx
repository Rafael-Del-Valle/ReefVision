import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { AnnotationAggregatePanel } from "./AnnotationAggregatePanel";

const project = {
  id: "00000000-0000-4000-8000-000000000001",
  name: "Reef survey",
  slug: "reef-survey",
  description: null,
  storage_root: "projects/reef-survey",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-11-04T00:00:00Z",
  updated_at: "2026-11-04T00:00:00Z",
  archived_at: null,
  label_classes: [],
} satisfies Project;

const imageIds = [
  "00000000-0000-4000-8000-000000000011",
  "00000000-0000-4000-8000-000000000012",
];
const definition = {
  id: "00000000-0000-4000-8000-000000000020",
  project_id: project.id,
  name: "Reviewed coral count",
  definition_kind: "annotation_aggregate",
  expression: "count(verified_annotations)",
  source_kind: "verified_annotations",
  grouping_level: "image_group_key",
  label_class_ids: [],
  operation: "count",
  output_unit: "count",
  formula_version: "reefvision.annotation-aggregate.v1",
  schema_version: "1.1.0",
  required_review_state: "reviewed",
  independence_contract: "one_unit_per_image_group_key",
  definition_sha256: "d".repeat(64),
  created_at: "2026-11-04T01:00:00Z",
};
const preview = {
  schema_version: "1.1.0",
  definition_id: definition.id,
  definition_sha256: definition.definition_sha256,
  source_kind: definition.source_kind,
  grouping_level: definition.grouping_level,
  operation: "count",
  required_review_state: "reviewed",
  image_count: 2,
  independent_unit_count: 1,
  observation_count: 3,
  mean_per_independent_unit: 3,
  counts_by_class: [
    {
      label_class_id: "00000000-0000-4000-8000-000000000030",
      label_name: "Coral",
      count: 3,
    },
  ],
  groups: [
    {
      unit_key: "colony-a",
      image_ids: imageIds,
      observation_count: 3,
      counts_by_class: [],
    },
  ],
  excluded_proposals_by_status: { pending: 2 },
  image_snapshot: imageIds.map((image_id) => ({ image_id })),
  observation_snapshot: [],
  evidence_sha256: "e".repeat(64),
};
const result = {
  ...preview,
  id: "00000000-0000-4000-8000-000000000040",
  project_id: project.id,
  result_kind: "annotation_aggregate",
  definition_name: definition.name,
  expression: definition.expression,
  formula_version: definition.formula_version,
  output_unit: "count",
  observed_at: "2026-11-04T01:05:00Z",
  provenance: { predictions_counted: false },
  content_sha256: "c".repeat(64),
  workflow_run_id: null,
  workflow_node_run_id: null,
  created_at: "2026-11-04T01:05:00Z",
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
      <AnnotationAggregatePanel project={project} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("AnnotationAggregatePanel", () => {
  it("creates, previews, calculates, validates, and exports replicate-aware counts", async () => {
    let savedDefinition = false;
    let savedResult = false;
    const submitted: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const path = String(url);
      if (init?.method === "POST") {
        submitted.push(JSON.parse(String(init.body)));
        if (path.endsWith("/computed-aggregate-definitions")) {
          savedDefinition = true;
          return json(definition, 201);
        }
        if (path.endsWith("/preview")) return json(preview);
        savedResult = true;
        return json(result, 201);
      }
      if (path.includes("/validation")) {
        return json({
          result_id: result.id,
          current: true,
          saved_evidence_sha256: preview.evidence_sha256,
          current_evidence_sha256: preview.evidence_sha256,
          reasons: [],
        });
      }
      if (path.includes("computed-aggregate-definitions")) {
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
    expect(await screen.findByText("No aggregate results yet")).toBeVisible();
    expect(
      screen.getByText(/researcher-declared replicate identity/),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Aggregate name"), {
      target: { value: definition.name },
    });
    fireEvent.change(screen.getByLabelText("Independent-unit grouping"), {
      target: { value: "image_group_key" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save aggregate definition" }),
    );
    expect(
      await screen.findByRole("option", { name: definition.name }),
    ).toBeVisible();

    fireEvent.change(screen.getByLabelText("Reviewed image IDs"), {
      target: { value: imageIds.join("\n") },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview eligible evidence" }),
    );
    const summary = await screen.findByLabelText("Aggregate preview summary");
    expect(summary).toHaveTextContent("Observations3");
    expect(summary).toHaveTextContent("Images2");
    expect(summary).toHaveTextContent("Independent units1");
    expect(summary).toHaveTextContent("Coral: 3");
    expect(summary).toHaveTextContent("colony-a");
    expect(summary).toHaveTextContent('Excluded proposals: {"pending":2}');

    fireEvent.click(
      screen.getByRole("button", { name: "Save immutable aggregate" }),
    );
    expect(await screen.findByText("Evidence current")).toBeVisible();
    fireEvent.click(screen.getByText("Immutable provenance"));
    expect(screen.getByText(/Standalone calculation/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Export aggregate CSV" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining(
        `/projects/${project.id}/computed-aggregate-results.csv`,
      ),
    );
    await waitFor(() => expect(submitted).toHaveLength(3));
    expect(submitted).toEqual([
      {
        name: definition.name,
        source_kind: "verified_annotations",
        grouping_level: "image_group_key",
        label_class_ids: [],
      },
      { image_ids: imageIds },
      { image_ids: imageIds },
    ]);
  });

  it("shows reviewed-image eligibility failures", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const path = String(url);
      if (init?.method === "POST") {
        return json(
          {
            detail: "All selected images must have reviewed annotation status",
          },
          400,
        );
      }
      if (path.includes("computed-aggregate-definitions")) {
        return json({ items: [definition], total: 1 });
      }
      return json({ items: [], total: 0 });
    });
    renderPanel();
    await screen.findByRole("option", { name: definition.name });
    fireEvent.change(screen.getByLabelText("Reviewed image IDs"), {
      target: { value: imageIds[0] },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Preview eligible evidence" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "All selected images must have reviewed annotation status",
    );
  });
});
