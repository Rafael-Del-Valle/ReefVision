import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Scientific3DCalibrationValidation } from "./Scientific3DCalibrationValidation";
import * as api from "./videoScienceApi";
import type { MetricVideoDepth3DResult } from "./videoScienceApi";

vi.mock("./videoScienceApi", async () => {
  const actual =
    await vi.importActual<typeof import("./videoScienceApi")>(
      "./videoScienceApi",
    );
  return {
    ...actual,
    validateMetricDepth3DCalibration: vi.fn(),
  };
});

const baseResult = {
  depth_tier: "model_estimated_metric",
  calibration_validation: undefined,
  analytics: {
    tracks: [
      {
        track_id: "track-1",
        track_number: 1,
        label_class_id: "fish",
        points: [
          { frame: 0, z: 1.0 },
          { frame: 1, z: 1.02 },
          { frame: 2, z: 1.04 },
          { frame: 3, z: 1.08 },
          { frame: 4, z: 1.12 },
        ],
      },
    ],
  },
} as unknown as MetricVideoDepth3DResult;

describe("Scientific3DCalibrationValidation", () => {
  it("requires explicit independent underwater confirmations", () => {
    render(
      <Scientific3DCalibrationValidation
        videoId="video-1"
        jobId="job-1"
        result={baseResult}
        onResultUpdated={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Promote model-estimated depth to calibrated metric"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Validate physical depth" }),
    ).toBeDisabled();
  });

  it("updates the result after a passing independent validation", async () => {
    const updated = {
      ...baseResult,
      depth_tier: "calibrated_metric",
      calibration_validation: {
        qualified: true,
        sample_count: 5,
        distinct_frame_count: 5,
        reference_depth_span_m: 0.12,
        rmse_m: 0.01,
        mean_relative_error: 0.01,
      },
    } as unknown as MetricVideoDepth3DResult;
    vi.mocked(api.validateMetricDepth3DCalibration).mockResolvedValue(updated);
    const onResultUpdated = vi.fn();

    render(
      <Scientific3DCalibrationValidation
        videoId="video-1"
        jobId="job-1"
        result={baseResult}
        onResultUpdated={onResultUpdated}
      />,
    );

    fireEvent.change(screen.getByLabelText("Independent reference source"), {
      target: { value: "calibrated stereo rig" },
    });
    fireEvent.change(screen.getByLabelText("Reference measurement method"), {
      target: { value: "stereo triangulation" },
    });
    fireEvent.change(screen.getByLabelText("Optical setup description"), {
      target: { value: "same camera and flat-port housing underwater" },
    });
    fireEvent.change(screen.getByLabelText("Independent reference depths"), {
      target: {
        value:
          "track-1,0,1.00\ntrack-1,1,1.02\ntrack-1,2,1.04\n" +
          "track-1,3,1.08\ntrack-1,4,1.12",
      },
    });
    for (const checkbox of screen.getAllByRole("checkbox")) {
      fireEvent.click(checkbox);
    }
    fireEvent.click(
      screen.getByRole("button", { name: "Validate physical depth" }),
    );

    await waitFor(() => expect(onResultUpdated).toHaveBeenCalledWith(updated));
    expect(
      await screen.findByText(
        "Validation passed. This run is now calibrated metric.",
      ),
    ).toBeInTheDocument();
  });
});
