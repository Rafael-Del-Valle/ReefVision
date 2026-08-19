import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalibrationAssistant } from "./CalibrationAssistant";
import {
  detectRulerCalibration,
  getMeasurementCalibrationProfiles,
  updateMeasurementCalibration,
} from "./maskMeasurementsApi";

vi.mock("./maskMeasurementsApi", () => ({
  applyMeasurementCalibrationProfile: vi.fn(),
  detectMarkerCalibration: vi.fn(),
  detectRulerCalibration: vi.fn(),
  getMeasurementCalibrationProfiles: vi.fn(),
  updateMeasurementCalibration: vi.fn(),
}));

function renderAssistant(imageId = "image-1") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onApplied = vi.fn().mockResolvedValue(undefined);
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <CalibrationAssistant
        projectId="project-1"
        imageId={imageId}
        defaultUnit="mm"
        onApplied={onApplied}
      />
    </QueryClientProvider>,
  );
  return { ...rendered, queryClient, onApplied };
}

describe("CalibrationAssistant", () => {
  beforeEach(() => {
    vi.mocked(detectRulerCalibration).mockReset();
    vi.mocked(getMeasurementCalibrationProfiles).mockReset();
    vi.mocked(updateMeasurementCalibration).mockReset();
    vi.mocked(getMeasurementCalibrationProfiles).mockResolvedValue([]);
    vi.mocked(detectRulerCalibration).mockResolvedValue({
      image_id: "image-1",
      method: "automatic_ruler",
      orientation: "horizontal",
      roi: { x_min: 0, y_min: 0, x_max: 200, y_max: 60 },
      base_interval_pixels: 20,
      major_interval_pixels: 100,
      tick_positions_pixels: [20, 40, 60, 80, 100],
      interval_count: 4,
      interval_coefficient_of_variation: 0.01,
      confidence: 0.92,
      unit_inferred: false,
      reference_length_required: true,
      warnings: [
        "The detector estimates repeating ruler ticks only; it does not infer physical units.",
      ],
    });
    vi.mocked(updateMeasurementCalibration).mockResolvedValue({
      image_id: "image-1",
      calibrated: true,
      distance_per_pixel: 0.5,
      unit: "mm",
      source: "automatic_ruler",
      reference_length: 10,
      reference_pixel_length: 20,
      default_depth: null,
      notes: null,
      confidence: 0.92,
      detector: "reefvision-ruler-periodicity-v1",
      profile_name: null,
      profile_source_image_id: null,
      camera_signature: null,
      perspective_homography: null,
      reference_plane_only: false,
    });
  });

  it("requires researcher-supplied physical interval before applying ruler evidence", async () => {
    const { onApplied } = renderAssistant();

    fireEvent.click(screen.getByText("Detect ruler spacing"));
    fireEvent.click(screen.getByRole("button", { name: "Detect ruler" }));

    expect(await screen.findByText("20.000 px")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
    expect(updateMeasurementCalibration).not.toHaveBeenCalled();

    fireEvent.change(
      screen.getByLabelText("Known physical length of one detected interval"),
      { target: { value: "10" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Apply reviewed ruler scale" }),
    );

    await waitFor(() =>
      expect(updateMeasurementCalibration).toHaveBeenCalledWith(
        "image-1",
        expect.objectContaining({
          distance_per_pixel: 0.5,
          unit: "mm",
          source: "automatic_ruler",
          reference_length: 10,
          reference_pixel_length: 20,
          confidence: 0.92,
        }),
      ),
    );
    expect(onApplied).toHaveBeenCalledTimes(1);
  });

  it("clears detected evidence when the active image changes", async () => {
    const { rerender, queryClient } = renderAssistant();

    fireEvent.click(screen.getByText("Detect ruler spacing"));
    fireEvent.click(screen.getByRole("button", { name: "Detect ruler" }));
    expect(await screen.findByText("20.000 px")).toBeInTheDocument();

    rerender(
      <QueryClientProvider client={queryClient}>
        <CalibrationAssistant
          projectId="project-1"
          imageId="image-2"
          defaultUnit="mm"
          onApplied={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.queryByText("20.000 px")).not.toBeInTheDocument(),
    );
  });
});
