import { describe, expect, it, vi } from "vitest";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "http://127.0.0.1:4567/api/v1",
}));

import { rasterMaskContentUrl } from "./rasterMaskApi";

describe("rasterMaskContentUrl", () => {
  it("uses the runtime API base and a revision cache key", () => {
    expect(rasterMaskContentUrl({ id: "mask id/1", revision: 4 })).toBe(
      "http://127.0.0.1:4567/api/v1/mask-annotations/mask%20id%2F1/content?revision=4",
    );
  });
});
