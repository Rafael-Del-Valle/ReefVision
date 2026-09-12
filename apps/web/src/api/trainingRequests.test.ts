import { afterEach, describe, expect, it, vi } from "vitest";

import { getModelHubBootstrap, getTrainingRuns } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("training and model hub requests", () => {
  it("bypasses HTTP caches on each training poll", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(Date, "now").mockReturnValueOnce(1000).mockReturnValueOnce(3000);
    const signal = new AbortController().signal;

    await getTrainingRuns("project-1", signal);
    await getTrainingRuns("project-1", signal);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      expect.stringMatching(/\/projects\/project-1\/training-runs\?poll=1000$/),
      expect.objectContaining({
        cache: "no-store",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringMatching(/\/projects\/project-1\/training-runs\?poll=3000$/),
      expect.objectContaining({
        cache: "no-store",
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("exports a callable model hub bootstrap request with the project route", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;
    await getModelHubBootstrap("project-1", signal);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/projects\/project-1\/model-hub\/bootstrap$/),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
