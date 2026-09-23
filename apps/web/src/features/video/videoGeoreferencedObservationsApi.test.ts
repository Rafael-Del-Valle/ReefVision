import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getFrameGeoreferencedObservations,
  getGeoreferencedObservation,
  getTrackGeoreferencedObservations,
  getVideoGeoreferencedObservations,
} from "./videoGeoreferencedObservationsApi";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function listResponse() {
  return {
    items: [],
    count: 0,
  };
}

describe("georeferenced observation API", () => {
  it("loads video observations with optional track and frame filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(listResponse()), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    vi.stubGlobal("fetch", fetchMock);

    const signal = new AbortController().signal;

    await getVideoGeoreferencedObservations(
      "video one",
      {
        trackId: "track/7",
        frameIndex: 42,
      },
      signal,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(url).toContain("/videos/video%20one/georeferenced-observations?");

    expect(url).toContain("track_id=track%2F7");

    expect(url).toContain("frame_index=42");

    expect(init).toEqual(
      expect.objectContaining({
        signal,
        cache: "no-store",
      }),
    );
  });

  it("loads observations for a track", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(listResponse()), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    vi.stubGlobal("fetch", fetchMock);

    await getTrackGeoreferencedObservations("track one");

    expect(fetchMock.mock.calls[0]?.[0]).toMatch(
      /\/video-tracks\/track%20one\/georeferenced-observations$/,
    );
  });

  it("loads observations for one frame", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(listResponse()), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    vi.stubGlobal("fetch", fetchMock);

    await getFrameGeoreferencedObservations("video-1", 123);

    expect(fetchMock.mock.calls[0]?.[0]).toMatch(
      /\/videos\/video-1\/frames\/123\/georeferenced-observations$/,
    );
  });

  it("loads full observation detail only by observation id", async () => {
    const payload = {
      id: "observation-1",
      frame_index: 12,
    };

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getGeoreferencedObservation("observation one"),
    ).resolves.toEqual(payload);

    expect(fetchMock.mock.calls[0]?.[0]).toMatch(
      /\/georeferenced-observations\/observation%20one$/,
    );
  });

  it("surfaces the backend detail message on request failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Geo-referenced observation not found",
        }),
        {
          status: 404,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    vi.stubGlobal("fetch", fetchMock);

    await expect(getGeoreferencedObservation("missing")).rejects.toThrow(
      "Geo-referenced observation not found",
    );
  });
});
