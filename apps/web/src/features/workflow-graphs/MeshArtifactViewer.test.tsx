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
