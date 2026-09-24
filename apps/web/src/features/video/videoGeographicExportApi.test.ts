import { describe, expect, it } from "vitest";

import { videoGeographicExportUrl } from "./videoGeographicExportApi";

function parsed(url: string): URL {
  return new URL(url, "http://reefvision.test");
}

describe("videoGeographicExportUrl", () => {
  it("builds a whole-video GeoJSON export URL", () => {
    const url = parsed(videoGeographicExportUrl("video 1", "geojson"));

    expect(url.pathname).toContain("/videos/video%201/geographic-export");
    expect(url.searchParams.get("format")).toBe("geojson");
    expect(url.searchParams.has("track_id")).toBe(false);
  });

  it("adds the selected track filter without altering the video", () => {
    const url = parsed(videoGeographicExportUrl("video-1", "csv", "track/one"));

    expect(url.pathname).toContain("/videos/video-1/geographic-export");
    expect(url.searchParams.get("format")).toBe("csv");
    expect(url.searchParams.get("track_id")).toBe("track/one");
  });

  it("omits a blank track filter", () => {
    const url = parsed(videoGeographicExportUrl("video-1", "geojson", "   "));

    expect(url.searchParams.has("track_id")).toBe(false);
  });
});
