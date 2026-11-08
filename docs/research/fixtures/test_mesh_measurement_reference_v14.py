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

if __name__ == "__main__":
    unittest.main()
