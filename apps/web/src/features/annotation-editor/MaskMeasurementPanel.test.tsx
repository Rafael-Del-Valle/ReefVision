import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAdvancedMaskMeasurements,
  getMaskMeasurementProfile,
  getMaskMeasurements,
  getMeasurementCalibration,
  updateMeasurementCalibration,
} from "./maskMeasurementsApi";
import { MaskMeasurementPanel } from "./MaskMeasurementPanel";
import type { EditorMaskAnnotation } from "./types";

vi.mock("./maskMeasurementsApi", () => ({
  clearMeasurementCalibration: vi.fn(),
  getAdvancedMaskMeasurements: vi.fn(),
  getMaskMeasurementProfile: vi.fn(),
  getMaskMeasurements: vi.fn(),
  getMeasurementCalibration: vi.fn(),
  measurementExportUrl: vi.fn(
    (projectId: string, format: string) => `/exports/${projectId}/${format}`,
  ),
  updateMaskMeasurementProfile: vi.fn(),
  updateMeasurementCalibration: vi.fn(),
}));

const selectedMask: EditorMaskAnnotation = {
  id: "mask-1",
  label_class_id: "class-1",
  geometry_kind: "polygon",
  points: [
    { x: 10, y: 10 },
    { x: 30, y: 10 },
    { x: 30, y: 25 },
    { x: 10, y: 25 },
  ],
  mask_path: null,
  x_min: 10,
  y_min: 10,
  x_max: 30,
  y_max: 25,
  area_pixels: 300,
  source_type: "human",
  persisted: true,
  revision: 2,
};

const basicMeasurement = {
  mask_annotation_id: selectedMask.id,
  image_id: "image-1",
  label_class_id: "class-1",
  geometry_kind: "polygon",
  area_pixels: 300,
  perimeter_pixels: 70,
  centroid_x: 20,
  centroid_y: 17.5,
  x_min: 10,
  y_min: 10,
  x_max: 30,
  y_max: 25,
  contained_box_count: 4,
  contained_box_density_per_1000_pixels: 13.3333,
  filters: {
    label_class_ids: [],
    scientific_names: [],
    state_names: [],
  },
  calibrated: false,
  physical_unit: null,
  distance_per_pixel: null,
  area_physical: null,
  perimeter_physical: null,
  centroid_x_physical: null,
  centroid_y_physical: null,
  contained_box_density_per_square_unit: null,
  centerline_points: [],
  total_linear_extension_pixels: 0,
  total_linear_extension_physical: null,
  surface_area_model: "none" as const,
  surface_area_physical: null,
  surface_area_assumptions: [],
};

function renderPanel(masks: EditorMaskAnnotation[], documentDirty = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MaskMeasurementPanel
        projectId="project-1"
        imageId="image-1"
        labelClasses={[
          {
            id: "class-1",
            name: "Open Swiftia",
            scientific_name: "Swiftia exserta",
            state_name: "open",
          },
        ]}
        selectedMasks={masks}
        documentDirty={documentDirty}
        onRevisionCommitted={vi.fn().mockResolvedValue(undefined)}
      />
    </QueryClientProvider>,
  );
}

describe("MaskMeasurementPanel", () => {
  beforeEach(() => {
    vi.mocked(getAdvancedMaskMeasurements).mockReset();
    vi.mocked(getMaskMeasurements).mockReset();
    vi.mocked(getMeasurementCalibration).mockReset();
    vi.mocked(getMaskMeasurementProfile).mockReset();
    vi.mocked(updateMeasurementCalibration).mockReset();
    vi.mocked(getMeasurementCalibration).mockResolvedValue(null);
    vi.mocked(getMaskMeasurementProfile).mockResolvedValue({
      mask_annotation_id: selectedMask.id,
      image_id: "image-1",
      revision: 2,
      centerline_points: [],
      centerline_length_pixels: 0,
      surface_model: "none",
      depth_value: null,
      diameter_value: null,
      notes: null,
    });
  });

  it("loads scientific measurements for one persisted selected mask", async () => {
    vi.mocked(getMaskMeasurements).mockResolvedValue(basicMeasurement);

    renderPanel([selectedMask]);

    expect(await screen.findByText("300 px²")).toBeInTheDocument();
    expect(screen.getByText("70.00 px")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(
      screen.getByText(/13\.3333 boxes per 1,000 mask pixels/),
    ).toBeInTheDocument();
    expect(getMaskMeasurements).toHaveBeenCalledWith(
      "mask-1",
      {
        label_class_ids: [],
        scientific_names: [],
        state_names: [],
      },
      expect.any(AbortSignal),
    );
  });

  it("calculates calibration from a known reference", async () => {
    vi.mocked(getMaskMeasurements).mockResolvedValue(basicMeasurement);
    vi.mocked(updateMeasurementCalibration).mockResolvedValue({
      image_id: "image-1",
      calibrated: true,
      distance_per_pixel: 0.02,
      unit: "mm",
      source: "known_reference_length",
      reference_length: 10,
      reference_pixel_length: 500,
      default_depth: null,
      notes: null,
    });

    renderPanel([selectedMask]);
    fireEvent.click(screen.getByText("Image calibration"));
    fireEvent.change(screen.getByLabelText("Known reference length"), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByLabelText("Reference pixel length"), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save calibration" }));

    await waitFor(() =>
      expect(updateMeasurementCalibration).toHaveBeenCalledWith("image-1", {
        distance_per_pixel: 0.02,
        unit: "mm",
        source: "known_reference_length",
        reference_length: 10,
        reference_pixel_length: 500,
        default_depth: null,
      }),
    );
  });

  it("calculates advanced shape and skeleton measurements on demand", async () => {
    vi.mocked(getMaskMeasurements).mockResolvedValue(basicMeasurement);
    vi.mocked(getAdvancedMaskMeasurements).mockResolvedValue({
      mask_annotation_id: selectedMask.id,
      image_id: "image-1",
      revision: 2,
      calibrated: false,
      distance_per_pixel: null,
      physical_unit: null,
      shape: {
        area_pixels: 300,
        perimeter_pixels: 70,
        convex_hull_area_pixels: 320,
        solidity: 0.9375,
        circularity: 0.7694,
        compactness: 1.2997,
        feret_max_pixels: 25,
        feret_min_pixels: 15,
        major_axis_pixels: 23,
        minor_axis_pixels: 14,
        orientation_degrees: 12.5,
        bounding_width_pixels: 20,
        bounding_height_pixels: 15,
      },
      skeleton: {
        method: "medial_axis",
        skeleton_pixel_count: 28,
        total_length_pixels: 30.5,
        longest_path_pixels: 24.25,
        endpoint_count: 2,
        junction_count: 1,
        branch_count: 3,
        branch_lengths_pixels: [10, 9, 8],
        pruned_pixels: 0,
        bridged_gaps: 0,
      },
      surface: {
        method: "none",
        area: null,
        unit_squared: null,
        standard_uncertainty: null,
        lower_95: null,
        upper_95: null,
        assumptions: [],
      },
      total_length_physical: null,
      longest_path_physical: null,
      feret_max_physical: null,
      feret_min_physical: null,
      warnings: [],
    });

    renderPanel([selectedMask]);
    fireEvent.click(screen.getByText("Advanced shape and skeleton"));
    fireEvent.click(
      screen.getByRole("button", {
        name: "Calculate advanced measurements",
      }),
    );

    expect(await screen.findByText(/Solidity 0\.9375/)).toBeInTheDocument();
    expect(screen.getByText(/25\.00 px max/)).toBeInTheDocument();
    expect(screen.getByText(/30\.50 px total/)).toBeInTheDocument();
    expect(screen.getByText(/2 endpoints/)).toBeInTheDocument();
    expect(getAdvancedMaskMeasurements).toHaveBeenCalledWith("mask-1", {
      prune_spurs_pixels: 0,
      bridge_gaps_pixels: 0,
      surface_method: "none",
    });
  });

  it("waits for unsaved edits before requesting measurements", () => {
    renderPanel([selectedMask], true);

    expect(
      screen.getByText(/Waiting for the current mask edits to save/),
    ).toBeInTheDocument();
    expect(getMaskMeasurements).not.toHaveBeenCalled();
  });
});
