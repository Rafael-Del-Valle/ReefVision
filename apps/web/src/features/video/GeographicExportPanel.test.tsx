import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GeographicExportPanel } from "./GeographicExportPanel";

describe("GeographicExportPanel", () => {
  it("shows whole-video GeoJSON and CSV exports", () => {
    render(<GeographicExportPanel videoId="video 1" selectedTrackId={null} />);

    const geojson = screen.getByRole("link", {
      name: "Download whole-video GeoJSON",
    });

    const csv = screen.getByRole("link", {
      name: "Download whole-video CSV",
    });

    expect(geojson.getAttribute("href")).toContain(
      "/videos/video%201/geographic-export",
    );
    expect(geojson.getAttribute("href")).toContain("format=geojson");

    expect(csv.getAttribute("href")).toContain("format=csv");

    expect(
      screen.queryByRole("link", {
        name: "Download selected-track GeoJSON",
      }),
    ).not.toBeInTheDocument();
  });

  it("adds the explicit selected-track filter", () => {
    render(
      <GeographicExportPanel videoId="video-1" selectedTrackId="track/one" />,
    );

    const geojson = screen.getByRole("link", {
      name: "Download selected-track GeoJSON",
    });

    const csv = screen.getByRole("link", {
      name: "Download selected-track CSV",
    });

    expect(geojson.getAttribute("href")).toContain("format=geojson");
    expect(geojson.getAttribute("href")).toContain("track_id=track%2Fone");

    expect(csv.getAttribute("href")).toContain("format=csv");
    expect(csv.getAttribute("href")).toContain("track_id=track%2Fone");
  });

  it("does not expose download links without a selected video", () => {
    render(<GeographicExportPanel videoId={null} selectedTrackId="track-1" />);

    expect(
      screen.getByText("Select a video to enable geographic exports."),
    ).toBeInTheDocument();

    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });
});
