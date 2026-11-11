"""Executable positive/negative fixtures for the proposed Track C reference contract.

These are synthetic schema fixtures, not independently verified coral measurements.
Run with: python -m pytest apps/api/reefvision/tests/test_track_c_anatomical_reference_schema_v14.py
Requires the optional jsonschema package; tests skip explicitly when absent.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "docs/research/track_c_anatomical_reference.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
HASH = "a" * 64


def reference_record() -> dict:
    return {
        "schema_version": "1.0",
        "specimen_id": "synthetic-coral-1",
        "observation_id": "synthetic-observation-1",
        "acquired_at_utc": "2026-01-01T00:00:00Z",
        "source_sha256": HASH,
        "geometry_kind": "mesh",
        "calibration": {
            "method": "synthetic scale",
            "meters_per_unit": 0.01,
            "relative_scale_uncertainty": 0.1,
            "verified": False,
            "reviewer_id": None,
        },
        "reviewers": [
            {
                "reviewer_id": "synthetic-reviewer-a",
                "blinded": True,
                "protocol_revision": "draft",
                "reviewed_at_utc": "2026-01-02T00:00:00Z",
            },
            {
                "reviewer_id": "synthetic-reviewer-b",
                "blinded": True,
                "protocol_revision": "draft",
                "reviewed_at_utc": "2026-01-02T00:00:00Z",
            },
        ],
        "reference_measurements": [
            {
                "metric": "surface_area",
                "value": 0.5,
                "unit": "m2",
                "reference_method": "synthetic reference",
                "reviewer_id": "synthetic-reviewer-a",
                "anatomical_definition": "synthetic triangular area",
                "verification_status": "provisional",
            }
        ],
        "identity_review": {"status": "unverified", "reviewer_id": None},
        "registration_review": {
            "status": "not_applicable",
            "reference_frame": "synthetic mesh frame",
        },
    }


def test_reference_schema_itself_is_valid() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_provisional_synthetic_record_is_accepted() -> None:
    VALIDATOR.validate(reference_record())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("reference_measurements", 0, "unit"), "m"),
        (("calibration", "meters_per_unit"), 0),
        (("calibration", "relative_scale_uncertainty"), -0.1),
        (("identity_review", "status"), "verified"),
        (("source_sha256",), "not-a-sha256"),
        (("acquired_at_utc",), "not-a-date"),
        (("reviewers",), []),
    ],
)
def test_invalid_reference_evidence_is_rejected(path: tuple, value: object) -> None:
    record = copy.deepcopy(reference_record())
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not VALIDATOR.is_valid(record)


def test_verified_calibration_requires_reviewer_and_target() -> None:
    record = reference_record()
    record["calibration"]["verified"] = True
    assert not VALIDATOR.is_valid(record)
    record["calibration"]["reviewer_id"] = "synthetic-reviewer-a"
    record["calibration"]["reference_target_id"] = "synthetic-target"
    VALIDATOR.validate(record)


def test_confirmed_identity_requires_reviewer() -> None:
    record = reference_record()
    record["identity_review"]["status"] = "confirmed"
    assert not VALIDATOR.is_valid(record)
    record["identity_review"]["reviewer_id"] = "synthetic-reviewer-b"
    VALIDATOR.validate(record)


def test_anatomical_centerline_requires_branch_and_endpoint_digest() -> None:
    record = reference_record()
    measurement = record["reference_measurements"][0]
    measurement.update(metric="branch_centerline_length", unit="m")
    assert not VALIDATOR.is_valid(record)
    measurement["branch_id"] = "synthetic-branch"
    measurement["endpoint_annotation_sha256"] = HASH
    VALIDATOR.validate(record)


def test_independently_verified_reference_requires_numeric_uncertainty() -> None:
    record = reference_record()
    measurement = record["reference_measurements"][0]
    measurement["verification_status"] = "independently_verified"
    assert not VALIDATOR.is_valid(record)
    measurement["uncertainty_absolute"] = None
    assert not VALIDATOR.is_valid(record)
    measurement["uncertainty_absolute"] = 0.02
    VALIDATOR.validate(record)


@pytest.mark.parametrize(
    ("metric", "unit"),
    [("height", "m2"), ("mesh_edge_path_length", "m3"), ("enclosed_volume", "m")],
)
def test_metric_dimensions_are_enforced(metric: str, unit: str) -> None:
    record = reference_record()
    record["reference_measurements"][0].update(metric=metric, unit=unit)
    assert not VALIDATOR.is_valid(record)
