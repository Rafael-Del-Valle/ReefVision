import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "../../api/client";
import { ScientificNodeControls } from "./ScientificNodeControls";

const comparison = {
  id: "comparison",
  stale: false,
  snapshot: { options: { name: "Baseline" } },
};

function renderControls(type: string, initial: Record<string, unknown> = {}) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Fixture() {
    const [config, setConfig] = useState(initial);
    return (
      <>
        <ScientificNodeControls
          nodeType={type}
          projectId="local-study"
          parameters={config}
          onChange={setConfig}
        />
        <output>{JSON.stringify(config)}</output>
      </>
    );
  }
  return render(
    <QueryClientProvider client={cache}>
      <Fixture />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

it("replays a current project comparison and clears the calculation choice", async () => {
  const request = vi.spyOn(api, "request").mockImplementation(async (path) => {
    expect(path).toContain("/projects/local-study/");
    return (path.includes("/static-comparisons") ? [] : [comparison]) as never;
  });
  renderControls("scientific_comparison", {
    configuration: { name: "Old settings" },
  });
  fireEvent.change(screen.getByLabelText("Operation"), {
    target: { value: "comparison_id" },
  });
  await screen.findByRole("option", { name: "Baseline" });
  fireEvent.change(screen.getByLabelText("Saved comparison"), {
    target: { value: "comparison" },
  });
  expect(screen.getByRole("status").textContent).toContain(
    '"comparison_id":"comparison"',
  );
  expect(screen.getByRole("status").textContent).not.toContain(
    '"configuration"',
  );
  expect(request).toHaveBeenCalled();
});

it("uses the standalone acquisition contract and validates clipping bands", async () => {
  vi.spyOn(api, "getDatasetVersions").mockResolvedValue([]);
  renderControls("image_acquisition_quality");
  fireEvent.change(screen.getByLabelText("Dark luma maximum"), {
    target: { value: "252" },
  });
  expect(screen.getByRole("alert")).toHaveTextContent("Dark luma maximum");
  expect(screen.getByRole("status").textContent).toContain(
    '"dark_luma_max":252',
  );
});
