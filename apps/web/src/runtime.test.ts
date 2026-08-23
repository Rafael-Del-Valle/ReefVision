import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

import { invoke } from "@tauri-apps/api/core";

import {
  getApiBaseUrl,
  getRuntimeContext,
  initializeRuntime,
  resetRuntimeForTests,
} from "./runtime";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("runtime", () => {
  beforeEach(() => {
    resetRuntimeForTests();
    vi.restoreAllMocks();
    vi.mocked(invoke).mockReset();
    delete window.__TAURI_INTERNALS__;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("rejects standalone browser runtime", async () => {
    await expect(initializeRuntime()).rejects.toThrow(
      "ReefVision is a desktop application",
    );
    expect(getApiBaseUrl()).toBe("");
    expect(getRuntimeContext().desktopMode).toBe(false);
  });

  it("loads the desktop API base URL from Tauri and waits for health", async () => {
    window.__TAURI_INTERNALS__ = {};
    vi.mocked(invoke).mockResolvedValue({
      apiBaseUrl: "http://127.0.0.1:40123/api/v1",
      dataDir: "C:/ReefVisionData",
      desktopMode: true,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ status: "ok", version: "1.6.0" }),
    );

    await initializeRuntime();

    expect(invoke).toHaveBeenCalledWith("desktop_context");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:40123/api/v1/health",
    );
    expect(getApiBaseUrl()).toBe("http://127.0.0.1:40123/api/v1");
    expect(getRuntimeContext()).toEqual({
      apiBaseUrl: "http://127.0.0.1:40123/api/v1",
      dataDir: "C:/ReefVisionData",
      desktopMode: true,
    });
  });

  it("surfaces a friendly startup error when the desktop health check never connects", async () => {
    vi.useFakeTimers();
    window.__TAURI_INTERNALS__ = {};
    vi.mocked(invoke).mockResolvedValue({
      apiBaseUrl: "http://127.0.0.1:40123/api/v1",
      dataDir: "C:/ReefVisionData",
      desktopMode: true,
    });
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new TypeError("Failed to fetch"),
    );

    const runtimePromise = initializeRuntime();
    const rejection = expect(runtimePromise).rejects.toThrow(
      "ReefVision could not reach its local desktop API",
    );
    await vi.advanceTimersByTimeAsync(15_500);
    await rejection;
  });
});
