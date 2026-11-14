import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { EcologyWorkspace } from "./EcologyWorkspace";

afterEach(() => vi.restoreAllMocks());

it("registers a project organism and keeps projected results under scientific review", async () => {
  const sent: unknown[] = [];
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      let json: unknown = { items: [], page: 1, pages: 0 };
      if (url.endsWith("/identity-registry")) {
        json = {
          identities: sent.length
            ? [
                {
                  id: "revision-1",
                  organism_key: "colony-9",
                  kind: "colony",
                  revision: 1,
                  reason: "Field label",
                },
              ]
            : [],
          identity_history: [],
          image_evidence_links: [],
          annotation_evidence_links: [],
          calibration_evidence_links: [],
          snapshot_sha256: "registry-fingerprint",
        };
      } else if (url.endsWith("/organisms")) {
        sent.push(JSON.parse(String(init?.body)));
        json = {};
      } else if (url.endsWith("/calibrated-measurement-candidates")) {
        json = {
          candidate_count: 0,
          projected_endpoint_changes: [],
          exclusions: [],
          sampling_date_qc: [],
          input_sha256: "source-fingerprint",
        };
      }
      return Response.json(json);
    });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <EcologyWorkspace projectId="field-project" />
    </QueryClientProvider>,
  );

  await screen.findByText("No registered organisms");
  const register = within(
    screen.getByRole("form", { name: "Register organism" }),
  );
  fireEvent.change(register.getByLabelText("Organism ID"), {
    target: { value: "colony-9" },
  });
  fireEvent.change(register.getByLabelText("Registration reason"), {
    target: { value: "Field label" },
  });
  fireEvent.click(register.getByRole("button", { name: "Register organism" }));
  await screen.findByRole("heading", { name: "colony-9" });
  expect(sent).toEqual([
    {
      organism_key: "colony-9",
      kind: "colony",
      parent_colony_key: null,
      experimental_unit_type: null,
      experimental_unit_id: null,
      reason: "Field label",
    },
  ]);
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/projects/field-project/ecology/organisms"),
    expect.anything(),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Longitudinal candidates" }),
  );
  expect(await screen.findByText("No comparable timepoints")).toBeVisible();
  expect(screen.getByText(/Scientist review required/i)).toBeVisible();
  expect(
    screen.getByRole("link", { name: "Measurements CSV" }),
  ).toHaveAttribute(
    "href",
    expect.stringContaining(
      "/projects/field-project/ecology/calibrated-measurement-candidates/measurements.csv",
    ),
  );
  client.clear();
});
