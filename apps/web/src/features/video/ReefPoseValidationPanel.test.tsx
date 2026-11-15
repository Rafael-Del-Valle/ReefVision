import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReefPoseValidationPanel } from "./ReefPoseValidationPanel";

afterEach(() => vi.unstubAllGlobals());

it("shows recovery instructions while preserving the interrupted validation", async () => {
  const message =
    "Open the original project or restore its backup with the original recordings.";
  const fetch = vi.fn(async (input: string) => {
    if (input.endsWith("/retry")) {
      return Response.json({ detail: message }, { status: 409 });
    }
    if (input.endsWith("/reefpose-validations")) {
      return Response.json([
        {
          id: "interrupted-job",
          status: "cancelled",
          request_json: { payload: { split: "test" } },
        },
      ]);
    }
    return Response.json([]);
  });
  vi.stubGlobal("fetch", fetch);
  const query = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={query}>
      <ReefPoseValidationPanel projectId="project-1" />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("ReefPose scientific validation"));
  await screen.findByRole("option", { name: /interrupted-job/ });
  fireEvent.change(screen.getByLabelText("Validation runs"), {
    target: { value: "interrupted-job" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Retry saved validation" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.getByLabelText("Validation runs")).toHaveValue(
    "interrupted-job",
  );
  expect(fetch).toHaveBeenCalledWith(
    expect.stringMatching(/interrupted-job\/retry$/),
    expect.objectContaining({ method: "POST" }),
  );
});
