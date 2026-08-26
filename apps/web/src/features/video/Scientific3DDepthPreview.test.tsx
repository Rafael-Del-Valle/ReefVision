import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Scientific3DDepthPreview } from "./Scientific3DDepthPreview";
import type { MetricVideoDepth3DResult } from "./videoScienceApi";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "http://127.0.0.1:8765/api/v1",
}));

const result = {
  depth_stack_shape: [3, 60, 100],
  decoded_frame_count: 3,
  depth_tier: "model_estimated_metric",
  depth_preview: {
    display_min_m: 1.2,
    display_max_m: 4.8,
    scaling: "global_positive_depth_percentile_2_98",
    invalid_pixels: "finite_positive_depth_only",
    colorization_only: true,
  },
} as unknown as MetricVideoDepth3DResult;

describe("Scientific3DDepthPreview", () => {
  it("shows a fixed whole-stack metric-depth scale", () => {
    render(
      <Scientific3DDepthPreview
        videoId="video-1"
        jobId="job-1"
        result={result}
      />,
    );

    expect(
      screen.getByText("Raw Video Depth Anything output"),
    ).toBeInTheDocument();
    expect(screen.getByText(/1.200 m/)).toBeInTheDocument();
    expect(screen.getByText(/4.800 m/)).toBeInTheDocument();
    expect(
      screen.getByText(/Whole-stack positive-depth 2nd–98th percentiles/),
    ).toBeInTheDocument();
  });

  it("changes the requested depth frame without changing the result tier", () => {
    render(
      <Scientific3DDepthPreview
        videoId="video-1"
        jobId="job-1"
        result={result}
      />,
    );

    const image = screen.getByAltText("Metric depth preview frame 0");
    expect(image).toHaveAttribute(
      "src",
      expect.stringContaining("depth-preview?frame=0"),
    );

    fireEvent.change(screen.getByLabelText("Depth preview frame"), {
      target: { value: "2" },
    });

    expect(screen.getByAltText("Metric depth preview frame 2")).toHaveAttribute(
      "src",
      expect.stringContaining("depth-preview?frame=2"),
    );
    expect(screen.getByText("model estimated metric")).toBeInTheDocument();
  });
});
