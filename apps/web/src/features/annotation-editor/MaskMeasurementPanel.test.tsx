import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getMaskMeasurements } from "./maskMeasurementsApi";
import { MaskMeasurementPanel } from "./MaskMeasurementPanel";
import type { EditorMaskAnnotation } from "./types";

vi.mock("./maskMeasurementsApi", () => ({
  getMaskMeasurements: vi.fn(),
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

function renderPanel(masks: EditorMaskAnnotation[], documentDirty = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MaskMeasurementPanel
        selectedMasks={masks}
        documentDirty={documentDirty}
      />
    </QueryClientProvider>,
  );
}

describe("MaskMeasurementPanel", () => {
  beforeEach(() => {
    vi.mocked(getMaskMeasurements).mockReset();
  });

  it("loads scientific measurements for one persisted selected mask", async () => {
    vi.mocked(getMaskMeasurements).mockResolvedValue({
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
    });

    renderPanel([selectedMask]);

    expect(await screen.findByText("300 px²")).toBeInTheDocument();
    expect(screen.getByText("70.00 px")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(
      screen.getByText(/13\.3333 boxes per 1,000 mask pixels/),
    ).toBeInTheDocument();
    expect(getMaskMeasurements).toHaveBeenCalledWith(
      "mask-1",
      expect.any(AbortSignal),
    );
  });

  it("waits for unsaved edits before requesting measurements", () => {
    renderPanel([selectedMask], true);

    expect(
      screen.getByText(/Waiting for the current mask edits to save/),
    ).toBeInTheDocument();
    expect(getMaskMeasurements).not.toHaveBeenCalled();
  });
});
