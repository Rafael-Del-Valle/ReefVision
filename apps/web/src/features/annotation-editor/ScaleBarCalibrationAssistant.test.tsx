import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalibrationAssistant } from "./CalibrationAssistant";
import {
  detectScaleBarCalibration,
  getMeasurementCalibrationProfiles,
  updateMeasurementCalibration,
} from "./maskMeasurementsApi";

vi.mock("./maskMeasurementsApi", () => ({
  applyMeasurementCalibrationProfile: vi.fn(),
  detectMarkerCalibration: vi.fn(),
  detectRulerCalibration: vi.fn(),
  detectScaleBarCalibration: vi.fn(),
  getMeasurementCalibrationProfiles: vi.fn(),
  updateMeasurementCalibration: vi.fn(),
}));

function renderAssistant() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onApplied = vi.fn().mockResolvedValue(undefined);
  render(
    <QueryClientProvider client={queryClient}>
      <CalibrationAssistant
        projectId="project-1"
        imageId="image-1"
        defaultUnit="mm"
        onApplied={onApplied}
      />
    </QueryClientProvider>,
  );
  return { onApplied };
}

describe("CalibrationAssistant scale bar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getMeasurementCalibrationProfiles).mockResolvedValue([]);
    vi.mocked(detectScaleBarCalibration).mockResolvedValue({
      image_id: "image-1",
      method: "automatic_scale_bar",
      orientation: "horizontal",
      roi: { x_min: 0, y_min: 100, x_max: 300, y_max: 150 },
      bar_start_pixels: [55, 127.5],
      bar_end_pixels: [206, 127.5],
      bar_length_pixels: 151,
      bar_thickness_pixels: 6,
      polarity: "dark",
      continuity_score: 1,
      contrast_score: 1,
      confidence: 0.96,
      label_text: null,
      unit_inferred: false,
      reference_length_required: true,
      warnings: ["Confirm the reference length and unit before applying."],
    });
    vi.mocked(updateMeasurementCalibration).mockResolvedValue({
      image_id: "image-1",
      calibrated: true,
      distance_per_pixel: 10 / 151,
      unit: "mm",
      source: "automatic_scale_bar",
      reference_length: 10,
      reference_pixel_length: 151,
      default_depth: null,
      notes: null,
      confidence: 0.96,
      detector: "reefvision-scale-bar-geometry-v1",
      profile_name: null,
      profile_source_image_id: null,
      camera_signature: null,
      perspective_homography: null,
      reference_plane_only: false,
    });
  });

  it("detects scale-bar geometry but requires physical review before applying", async () => {
    const { onApplied } = renderAssistant();

    fireEvent.click(screen.getByText("Detect digital scale bar"));
    fireEvent.click(screen.getByRole("button", { name: "Detect scale bar" }));

    expect(await screen.findByText("151.000 px")).toBeInTheDocument();
    expect(screen.getByText("96%")).toBeInTheDocument();
    expect(updateMeasurementCalibration).not.toHaveBeenCalled();

    fireEvent.change(
      screen.getByLabelText("Known physical length printed for this scale bar"),
      { target: { value: "10" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Apply reviewed scale bar" }),
    );

    await waitFor(() =>
      expect(updateMeasurementCalibration).toHaveBeenCalledWith(
        "image-1",
        expect.objectContaining({
          distance_per_pixel: 10 / 151,
          unit: "mm",
          source: "automatic_scale_bar",
          reference_length: 10,
          reference_pixel_length: 151,
          confidence: 0.96,
        }),
      ),
    );
    expect(onApplied).toHaveBeenCalledTimes(1);
  });
});
