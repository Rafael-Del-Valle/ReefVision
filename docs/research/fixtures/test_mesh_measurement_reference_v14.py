"""Synthetic analytical checks for the standalone provisional mesh reference."""
from __future__ import annotations

import math
import unittest

from mesh_measurement_reference_v14 import measure_triangle_mesh


class MeshMeasurementReferenceTests(unittest.TestCase):
    def test_unit_square_calibration_and_uncertainty(self) -> None:
        result = measure_triangle_mesh(
            [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)],
            [(0, 1, 2), (0, 2, 3)],
            meters_per_unit=0.01,
            absolute_scale_bound=0.001,
        )
        self.assertEqual(result.triangle_count, 2)
        self.assertAlmostEqual(result.triangle_area_units2, 4)
        self.assertAlmostEqual(result.surface_area_m2, 0.0004)
        self.assertAlmostEqual(result.surface_area_scale_bound_m2, 0.000084)
        self.assertEqual(result.dimensions_m, (0.02, 0.02, 0.0))
        self.assertEqual(result.dimensions_scale_bound_m, (0.002, 0.002, 0.0))
        self.assertEqual(result.calibration_review_state, "provisional")
        self.assertEqual(result.anatomical_review_state, "unverified")

    def test_triangle_winding_does_not_change_area(self) -> None:
        vertices = [(0, 0, 0), (3, 0, 0), (0, 4, 0)]
        forward = measure_triangle_mesh(vertices, [(0, 1, 2)],
                                        meters_per_unit=1, absolute_scale_bound=0)
        reverse = measure_triangle_mesh(vertices, [(2, 1, 0)],
                                        meters_per_unit=1, absolute_scale_bound=0)
        self.assertEqual(forward.surface_area_m2, 6)
        self.assertEqual(forward, reverse)

    def test_invalid_calibration_rejected(self) -> None:
        for scale, bound in [(0, 0), (1, 1), (1, -0.1), (math.nan, 0)]:
            with self.subTest(scale=scale, bound=bound), self.assertRaises(ValueError):
                measure_triangle_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                                      [(0, 1, 2)], meters_per_unit=scale,
                                      absolute_scale_bound=bound)

    def test_nonnumeric_and_boolean_coordinates_rejected(self) -> None:
        # bool is accepted by math.isfinite but is not a measured coordinate.
        # Strings and missing values should produce a scientific input error,
        # not leak a Python TypeError from the arithmetic implementation.
        for invalid in [True, False, "1", None, complex(1, 0)]:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "vertices must be finite numeric 3D coordinates"
            ):
                measure_triangle_mesh(
                    [(0, 0, 0), (invalid, 0, 0), (0, 1, 0)],
                    [(0, 1, 2)], meters_per_unit=1,
                    absolute_scale_bound=0,
                )

    def test_degenerate_and_invalid_faces_rejected(self) -> None:
        vertices = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        for face in [(0, 1, 2), (0, 1, 1), (0, 1, 3), (0, True, 2)]:
            with self.subTest(face=face), self.assertRaises(ValueError):
                measure_triangle_mesh(vertices, [face], meters_per_unit=1,
                                      absolute_scale_bound=0)


    def test_duplicate_faces_rejected_regardless_of_winding(self) -> None:
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        for duplicate in [(0, 1, 2), (2, 1, 0), (1, 2, 0)]:
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(
                ValueError, "duplicate triangle surface"
            ):
                measure_triangle_mesh(
                    vertices, [(0, 1, 2), duplicate],
                    meters_per_unit=1, absolute_scale_bound=0,
                )

    def test_coincident_faces_with_distinct_indices_rejected(self) -> None:
        # Mesh exporters can duplicate seam vertices. Distinct indices do not
        # imply distinct observed coral surface patches.
        vertices = [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
            (0, 1, 0), (0, 0, 0), (1, 0, 0),
        ]
        for faces in [
            [(0, 1, 2), (3, 4, 5)],
            [(3, 4, 5), (0, 1, 2)],
        ]:
            with self.subTest(faces=faces), self.assertRaisesRegex(
                ValueError, "duplicate triangle surface"
            ):
                measure_triangle_mesh(
                    vertices, faces, meters_per_unit=0.01,
                    absolute_scale_bound=0.001,
                )

    def test_unreferenced_vertices_do_not_inflate_dimensions(self) -> None:
        vertices = [(0, 0, 0), (2, 0, 0), (0, 3, 0), (1000, -500, 900)]
        result = measure_triangle_mesh(
            vertices, [(0, 1, 2)],
            meters_per_unit=0.01, absolute_scale_bound=0.001,
        )
        self.assertAlmostEqual(result.surface_area_m2, 0.0003)
        self.assertEqual(result.dimensions_m, (0.02, 0.03, 0.0))
        self.assertEqual(result.dimensions_scale_bound_m, (0.002, 0.003, 0.0))
        self.assertEqual(result.triangle_count, 1)

    def test_extreme_finite_coordinates_reject_overflowing_geometry(self) -> None:
        vertices = [(-1e308, 0, 0), (1e308, 0, 0), (0, 1e-308, 0)]
        with self.assertRaisesRegex(ValueError, "degenerate or overflowing triangle"):
            measure_triangle_mesh(
                vertices, [(0, 1, 2)],
                meters_per_unit=1, absolute_scale_bound=0,
            )

    def test_calibration_cannot_overflow_physical_dimensions(self) -> None:
        vertices = [(0, 0, 0), (1e200, 0, 0), (0, 1e-200, 0)]
        with self.assertRaisesRegex(ValueError, "nonfinite calibrated mesh measurement"):
            measure_triangle_mesh(
                vertices, [(0, 1, 2)],
                meters_per_unit=1e200, absolute_scale_bound=0,
            )


    def test_nonzero_surface_cannot_underflow_to_zero_after_calibration(self) -> None:
        # Source triangle is nondegenerate; extremely small scale would
        # otherwise silently report zero physical area.
        vertices = [(0, 0, 0), (1e-100, 0, 0), (0, 1e-100, 0)]
        with self.assertRaisesRegex(ValueError, "calibrated mesh surface area underflow"):
            measure_triangle_mesh(
                vertices, [(0, 1, 2)],
                meters_per_unit=1e-100, absolute_scale_bound=0,
            )

    def test_nonzero_axis_cannot_underflow_to_zero_after_calibration(self) -> None:
        # Area remains representable, but the tiny observed Z extent would
        # otherwise be falsely reported as an exactly planar surface.
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 1e-200)]
        with self.assertRaisesRegex(ValueError, "calibrated mesh dimension underflow"):
            measure_triangle_mesh(
                vertices, [(0, 1, 2)],
                meters_per_unit=1e-150, absolute_scale_bound=0,
            )

    def test_nonzero_dimension_uncertainty_cannot_underflow(self) -> None:
        # The observed Z extent and nominal dimension are representable,
        # but a positive scale uncertainty would otherwise become zero.
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 1e-200)]
        with self.assertRaisesRegex(ValueError, "calibrated mesh dimension uncertainty underflow"):
            measure_triangle_mesh(
                vertices, [(0, 1, 2)],
                meters_per_unit=1, absolute_scale_bound=1e-150,
            )

    def test_uncertainty_overflow_rejected_even_when_nominal_area_is_finite(self) -> None:
        # Nominal area is finite (~1e308 m²), but the upper scale
        # endpoint overflows; never return an infinite error bar.
        vertices = [(0, 0, 0), (2, 0, 0), (0, 1, 0)]
        with self.assertRaisesRegex(ValueError, "nonfinite calibrated mesh uncertainty"):
            measure_triangle_mesh(
                vertices, [(0, 1, 2)],
                meters_per_unit=1e154, absolute_scale_bound=0.5e154,
            )


    def test_small_observed_patch_cannot_disappear_in_area_sum(self) -> None:
        # Both triangles are nondegenerate and disjoint. A 5e-21-unit²
        # patch would otherwise be rounded away when added to 0.5-unit².
        vertices = [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
            (2, 0, 0), (2 + 1e-10, 0, 0), (2, 1e-10, 0),
        ]
        with self.assertRaisesRegex(
            ValueError, "observed triangle area lost to numeric precision"
        ):
            measure_triangle_mesh(
                vertices, [(0, 1, 2), (3, 4, 5)],
                meters_per_unit=1, absolute_scale_bound=0,
            )

    def test_small_patch_rejected_in_either_face_order(self) -> None:
        # Face order must not determine whether a real observed patch is lost.
        vertices = [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
            (2, 0, 0), (2 + 1e-10, 0, 0), (2, 1e-10, 0),
        ]
        for faces in [[(0, 1, 2), (3, 4, 5)], [(3, 4, 5), (0, 1, 2)]]:
            with self.subTest(faces=faces), self.assertRaisesRegex(
                ValueError, "observed triangle area lost to numeric precision"
            ):
                measure_triangle_mesh(
                    vertices, faces, meters_per_unit=1, absolute_scale_bound=0,
                )

    def test_positive_area_uncertainty_cannot_round_to_zero(self) -> None:
        # Positive calibration uncertainty can be smaller than the ULP
        # of the squared scale, silently reporting an exact area.
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        with self.assertRaisesRegex(
            ValueError, "calibrated mesh surface area uncertainty underflow"
        ):
            measure_triangle_mesh(
                vertices, [(0, 1, 2)],
                meters_per_unit=1, absolute_scale_bound=1e-20,
            )


if __name__ == "__main__":
    unittest.main()
