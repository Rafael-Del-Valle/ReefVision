import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "http://127.0.0.1:4567/api/v1",
}));

import { generatePolygonFill, rasterMaskContentUrl } from "./rasterMaskApi";

afterEach(() => vi.unstubAllGlobals());

it("requests read-only polygon geometry from the runtime API", async () => {
  const points = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
  ];
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ points })));
  vi.stubGlobal("fetch", fetchMock);
  const signal = new AbortController().signal;
  expect(
    await generatePolygonFill(
      "image-1",
      { seed: { x: 2, y: 3 }, tolerance: 12 },
      signal,
    ),
  ).toEqual({ points });
  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:4567/api/v1/images/image-1/polygon-fill",
    expect.objectContaining({
      signal,
      method: "POST",
      body: JSON.stringify({ seed: { x: 2, y: 3 }, tolerance: 12 }),
    }),
  );
});

it.each([
  {
    body: JSON.stringify({ detail: "Fill contains holes" }),
    message: "Fill contains holes",
  },
  { body: "unavailable", message: "Polygon Fill failed with HTTP 400" },
])("reports fill API failures: $message", async ({ body, message }) => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(body, { status: 400 })),
  );
  await expect(
    generatePolygonFill("image-1", { seed: { x: 0, y: 0 }, tolerance: 0 }),
  ).rejects.toThrow(message);
});

describe("rasterMaskContentUrl", () => {
  it("uses the runtime API base and a revision cache key", () => {
    expect(rasterMaskContentUrl({ id: "mask id/1", revision: 4 })).toBe(
      "http://127.0.0.1:4567/api/v1/mask-annotations/mask%20id%2F1/content?revision=4",
    );
  });
});
