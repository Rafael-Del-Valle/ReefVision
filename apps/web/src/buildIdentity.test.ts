import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("ReefVision development identity", () => {
  it("retains the true API version when no development line is configured", async () => {
    vi.stubEnv("VITE_REEFVISION_DEV_LINE", "");
    const { developmentLine, displayVersion } = await import("./buildIdentity");
    expect(developmentLine).toBeNull();
    expect(displayVersion("1.0.2")).toBe("1.0.2");
    expect(displayVersion()).toBe("1.0.2");
  });

  it("marks explicitly configured Vite development builds without modifying the API version", async () => {
    vi.stubEnv("VITE_REEFVISION_DEV_LINE", "1.1.0-dev");
    const { developmentLine, displayVersion } = await import("./buildIdentity");

    if (import.meta.env.DEV) {
      expect(developmentLine).toBe("1.1.0-dev");
      expect(displayVersion("1.0.2")).toBe("1.1.0-dev");
    } else {
      expect(developmentLine).toBeNull();
      expect(displayVersion("1.0.2")).toBe("1.0.2");
    }
  });

  it("ignores arbitrary version overrides and retains real package identity", async () => {
    vi.stubEnv("VITE_REEFVISION_DEV_LINE", "2.0.0");
    const { developmentLine, displayVersion } = await import("./buildIdentity");
    expect(developmentLine).toBeNull();
    expect(displayVersion("1.0.2")).toBe("1.0.2");
  });
});
