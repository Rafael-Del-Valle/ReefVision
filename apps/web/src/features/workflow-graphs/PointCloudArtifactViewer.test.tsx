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

  it("fails closed on contradictory scientific verification or biological measurements", () => {
    const contradictoryArtifacts = [
      { ...validArtifact, provenance: null },
      { ...validArtifact, provenance: { calibration_verified: true } },
      {
        ...validArtifact,
        provenance: {
          calibration_verified: false,
          coordinate_registration_verified: true,
        },
      },
      { ...validArtifact, measurement_status: "scientist_verified" },
      { ...validArtifact, surface_area_m2: 0.25 },
      { ...validArtifact, branch_length_m: 0.5 },
    ];
    for (const artifact of contradictoryArtifacts) {
      expect(parsePointCloudRenderArtifact(artifact)).toBeNull();
    }
    // An explicitly unregistered, unverified saved preview remains displayable.
    expect(parsePointCloudRenderArtifact(validArtifact)).not.toBeNull();
  });

  it("renders reviewed source-index chord metadata as provisional straight lines", () => {
    const artifact = {
      ...validArtifact,
      selected_point_chords: [
        {
          point_indices: [0, 2],
          chord_distance_m: 1,
          scale_uncertainty_m: 0.1,
        },
      ],
    };
    const before = JSON.stringify(artifact);
    render(<PointCloudArtifactViewer artifact={artifact} />);
    expect(screen.getByText(/Source-point chord 0–2:/)).toHaveTextContent(
      "1.0000 m",
    );
    expect(screen.getByText(/Source-point chord 0–2:/)).toHaveTextContent(
      "scale-only ±0.1000 m",
    );
    expect(screen.getByText(/Source-point chord 0–2:/)).toHaveTextContent(
      "not anatomical branch length",
    );
    expect(JSON.stringify(artifact)).toBe(before);
  });

  it("fails closed on contradictory point-pair indices or distances", () => {
    for (const chord of [
      { point_indices: [0, 0], chord_distance_m: 0 },
      { point_indices: [0, 3], chord_distance_m: 1 },
      { point_indices: [0, 2], chord_distance_m: Number.NaN },
      { point_indices: [0, 2], chord_distance_m: -1 },
      { point_indices: [0, 2], chord_distance_m: 1, scale_uncertainty_m: -1 },
    ]) {
      expect(
        parsePointCloudRenderArtifact({
          ...validArtifact,
          selected_point_chords: [chord],
        }),
      ).toBeNull();
    }
  });

  it("cross-checks sampled chord endpoints without guessing missing source points", () => {
    const contradictory = {
      ...validArtifact,
      selected_point_chords: [{ point_indices: [0, 2], chord_distance_m: 2 }],
    };
    // Both displayed endpoints are exactly 1 m apart in the calibrated frame.
    expect(parsePointCloudRenderArtifact(contradictory)).toBeNull();
    const decimated = {
      ...contradictory,
      point_count: 513,
      preview_point_indices: [0, 256, 512],
    };
    // Original point 2 is absent from the visualization sample. Do not infer
    // its coordinates or reject a full-cloud measurement without evidence.
    expect(parsePointCloudRenderArtifact(decimated)).not.toBeNull();
    expect(
      parsePointCloudRenderArtifact({
        ...validArtifact,
        selected_point_chords: [{ point_indices: [0, 2], chord_distance_m: 1 }],
      }),
    ).not.toBeNull();
  });

  it("does not falsely reject chords lost to large-offset display rounding", () => {
    const rounded = {
      ...validArtifact,
      preview_points_in_source_frame_m: [
        [1e15, 0, 0],
        [1e15, 1, 0],
        [1e15, 0, 0],
      ],
      axis_aligned_min_in_source_frame_m: [1e15, 0, 0],
      axis_aligned_max_in_source_frame_m: [1e15, 1, 0],
      selected_point_chords: [
        { point_indices: [0, 2], chord_distance_m: 0.01 },
      ],
    };
    // The full-resolution input may resolve a chord lost after scaling and
    // rounding very large source-frame coordinates for visualization.
    expect(parsePointCloudRenderArtifact(rounded)).not.toBeNull();
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
