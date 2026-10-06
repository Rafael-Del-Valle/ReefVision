import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectMorphometricsInspector } from "./ProjectMorphometricsInspector";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderInspector({
  imageId = "image-1",
  onOpenMeasurements = vi.fn(),
}: {
  imageId?: string | null;
  onOpenMeasurements?: (imageId: string) => void;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ProjectMorphometricsInspector
        projectId="project-1"
        imageId={imageId}
        onOpenMeasurements={onOpenMeasurements}
      />
    </QueryClientProvider>,
  );

  return { onOpenMeasurements };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ProjectMorphometricsInspector", () => {
  it("shows the accepted physical calibration for the focused image", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);

      if (url.includes("/images/image-1/measurement-calibration")) {
        return jsonResponse({
          image_id: "image-1",
          calibrated: true,
          distance_per_pixel: 0.0125,
          unit: "mm",
          source: "automatic_scale_bar",
          reference_length: 10,
          reference_pixel_length: 800,
          default_depth: null,
          notes: null,
          confidence: 0.93,
          detector: "reefvision-scale-bar-geometry-v1",
          profile_name: null,
          profile_source_image_id: null,
          camera_signature: null,
          perspective_homography: null,
          reference_plane_only: false,
        });
      }

      throw new Error(`Unhandled request GET ${url}`);
    });

    renderInspector();

    expect(
      await screen.findByLabelText("Accepted image calibration"),
    ).toBeInTheDocument();

    expect(screen.getByText("0.0125 mm/px")).toBeInTheDocument();
    expect(screen.getByText("automatic scale bar")).toBeInTheDocument();
    expect(screen.getByText("93%")).toBeInTheDocument();

    expect(
      screen.getByRole("link", {
        name: "Export measurements CSV",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", {
        name: "Export measurements NumPy",
      }),
    ).toBeInTheDocument();
  });

  it("opens the existing Scale Assistant instead of duplicating calibration logic", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);

      if (url.includes("/images/image-1/measurement-calibration")) {
        return jsonResponse(null);
      }

      if (
        url.includes("/projects/project-1/measurement-calibration-profiles")
      ) {
        return jsonResponse([]);
      }

      throw new Error(`Unhandled request GET ${url}`);
    });

    renderInspector();

    await screen.findByText("Not calibrated");

    await userEvent.click(
      screen.getByRole("button", {
        name: "Open Scale Assistant",
      }),
    );

    expect(screen.getByTestId("calibration-assistant")).toBeInTheDocument();
    expect(screen.getByText("Detect digital scale bar")).toBeInTheDocument();
    expect(
      screen.getByText("Read a printed scale label with OCR"),
    ).toBeInTheDocument();
  });

  it("routes mask measurements to the canonical annotation editor", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);

      if (url.includes("/images/image-1/measurement-calibration")) {
        return jsonResponse(null);
      }

      throw new Error(`Unhandled request GET ${url}`);
    });

    const handlers = renderInspector();

    await screen.findByText("Not calibrated");

    await userEvent.click(
      screen.getByRole("button", {
        name: "Open masks & measurements",
      }),
    );

    expect(handlers.onOpenMeasurements).toHaveBeenCalledWith("image-1");
  });

  it("does not fabricate measurement context without a focused image", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    renderInspector({ imageId: null });

    expect(screen.getByText("Focus an image first")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
