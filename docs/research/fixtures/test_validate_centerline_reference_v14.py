"""Mutation regressions for the provisional Track C centerline reference validator.

Run: python -m unittest discover -s docs/research/fixtures -p 'test_*.py'
These tests validate synthetic reference integrity, not anatomical accuracy.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from validate_centerline_reference_v14 import REFERENCE, validate_reference


class CenterlineReferenceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference = json.loads(REFERENCE.read_text(encoding="utf-8"))

    def check_mutation_rejected(self, mutate) -> None:
        data = copy.deepcopy(self.reference)
        mutate(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mutated_reference.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises((AssertionError, KeyError, TypeError, ValueError)):
                validate_reference(path)

    def test_unmodified_reference_passes(self) -> None:
        self.assertEqual(len(validate_reference()), 5)

    def test_duplicate_edge_is_rejected(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][1]["edges"].append(["junction", "root"])
        )

    def test_shared_trunk_double_count_is_rejected(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][1]["expected"].update(
                unique_edge_total_raw=14
            )
        )

    def test_degree_two_sampling_vertex_is_not_a_new_branch(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][2]["expected"].update(branch_count=2)
        )

    def test_cycle_cannot_be_silently_marked_resolved(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][3]["expected"].update(unresolved=False)
        )

    def test_occlusion_cannot_be_silently_marked_resolved(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][4]["expected"].update(unresolved=False)
        )

    def test_calibration_bound_mismatch_is_rejected(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][0]["expected"].update(
                scale_only_bound_m=0.0
            )
        )

    def test_zero_length_edge_is_rejected(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][0]["nodes"][1].__setitem__(slice(1, 4), [0, 0, 0])
        )

    def test_isolated_vertex_is_rejected(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][0]["nodes"].append(["orphan", 8, 8, 8])
        )

    def test_disconnected_centerline_requires_explicit_gap_review(self) -> None:
        data = copy.deepcopy(self.reference)
        data["cases"][4].pop("missing_edge")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unreviewed_gap.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "unreviewed disconnected graph"):
                validate_reference(path)

    def test_gap_annotation_must_bridge_disconnected_components(self) -> None:
        def mutate(data) -> None:
            data["cases"][4]["missing_edge"] = ["root", "visible_end"]

        self.check_mutation_rejected(mutate)

    def test_spurious_gap_on_connected_graph_is_rejected(self) -> None:
        def mutate(data) -> None:
            data["cases"][2]["missing_edge"] = ["root", "tip"]

        self.check_mutation_rejected(mutate)

    def test_nonfinite_coordinate_is_rejected(self) -> None:
        self.check_mutation_rejected(
            lambda data: data["cases"][0]["nodes"][0].__setitem__(1, float("nan"))
        )


if __name__ == "__main__":
    unittest.main()
