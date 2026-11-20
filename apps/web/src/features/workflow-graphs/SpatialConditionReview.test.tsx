import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { SpatialConditionReview } from "./SpatialConditionReview";

afterEach(() => vi.unstubAllGlobals());

it("records a supplied observation and identifies its reusable report", async () => {
  const requests: unknown[] = [];
  let recorded: unknown = null;
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const observation = JSON.parse(String(init.body));
      requests.push(observation);
      recorded = {
        id: "condition-receipt",
        observation_id: "condition-receipt",
        previous_revision_id: null,
        phase: "observation",
        observation,
        decision: null,
        resolved_label: null,
        stale_source_metadata: false,
      };
      return Response.json(recorded, { status: 201 });
    }
    return Response.json(recorded ? [recorded] : []);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(
    <SpatialConditionReview
      projectId="test-project"
      assetId="test-asset"
      sourceSha256={"b".repeat(64)}
      metadataRevisionId="geometry-revision"
    />,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Condition review" }));
  await screen.findByText("No condition observations have been recorded.");
  const values = {
    "Rubric ID": "declared-rubric",
    "Rubric version": "approved-v1",
    "Rubric reference": "Study protocol page one",
    "Observation unit": "specimen",
    "Observation unit ID": "fixture-unit-1",
    "Rubric labels (one per line)": "candidate-a\ncandidate-b",
    "Observed label": "candidate-a",
    "Observer ID": "observer-id",
    "Observed at (local time)": "2026-01-01T10:30",
    "Observation evidence": "Local reference photo R1",
    "Observation uncertainty": "One view obscured",
  };
  for (const [name, value] of Object.entries(values)) {
    fireEvent.change(screen.getByLabelText(name, { exact: true }), {
      target: { value },
    });
  }
  fireEvent.click(screen.getByRole("button", { name: "Record observation" }));
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0]).toMatchObject({
    source_sha256: "b".repeat(64),
    metadata_revision_id: "geometry-revision",
    rubric: { labels: ["candidate-a", "candidate-b"], version: "approved-v1" },
    reference_evidence: "Local reference photo R1",
  });
  expect(await screen.findByText("Awaiting independent review")).toBeVisible();
  expect(screen.getByRole("link", { name: "Download report" })).toHaveAttribute(
    "href",
    expect.stringContaining("/condition-receipt/report"),
  );
});
