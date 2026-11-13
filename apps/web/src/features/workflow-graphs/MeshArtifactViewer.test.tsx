import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  MeshArtifactViewer,
  parseMeshRenderArtifact,
} from "./MeshArtifactViewer";

const validArtifact = {
  preview_vertices_in_source_frame_m: [
    [0, 0, 0],
    [1, 0, 0],
    [0, 1, 0],
  ],
  preview_faces_local_indices: [[0, 1, 2]],
  preview_face_indices: [7],
  preview_camera_target_in_source_frame_m: [0.5, 0.5, 0],
  preview_camera_radius_m: 1,
  preview_face_fraction: 0.5,
  preview_surface_area_fraction: 0.25,
  preview_is_decimated: true,
  measurement_status: "caller_supplied_unverified",
  provenance: { calibration_verified: false },
};

describe("MeshArtifactViewer", () => {
  it("rotates and resets the persisted preview without changing the scientific artifact", () => {
    const before = JSON.stringify(validArtifact);
    const { container } = render(
      <MeshArtifactViewer artifact={validArtifact} />,
    );
    const polygon = container.querySelector("polygon");
    expect(polygon).not.toBeNull();
    expect(polygon?.getAttribute("data-source-face-index")).toBe("7");
    const originalPoints = polygon?.getAttribute("points");
    fireEvent.change(screen.getByRole("slider", { name: "Yaw" }), {
      target: { value: "90" },
    });
    expect(polygon?.getAttribute("points")).not.toBe(originalPoints);
    fireEvent.click(screen.getByRole("button", { name: "Reset 3D view" }));
    expect(polygon?.getAttribute("points")).toBe(originalPoints);
    expect(screen.getByText(/Surface-area coverage:/)).toHaveTextContent(
      "25.0%",
    );
    expect(screen.getByText(/Surface-area coverage:/)).toHaveTextContent(
      "Decimated preview",
    );
    expect(JSON.stringify(validArtifact)).toBe(before);
  });

  it("renders complete provisional edge routes despite triangle decimation", () => {
    const artifact = {
      ...validArtifact,
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 5, 2],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [0.5, 0.5, 0.5],
            [0, 1, 0],
          ],
        },
        {
          status: "disconnected",
          path_vertex_indices: null,
          path_vertices_in_source_frame_m: null,
        },
      ],
    };
    const original = JSON.stringify(artifact);
    const { container } = render(<MeshArtifactViewer artifact={artifact} />);
    const polyline = container.querySelector(
      '[data-testid="mesh-route-polyline"]',
    );
    expect(polyline).not.toBeNull();
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
    expect(polyline?.getAttribute("points")?.split(" ")).toHaveLength(3);
    const initial = polyline?.getAttribute("points");
    fireEvent.change(screen.getByRole("slider", { name: "Yaw" }), {
      target: { value: "90" },
    });
    expect(polyline?.getAttribute("points")).not.toBe(initial);
    expect(
      screen.getByText(/complete provisional mesh-edge/),
    ).toHaveTextContent("not verified coral branch centerlines");
    expect(JSON.stringify(artifact)).toBe(original);
  });

  it("inspects saved path lengths, scale bounds, and QC without promoting routes to centerlines", () => {
    const artifact = {
      ...validArtifact,
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 1, 2],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
          ],
          length_m: 2,
          length_scale_interval_m: [1.8, 2.2],
          path_qc_warnings: ["open_boundary_edge_on_path"],
        },
        {
          status: "connected",
          path_vertex_indices: [5, 6],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1, 0, 0],
          ],
          length_m: 1,
          length_scale_interval_m: null,
          path_qc_warnings: ["coincident_route_endpoints"],
        },
        {
          status: "disconnected",
          path_vertex_indices: null,
          path_vertices_in_source_frame_m: null,
        },
      ],
    };
    const unchanged = JSON.stringify(artifact);
    const { container, rerender } = render(
      <MeshArtifactViewer artifact={artifact} />,
    );
    expect(container.querySelectorAll("polyline")).toHaveLength(2);
    expect(
      screen.getByText(
        "Select a connected route for provisional measurement details.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    expect(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(/Saved geometric route length: 2.00000 m/),
    ).toHaveTextContent("Scale-only length interval: [1.80000, 2.20000] m");
    expect(
      screen.getByText(/Saved geometric route length: 2.00000 m/),
    ).toHaveTextContent("open_boundary_edge_on_path");
    expect(
      screen.getByText(/Saved geometric route length: 2.00000 m/),
    ).toHaveTextContent("not a verified biological branch length");

    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 2" }),
    );
    expect(
      screen.getByText(/Saved geometric route length: 1.00000 m/),
    ).toHaveTextContent("Scale-only length interval: unknown");
    expect(
      screen.getByText(/Saved geometric route length: 1.00000 m/),
    ).toHaveTextContent("coincident_route_endpoints");
    expect(JSON.stringify(artifact)).toBe(unchanged);
    rerender(<MeshArtifactViewer artifact={validArtifact} />);
    expect(screen.queryByText(/Saved geometric route length:/)).toBeNull();
  });

  it("inspects saved cumulative mesh waypoints without treating them as anatomical landmarks", () => {
    const artifact = {
      ...validArtifact,
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [10, 12, 16],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
          ],
          length_m: 2,
          length_scale_interval_m: [1.8, 2.2],
          path_cumulative_lengths_m: [0, 1, 2],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [0.9, 1.1],
            [1.8, 2.2],
          ],
          path_qc_warnings: [],
        },
      ],
    };
    const original = JSON.stringify(artifact);
    const { container, rerender } = render(
      <MeshArtifactViewer artifact={artifact} />,
    );
    expect(
      screen.queryByTestId("mesh-route-waypoint-marker"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    expect(screen.getByText(/Route waypoint 1 of 3/)).toHaveTextContent(
      "source vertex 10",
    );
    expect(screen.getByText(/Route waypoint 1 of 3/)).toHaveTextContent(
      "Saved cumulative mesh-edge distance: 0.00000 m",
    );
    const marker = container.querySelector(
      '[data-testid="mesh-route-waypoint-marker"]',
    );
    expect(marker).not.toBeNull();
    const firstPosition = marker?.getAttribute("cx");
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "source vertex 12",
    );
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Saved cumulative mesh-edge distance: 1.00000 m",
    );
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Scale-only cumulative interval: [0.900000, 1.10000] m",
    );
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "not a verified coral anatomical landmark",
    );
    expect(marker?.getAttribute("cx")).not.toBe(firstPosition);
    expect(JSON.stringify(artifact)).toBe(original);
    rerender(<MeshArtifactViewer artifact={validArtifact} />);
    expect(screen.queryByTestId("mesh-route-waypoint-marker")).toBeNull();
    expect(screen.queryByRole("slider", { name: "Route vertex" })).toBeNull();
  });

  it("highlights and inspects individual saved mesh-edge segments without claiming anatomy", () => {
    const artifact = {
      ...validArtifact,
      provenance: {
        calibration_verified: false,
        relative_scale_uncertainty: 0.1,
      },
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [10, 12, 16],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [3, 0, 0],
            [3, 4, 0],
          ],
          length_m: 7,
          length_scale_interval_m: [6.3, 7.7],
          path_cumulative_lengths_m: [0, 3, 7],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [2.7, 3.3],
            [6.3, 7.7],
          ],
          path_qc_warnings: [],
        },
      ],
    };
    const original = JSON.stringify(artifact);
    const { container, rerender } = render(
      <MeshArtifactViewer artifact={artifact} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    expect(screen.getByText(/Route waypoint 1 of 3/)).toHaveTextContent(
      "Starting waypoint has no preceding route segment",
    );
    expect(screen.queryByTestId("mesh-route-selected-segment")).toBeNull();

    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Saved preceding mesh-edge segment length: 3.00000 m",
    );
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Scale-only segment interval: [2.70000, 3.30000] m",
    );
    const segment = container.querySelector(
      '[data-testid="mesh-route-selected-segment"]',
    );
    expect(segment).not.toBeNull();
    const beforeYaw = segment?.getAttribute("x2");
    fireEvent.change(screen.getByRole("slider", { name: "Yaw" }), {
      target: { value: "100" },
    });
    expect(segment?.getAttribute("x2")).not.toBe(beforeYaw);

    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "2" },
    });
    expect(screen.getByText(/Route waypoint 3 of 3/)).toHaveTextContent(
      "Saved preceding mesh-edge segment length: 4.00000 m",
    );
    expect(screen.getByText(/Route waypoint 3 of 3/)).toHaveTextContent(
      "Scale-only segment interval: [3.60000, 4.40000] m",
    );
    expect(screen.getByText(/Route waypoint 3 of 3/)).toHaveTextContent(
      "Not a verified anatomical segment",
    );
    expect(JSON.stringify(artifact)).toBe(original);
    rerender(<MeshArtifactViewer artifact={validArtifact} />);
    expect(screen.queryByTestId("mesh-route-selected-segment")).toBeNull();
  });

  it("inspects persisted per-edge measurements independently of missing cumulative arrays", () => {
    const artifact = {
      ...validArtifact,
      provenance: {
        calibration_verified: false,
        relative_scale_uncertainty: 0.1,
      },
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [10, 12, 16],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [3, 0, 0],
            [3, 4, 0],
          ],
          length_m: 7,
          path_edge_lengths_m: [3, 4],
          path_edge_length_scale_intervals_m: [
            [2.7, 3.3],
            [3.6, 4.4],
          ],
          path_qc_warnings: [],
        },
      ],
    };
    const original = JSON.stringify(artifact);
    render(<MeshArtifactViewer artifact={artifact} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    const first = screen.getByText(/Route waypoint 2 of 3/);
    expect(first).toHaveTextContent(
      "Saved cumulative mesh-edge distance: unknown",
    );
    expect(first).toHaveTextContent(
      "Saved preceding mesh-edge segment length: 3.00000 m",
    );
    expect(first).toHaveTextContent(
      "Scale-only segment interval: [2.70000, 3.30000] m",
    );
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "2" },
    });
    const second = screen.getByText(/Route waypoint 3 of 3/);
    expect(second).toHaveTextContent(
      "Saved preceding mesh-edge segment length: 4.00000 m",
    );
    expect(second).toHaveTextContent(
      "Scale-only segment interval: [3.60000, 4.40000] m",
    );
    expect(second).toHaveTextContent("Not a verified anatomical segment");
    expect(JSON.stringify(artifact)).toBe(original);
  });

  it("keeps inconsistent saved edge values and uncertainty unknown rather than recomputing", () => {
    const route = {
      status: "connected",
      path_vertex_indices: [10, 12, 16],
      path_vertices_in_source_frame_m: [
        [0, 0, 0],
        [3, 0, 0],
        [3, 4, 0],
      ],
      length_m: 7,
      path_edge_lengths_m: [3, 40],
      path_edge_length_scale_intervals_m: [
        [2.7, 3.3],
        [3.6, 4.4],
      ],
      path_qc_warnings: [],
    };
    const provenance = {
      calibration_verified: false,
      relative_scale_uncertainty: 0.1,
    };
    const corrupted = {
      ...validArtifact,
      provenance,
      surface_edge_paths: [route],
    };
    const { rerender } = render(<MeshArtifactViewer artifact={corrupted} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Saved preceding mesh-edge segment length: unknown",
    );
    const badInterval = {
      ...validArtifact,
      provenance,
      surface_edge_paths: [
        {
          ...route,
          path_edge_lengths_m: [3, 4],
          path_edge_length_scale_intervals_m: [
            [1, 6],
            [3.6, 4.4],
          ],
        },
      ],
    };
    const original = JSON.stringify(badInterval);
    rerender(<MeshArtifactViewer artifact={badInterval} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    const inspected = screen.getByText(/Route waypoint 2 of 3/);
    expect(inspected).toHaveTextContent(
      "Saved preceding mesh-edge segment length: 3.00000 m",
    );
    expect(inspected).toHaveTextContent("Scale-only segment interval: unknown");
    expect(JSON.stringify(badInterval)).toBe(original);
  });

  it("keeps invalid or legacy cumulative route measurements unknown", () => {
    const artifact = {
      ...validArtifact,
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 1, 2],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
          ],
          length_m: 2,
          path_cumulative_lengths_m: [0, 3, 2],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [2.9, 3.1],
            [1.8, 2.2],
          ],
          path_qc_warnings: [],
        },
      ],
    };
    render(<MeshArtifactViewer artifact={artifact} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Saved cumulative mesh-edge distance: unknown",
    );
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Scale-only cumulative interval: unknown",
    );
  });

  it("rejects backwards scale bounds in saved waypoint metadata", () => {
    const artifact = {
      ...validArtifact,
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 1, 2],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
          ],
          length_m: 2,
          length_scale_interval_m: [1.8, 2.2],
          path_cumulative_lengths_m: [0, 1, 2],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [0.9, 1.1],
            [0.8, 2.2],
          ],
          path_qc_warnings: [],
        },
      ],
    };
    const before = JSON.stringify(artifact);
    const { container } = render(<MeshArtifactViewer artifact={artifact} />);
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    const waypoint = screen.getByText(/Route waypoint 2 of 3/);
    expect(waypoint).toHaveTextContent(
      "Saved cumulative mesh-edge distance: 1.00000 m",
    );
    expect(waypoint).toHaveTextContent(
      "Scale-only cumulative interval: unknown",
    );
    expect(waypoint).toHaveTextContent(
      "not a verified coral anatomical landmark",
    );
    expect(JSON.stringify(artifact)).toBe(before);
  });

  it("rejects scale-only route and waypoint bounds that contradict saved calibration", () => {
    const artifact = {
      ...validArtifact,
      provenance: {
        calibration_verified: false,
        relative_scale_uncertainty: 0.1,
      },
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 1, 2],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
          ],
          length_m: 2,
          length_scale_interval_m: [0.5, 3.5],
          path_cumulative_lengths_m: [0, 1, 2],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [0.5, 1.5],
            [1.8, 2.2],
          ],
          path_qc_warnings: [],
        },
      ],
    };
    const original = JSON.stringify(artifact);
    const { rerender } = render(<MeshArtifactViewer artifact={artifact} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    expect(
      screen.getByText(/Saved geometric route length: 2.00000 m/),
    ).toHaveTextContent("Scale-only length interval: unknown");
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    const waypoint = screen.getByText(/Route waypoint 2 of 3/);
    expect(waypoint).toHaveTextContent(
      "Saved cumulative mesh-edge distance: 1.00000 m",
    );
    expect(waypoint).toHaveTextContent(
      "Scale-only cumulative interval: unknown",
    );
    expect(JSON.stringify(artifact)).toBe(original);

    const corrected = {
      ...artifact,
      surface_edge_paths: [
        {
          ...artifact.surface_edge_paths[0],
          length_scale_interval_m: [1.8, 2.2],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [0.9, 1.1],
            [1.8, 2.2],
          ],
        },
      ],
    };
    rerender(<MeshArtifactViewer artifact={corrected} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    expect(
      screen.getByText(/Saved geometric route length: 2.00000 m/),
    ).toHaveTextContent("Scale-only length interval: [1.80000, 2.20000] m");
    fireEvent.change(screen.getByRole("slider", { name: "Route vertex" }), {
      target: { value: "1" },
    });
    expect(screen.getByText(/Route waypoint 2 of 3/)).toHaveTextContent(
      "Scale-only cumulative interval: [0.900000, 1.10000] m",
    );
  });

  it("rejects misleading microscopic and zero-length uncertainty bounds", () => {
    const tiny = {
      ...validArtifact,
      provenance: {
        calibration_verified: false,
        relative_scale_uncertainty: 0.1,
      },
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 1],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1e-16, 0, 0],
          ],
          length_m: 1e-16,
          length_scale_interval_m: [0, 1e-13],
          path_edge_lengths_m: [1e-16],
          path_edge_length_scale_intervals_m: [[0, 1e-13]],
          path_cumulative_lengths_m: [0, 1e-16],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [0, 1e-13],
          ],
          path_qc_warnings: [],
        },
      ],
    };
    const original = JSON.stringify(tiny);
    const rejected = parseMeshRenderArtifact(tiny)?.routeInspections[0];
    expect(rejected).toMatchObject({
      lengthM: 1e-16,
      lengthScaleIntervalM: null,
      edgeLengthsM: [1e-16],
      edgeScaleIntervalsM: null,
      cumulativeLengthsM: [0, 1e-16],
      cumulativeScaleIntervalsM: null,
    });

    const zero = {
      ...tiny,
      surface_edge_paths: [
        {
          ...tiny.surface_edge_paths[0],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [0, 0, 0],
          ],
          length_m: 0,
          length_scale_interval_m: [0, 1e-13],
          path_edge_lengths_m: [0],
          path_edge_length_scale_intervals_m: [[0, 1e-13]],
          path_cumulative_lengths_m: [0, 0],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [0, 1e-13],
          ],
        },
      ],
    };
    expect(parseMeshRenderArtifact(zero)?.routeInspections[0]).toMatchObject({
      lengthM: 0,
      lengthScaleIntervalM: null,
      edgeLengthsM: [0],
      edgeScaleIntervalsM: null,
      cumulativeLengthsM: [0, 0],
      cumulativeScaleIntervalsM: null,
    });

    const valid = {
      ...tiny,
      surface_edge_paths: [
        {
          ...tiny.surface_edge_paths[0],
          length_scale_interval_m: [9e-17, 1.1e-16],
          path_edge_length_scale_intervals_m: [[9e-17, 1.1e-16]],
          path_cumulative_length_scale_intervals_m: [
            [0, 0],
            [9e-17, 1.1e-16],
          ],
        },
      ],
    };
    expect(parseMeshRenderArtifact(valid)?.routeInspections[0]).toMatchObject({
      lengthScaleIntervalM: [9e-17, 1.1e-16],
      edgeScaleIntervalsM: [[9e-17, 1.1e-16]],
      cumulativeScaleIntervalsM: [
        [0, 0],
        [9e-17, 1.1e-16],
      ],
    });
    expect(
      parseMeshRenderArtifact({
        ...tiny,
        provenance: {
          calibration_verified: false,
          relative_scale_uncertainty: 1,
        },
      }),
    ).toBeNull();
    expect(JSON.stringify(tiny)).toBe(original);
  });

  it("fails closed on invalid saved path measurements but retains renderable geometry", () => {
    const artifact = {
      ...validArtifact,
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 1],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [1, 0, 0],
          ],
          length_m: -3,
          length_scale_interval_m: [4, 5],
          path_qc_warnings: ["<untrusted>"],
        },
      ],
    };
    const { container } = render(<MeshArtifactViewer artifact={artifact} />);
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect provisional route 1" }),
    );
    const result = screen.getByText(/Saved geometric route length: unknown/);
    expect(result).toHaveTextContent("Scale-only length interval: unknown");
    expect(result).toHaveTextContent("missing or invalid saved QC");
    expect(result).not.toHaveTextContent("<untrusted>");
  });

  it("does not draw malformed or legacy route geometry", () => {
    const malformed = {
      ...validArtifact,
      surface_edge_paths: [
        {
          status: "connected",
          path_vertex_indices: [0, 1, 2],
          path_vertices_in_source_frame_m: [
            [0, 0, 0],
            [Number.POSITIVE_INFINITY, 0, 0],
          ],
        },
      ],
    };
    expect(parseMeshRenderArtifact(malformed)?.pathPolylines).toEqual([]);
    const { container, rerender } = render(
      <MeshArtifactViewer artifact={malformed} />,
    );
    expect(container.querySelectorAll("polyline")).toHaveLength(0);
    rerender(<MeshArtifactViewer artifact={validArtifact} />);
    expect(container.querySelectorAll("polyline")).toHaveLength(0);
    expect(parseMeshRenderArtifact(validArtifact)?.pathPolylines).toEqual([]);
  });

  it("fails closed on malformed indices, non-finite geometry, and oversized payloads", () => {
    expect(
      parseMeshRenderArtifact({
        ...validArtifact,
        preview_faces_local_indices: [[0, 1, 999]],
      }),
    ).toBeNull();
    expect(
      parseMeshRenderArtifact({
        ...validArtifact,
        preview_vertices_in_source_frame_m: [
          [0, 0, 0],
          [Number.POSITIVE_INFINITY, 0, 0],
          [0, 1, 0],
        ],
      }),
    ).toBeNull();
    expect(
      parseMeshRenderArtifact({
        ...validArtifact,
        preview_faces_local_indices: Array.from({ length: 513 }, () => [
          0, 1, 2,
        ]),
        preview_face_indices: Array.from({ length: 513 }, (_, index) => index),
      }),
    ).toBeNull();
    render(
      <MeshArtifactViewer
        artifact={{ ...validArtifact, preview_face_fraction: Number.NaN }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "no valid bounded 3D display geometry",
    );
  });

  it("does not misrepresent zero-area sampling as verified area coverage", () => {
    render(
      <MeshArtifactViewer
        artifact={{ ...validArtifact, preview_surface_area_fraction: null }}
      />,
    );
    expect(screen.getByText(/Surface-area coverage:/)).toHaveTextContent(
      "undefined (zero-area geometry)",
    );
    expect(
      screen.getByText(/Calibration and coordinate registration/),
    ).toHaveTextContent("unverified");
  });

  it("inspects source triangle vertices without changing saved data", () => {
    const before = JSON.stringify(validArtifact);
    render(<MeshArtifactViewer artifact={validArtifact} />);
    const triangle = screen.getByRole("button", {
      name: "Inspect source triangle 7",
    });
    expect(triangle).toHaveAttribute("aria-pressed", "false");
    fireEvent.keyDown(triangle, { key: "Enter" });
    expect(triangle).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent("vertex 2 (1.00000, 0.00000, 0.00000) m");
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent("not anatomical branch lengths or verified surface");
    expect(JSON.stringify(validArtifact)).toBe(before);
  });

  it("computes preview triangle area from calibrated 3D vertices, independent of camera yaw", () => {
    const sample = {
      ...validArtifact,
      preview_vertices_in_source_frame_m: [
        [0, 0, 0],
        [0, 2, 0],
        [0, 0, 3],
      ],
    };
    render(<MeshArtifactViewer artifact={sample} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    const inspection = screen.getByText(
      /Source triangle 7 \(unverified source frame\)/,
    );
    expect(inspection).toHaveTextContent(
      "Selected preview triangle area: 3.00000 m²",
    );
    fireEvent.change(screen.getByRole("slider", { name: "Yaw" }), {
      target: { value: "120" },
    });
    expect(inspection).toHaveTextContent(
      "Selected preview triangle area: 3.00000 m²",
    );
    expect(inspection).toHaveTextContent(
      "reconstruction uncertainty unverified",
    );
  });

  it("shows caller-supplied scale-only area bounds without changing the saved mesh", () => {
    const sample = {
      ...validArtifact,
      preview_vertices_in_source_frame_m: [
        [0, 0, 0],
        [0, 2, 0],
        [0, 0, 3],
      ],
      provenance: {
        calibration_verified: false,
        relative_scale_uncertainty: 0.1,
      },
    };
    const original = JSON.stringify(sample);
    render(<MeshArtifactViewer artifact={sample} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    const inspection = screen.getByText(
      /Source triangle 7 \(unverified source frame\)/,
    );
    expect(inspection).toHaveTextContent(
      "Scale-only triangle area interval: [2.43000, 3.63000] m²",
    );
    fireEvent.change(screen.getByRole("slider", { name: "Yaw" }), {
      target: { value: "150" },
    });
    expect(inspection).toHaveTextContent(
      "Scale-only triangle area interval: [2.43000, 3.63000] m²",
    );
    expect(inspection).toHaveTextContent(
      "reconstruction uncertainty unverified",
    );
    expect(JSON.stringify(sample)).toBe(original);
  });

  it("distinguishes missing and zero scale uncertainty, and rejects invalid evidence", () => {
    const { rerender } = render(
      <MeshArtifactViewer artifact={validArtifact} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent("unknown (scale uncertainty not supplied)");
    rerender(
      <MeshArtifactViewer
        artifact={{
          ...validArtifact,
          provenance: {
            calibration_verified: false,
            relative_scale_uncertainty: 0,
          },
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent(
      "Scale-only triangle area interval: [0.500000, 0.500000] m²",
    );
    for (const invalid of [-0.1, 1.1, Number.NaN, true, "0.1"]) {
      expect(
        parseMeshRenderArtifact({
          ...validArtifact,
          provenance: {
            calibration_verified: false,
            relative_scale_uncertainty: invalid,
          },
        }),
      ).toBeNull();
    }
  });

  it("reports zero geometric area for a collinear preview triangle", () => {
    const sample = {
      ...validArtifact,
      preview_vertices_in_source_frame_m: [
        [0, 0, 0],
        [1, 0, 0],
        [2, 0, 0],
      ],
    };
    render(<MeshArtifactViewer artifact={sample} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent("Selected preview triangle area: 0.00000 m²");
  });

  it("inspects 3–4–5 triangle edges with scale-only intervals independent of camera", () => {
    const sample = {
      ...validArtifact,
      preview_vertices_in_source_frame_m: [
        [0, 0, 0],
        [3, 0, 0],
        [0, 4, 0],
      ],
      provenance: {
        calibration_verified: false,
        relative_scale_uncertainty: 0.1,
      },
    };
    const original = JSON.stringify(sample);
    render(<MeshArtifactViewer artifact={sample} />);
    fireEvent.keyDown(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
      { key: "Enter" },
    );
    const inspection = screen.getByText(
      /Source triangle 7 \(unverified source frame\)/,
    );
    expect(inspection).toHaveTextContent(
      "Selected preview triangle edge lengths (1–2, 2–3, 3–1): 3.00000, 5.00000, 4.00000 m",
    );
    expect(inspection).toHaveTextContent(
      "Scale-only edge length intervals: [2.70000, 3.30000], [4.50000, 5.50000], [3.60000, 4.40000] m",
    );
    fireEvent.change(screen.getByRole("slider", { name: "Yaw" }), {
      target: { value: "135" },
    });
    expect(inspection).toHaveTextContent(
      "Selected preview triangle edge lengths (1–2, 2–3, 3–1): 3.00000, 5.00000, 4.00000 m",
    );
    expect(inspection).toHaveTextContent("not anatomical branch lengths");
    expect(JSON.stringify(sample)).toBe(original);
  });

  it("keeps unknown edge uncertainty distinct from zero and handles degenerate edges", () => {
    const sample = {
      ...validArtifact,
      preview_vertices_in_source_frame_m: [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
      ],
    };
    const { rerender } = render(<MeshArtifactViewer artifact={sample} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent(
      "Selected preview triangle edge lengths (1–2, 2–3, 3–1): 0.00000, 0.00000, 0.00000 m",
    );
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent("unknown (scale uncertainty not supplied)");
    rerender(
      <MeshArtifactViewer
        artifact={{
          ...sample,
          provenance: {
            calibration_verified: false,
            relative_scale_uncertainty: 0,
          },
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toHaveTextContent(
      "Scale-only edge length intervals: [0.00000, 0.00000], [0.00000, 0.00000], [0.00000, 0.00000] m",
    );
  });

  it("clears triangle selection for a replacement reconstruction", () => {
    const { rerender } = render(
      <MeshArtifactViewer artifact={validArtifact} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect source triangle 7" }),
    );
    expect(
      screen.getByText(/Source triangle 7 \(unverified source frame\)/),
    ).toBeInTheDocument();
    rerender(<MeshArtifactViewer artifact={{ ...validArtifact }} />);
    expect(
      screen.queryByText(/Source triangle 7 \(unverified source frame\)/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Select a displayed source triangle/),
    ).toBeInTheDocument();
  });

  it("rejects contradictory calibration, registration, and identity claims", () => {
    const invalidArtifacts = [
      { ...validArtifact, measurement_status: "verified" },
      { ...validArtifact, provenance: { calibration_verified: true } },
      { ...validArtifact, provenance: null },
      { ...validArtifact, preview_coordinate_registration_verified: true },
      { ...validArtifact, coordinate_registration_verified: true },
      { ...validArtifact, specimen_identity_verified: true },
      { ...validArtifact, observation_metadata_verified: true },
    ];
    for (const artifact of invalidArtifacts) {
      expect(parseMeshRenderArtifact(artifact)).toBeNull();
    }
    render(
      <MeshArtifactViewer
        artifact={{
          ...validArtifact,
          provenance: { calibration_verified: true },
        }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "no valid bounded 3D display geometry",
    );
  });

  it("preserves display compatibility with legacy artifacts lacking review metadata", () => {
    const legacy: Record<string, unknown> = { ...validArtifact };
    delete legacy.provenance;
    delete legacy.measurement_status;
    expect(parseMeshRenderArtifact(legacy)).not.toBeNull();
  });

  it("rejects duplicate source-face identities in a sampled mesh", () => {
    expect(
      parseMeshRenderArtifact({
        ...validArtifact,
        preview_faces_local_indices: [
          [0, 1, 2],
          [0, 2, 1],
        ],
        preview_face_indices: [7, 7],
      }),
    ).toBeNull();
  });
});
