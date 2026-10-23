import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  PointCloudArtifactViewer,
  parsePointCloudRenderArtifact,
} from "./PointCloudArtifactViewer";

const validArtifact = {
  point_count: 3,
  preview_point_indices: [0, 1, 2],
  preview_points_in_source_frame_m: [
    [0, 0, 0],
    [1, 0, 0],
    [0, 1, 0],
  ],
  preview_point_colors_rgb_uint8: [
    [255, 0, 0],
    [0, 255, 0],
    [0, 0, 255],
  ],
  axis_aligned_min_in_source_frame_m: [0, 0, 0],
  axis_aligned_max_in_source_frame_m: [1, 1, 0],
  measurement_status: "caller_supplied_unverified",
  surface_area_m2: null,
  branch_length_m: null,
  provenance: { calibration_verified: false },
};

describe("PointCloudArtifactViewer", () => {
  it("rotates and resets saved RGB points without changing the scientific artifact", () => {
    const before = JSON.stringify(validArtifact);
    const { container } = render(
      <PointCloudArtifactViewer artifact={validArtifact} />,
    );
    const point = container.querySelector('[data-source-point-index="1"]');
    expect(point).not.toBeNull();
    expect(point?.getAttribute("fill")).toBe("rgb(0, 255, 0)");
    const originalX = point?.getAttribute("cx");
    fireEvent.change(screen.getByRole("slider", { name: "Point yaw" }), {
      target: { value: "90" },
    });
    expect(point?.getAttribute("cx")).not.toBe(originalX);
    fireEvent.click(screen.getByRole("button", { name: "Reset point view" }));
    expect(point?.getAttribute("cx")).toBe(originalX);
    expect(screen.getByText(/Point coverage:/)).toHaveTextContent("100.0%");
    expect(screen.getByText(/Point coverage:/)).toHaveTextContent(
      "Uncalibrated RGB display",
    );
    expect(JSON.stringify(validArtifact)).toBe(before);
    expect(screen.getByText(/RGB is display metadata/)).toHaveTextContent(
      "not biological condition",
    );
  });

  it("rejects malformed points, RGB, indices, and bounds rather than drawing them", () => {
    expect(
      parsePointCloudRenderArtifact({
        ...validArtifact,
        preview_point_indices: [0, 0, 2],
      }),
    ).toBeNull();
    expect(
      parsePointCloudRenderArtifact({
        ...validArtifact,
        preview_point_colors_rgb_uint8: [[256, 0, 0]],
      }),
    ).toBeNull();
    expect(
      parsePointCloudRenderArtifact({
        ...validArtifact,
        preview_points_in_source_frame_m: [
          [0, 0, 0],
          [Number.NaN, 0, 0],
          [0, 1, 0],
        ],
      }),
    ).toBeNull();
    expect(
      parsePointCloudRenderArtifact({
        ...validArtifact,
        axis_aligned_max_in_source_frame_m: [0.5, 1, 0],
      }),
    ).toBeNull();
    expect(
      parsePointCloudRenderArtifact({
        ...validArtifact,
        point_count: 2001,
      }),
    ).toBeNull();
    render(
      <PointCloudArtifactViewer
        artifact={{ ...validArtifact, preview_point_indices: [0, 0, 2] }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "no valid bounded 3D display data",
    );
  });

  it("renders decimated colorless samples with preserved original indices", () => {
    const { container } = render(
      <PointCloudArtifactViewer
        artifact={{
          ...validArtifact,
          point_count: 513,
          preview_point_indices: [0, 256, 512],
          preview_point_colors_rgb_uint8: null,
        }}
      />,
    );
    expect(
      container.querySelector('[data-source-point-index="512"]'),
    ).not.toBeNull();
    expect(screen.getByText(/Point coverage:/)).toHaveTextContent("0.6%");
    expect(screen.getByText(/Point coverage:/)).toHaveTextContent("No RGB");
  });
});
