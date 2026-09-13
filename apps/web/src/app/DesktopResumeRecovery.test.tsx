import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../runtime", () => ({
  getRuntimeContext: vi.fn(),
}));

import { getRuntimeContext } from "../runtime";
import { performDesktopResumeRecovery } from "./DesktopResumeRecovery";

describe("DesktopResumeRecovery", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("does nothing outside desktop mode", async () => {
    vi.mocked(getRuntimeContext).mockReturnValue({
      apiBaseUrl: "http://127.0.0.1:8000/api/v1",
      dataDir: "",
      desktopMode: false,
    });

    const fetchImpl = vi.fn<typeof fetch>();
    const queryClient = new QueryClient();

    const recovered = await performDesktopResumeRecovery(queryClient, {
      fetchImpl,
      attempts: 1,
      retryDelayMs: 0,
    });

    expect(recovered).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("health-checks the desktop backend and refreshes active state", async () => {
    vi.mocked(getRuntimeContext).mockReturnValue({
      apiBaseUrl: "http://127.0.0.1:40123/api/v1",
      dataDir: "C:/ReefVisionData",
      desktopMode: true,
    });

    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response("{}", { status: 200 }));

    const queryClient = new QueryClient();
    const resumeSpy = vi
      .spyOn(queryClient, "resumePausedMutations")
      .mockResolvedValue(undefined);
    const refetchSpy = vi
      .spyOn(queryClient, "refetchQueries")
      .mockResolvedValue();

    const recovered = await performDesktopResumeRecovery(queryClient, {
      fetchImpl,
      attempts: 1,
      healthTimeoutMs: 100,
      retryDelayMs: 0,
    });

    expect(recovered).toBe(true);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:40123/api/v1/health",
      expect.objectContaining({
        cache: "no-store",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(resumeSpy).toHaveBeenCalledOnce();
    expect(refetchSpy).toHaveBeenCalledWith({ type: "active" });
  });

  it("retries backend health before declaring recovery successful", async () => {
    vi.mocked(getRuntimeContext).mockReturnValue({
      apiBaseUrl: "http://127.0.0.1:40123/api/v1",
      dataDir: "C:/ReefVisionData",
      desktopMode: true,
    });

    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));

    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "resumePausedMutations").mockResolvedValue(undefined);
    vi.spyOn(queryClient, "refetchQueries").mockResolvedValue();

    const recovered = await performDesktopResumeRecovery(queryClient, {
      fetchImpl,
      attempts: 2,
      healthTimeoutMs: 100,
      retryDelayMs: 0,
    });

    expect(recovered).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
