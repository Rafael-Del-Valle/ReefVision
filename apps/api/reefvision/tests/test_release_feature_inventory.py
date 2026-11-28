from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_release_feature_inventory import render_inventory, validate_inventory  # noqa: E402

EVIDENCE_KINDS = (
    "source",
    "browser",
    "windows_installed",
    "physical_hardware",
    "representative_data",
)


def valid_document() -> dict[str, object]:
    evidence = {
        kind: [
            {
                "id": f"evidence-{kind}",
                "description": f"Verified {kind.replace('_', ' ')} behavior.",
                "artifact": f"docs/evidence/{kind}.md",
            }
        ]
        for kind in EVIDENCE_KINDS
    }
    return {
        "schema_version": "1.0",
        "candidate_target": "2.0",
        "updated_at": "2026-11-15T12:00:00Z",
        "sources": [
            {
                "id": "product-spec",
                "label": "Product specification",
                "location": "docs/REEFVISION_PRODUCT_SPEC.md",
            }
        ],
        "features": [
            {
                "id": "rv11-example",
                "title": "Example verified feature",
                "target_version": "1.1",
                "source_refs": ["product-spec"],
                "dependencies": [],
                "user_facing": True,
                "entry_point": "Open a project → Review → Example",
                "workflow_builder": "required",
                "acceptance_checks": [
                    {
                        "id": "rv11-example-check",
                        "description": "Complete the example from normal project navigation.",
                        "status": "verified",
                        "evidence": ["evidence-source", "evidence-browser"],
                    }
                ],
                "applicable_evidence": list(EVIDENCE_KINDS),
                "evidence": evidence,
                "status": "verified",
                "missing_input": None,
                "defer_reason": None,
                "notes": "Synthetic and representative evidence are recorded separately.",
            },
            {
                "id": "rv12-dependent",
                "title": "Dependent implementation",
                "target_version": "1.2",
                "source_refs": ["product-spec"],
                "dependencies": ["rv11-example"],
                "user_facing": False,
                "entry_point": None,
                "workflow_builder": "not_applicable",
                "acceptance_checks": [
                    {
                        "id": "rv12-dependent-check",
                        "description": "Preserve the dependent record during exchange.",
                        "status": "blocked",
                        "evidence": [],
                    }
                ],
                "applicable_evidence": ["source"],
                "evidence": {kind: [] for kind in EVIDENCE_KINDS},
                "status": "blocked",
                "missing_input": (
                    "A signed historical exchange fixture from an independent project."
                ),
                "defer_reason": None,
                "notes": "Non-UI persistence contract.",
            },
            {
                "id": "scope-deferred",
                "title": "Deferred scope",
                "target_version": "post-2.0",
                "source_refs": ["product-spec"],
                "dependencies": [],
                "user_facing": False,
                "entry_point": None,
                "workflow_builder": "deferred",
                "acceptance_checks": [
                    {
                        "id": "scope-deferred-check",
                        "description": "Confirm the capability is absent from supported builds.",
                        "status": "verified",
                        "evidence": ["scope-deferred-source"],
                    }
                ],
                "applicable_evidence": ["source"],
                "evidence": {
                    **{kind: [] for kind in EVIDENCE_KINDS},
                    "source": [
                        {
                            "id": "scope-deferred-source",
                            "description": "Approved scope decision.",
                            "artifact": "docs/decisions/scope.md",
                        }
                    ],
                },
                "status": "explicitly_deferred",
                "missing_input": None,
                "defer_reason": "Owner explicitly placed this capability beyond 2.0.",
                "notes": "Historical metadata remains readable.",
            },
        ],
    }


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "title",
        "target_version",
        "source_refs",
        "dependencies",
        "user_facing",
        "workflow_builder",
        "acceptance_checks",
        "applicable_evidence",
        "evidence",
        "status",
        "missing_input",
        "defer_reason",
    ],
)
def test_feature_records_require_the_release_contract_fields(field: str) -> None:
    document = valid_document()
    del document["features"][0][field]  # type: ignore[index]

    errors = validate_inventory(document)

    assert any(f"missing required field '{field}'" in error for error in errors)


def test_feature_ids_and_acceptance_check_ids_must_be_unique() -> None:
    document = valid_document()
    features = document["features"]  # type: ignore[assignment]
    features[1]["id"] = "rv11-example"
    features[1]["acceptance_checks"][0]["id"] = "rv11-example-check"

    errors = validate_inventory(document)

    assert "duplicate feature id 'rv11-example'" in errors
    assert "duplicate acceptance check id 'rv11-example-check'" in errors


def test_dependencies_and_source_references_must_resolve() -> None:
    document = valid_document()
    feature = document["features"][0]  # type: ignore[index]
    feature["dependencies"] = ["rv99-missing"]
    feature["source_refs"] = ["missing-source"]

    errors = validate_inventory(document)

    assert "feature 'rv11-example' references unknown dependency 'rv99-missing'" in errors
    assert "feature 'rv11-example' references unknown source 'missing-source'" in errors


def test_status_and_workflow_values_are_closed_enums() -> None:
    document = valid_document()
    feature = document["features"][0]  # type: ignore[index]
    feature["status"] = "mostly_done"
    feature["workflow_builder"] = "maybe"

    errors = validate_inventory(document)

    assert "feature 'rv11-example' has invalid status 'mostly_done'" in errors
    assert "feature 'rv11-example' has invalid workflow_builder value 'maybe'" in errors


def test_blocked_and_deferred_features_explain_their_release_state() -> None:
    document = valid_document()
    blocked = document["features"][1]  # type: ignore[index]
    deferred = document["features"][2]  # type: ignore[index]
    blocked["missing_input"] = "  "
    deferred["defer_reason"] = None

    errors = validate_inventory(document)

    assert "blocked feature 'rv12-dependent' requires an exact missing_input" in errors
    assert "deferred feature 'scope-deferred' requires a defer_reason" in errors


def test_user_facing_features_require_a_normal_navigation_entry_point() -> None:
    document = valid_document()
    document["features"][0]["entry_point"] = None  # type: ignore[index]

    errors = validate_inventory(document)

    assert "user-facing feature 'rv11-example' requires an entry_point" in errors


def test_verified_features_require_verified_checks_and_applicable_evidence() -> None:
    document = valid_document()
    feature = document["features"][0]  # type: ignore[index]
    feature["acceptance_checks"][0]["status"] = "in_progress"
    feature["evidence"]["representative_data"] = []

    errors = validate_inventory(document)

    assert (
        "verified feature 'rv11-example' has unresolved acceptance check 'rv11-example-check'"
        in errors
    )
    assert "verified feature 'rv11-example' lacks representative_data evidence" in errors


def test_evidence_categories_are_complete_and_check_references_resolve() -> None:
    document = valid_document()
    feature = document["features"][0]  # type: ignore[index]
    del feature["evidence"]["physical_hardware"]
    feature["acceptance_checks"][0]["evidence"] = ["unknown-evidence"]

    errors = validate_inventory(document)

    assert "feature 'rv11-example' evidence is missing category 'physical_hardware'" in errors
    assert (
        "acceptance check 'rv11-example-check' references unknown evidence 'unknown-evidence'"
        in errors
    )


def test_rendering_is_deterministic_and_does_not_mutate_the_document() -> None:
    document = valid_document()
    before = copy.deepcopy(document)

    first = render_inventory(document)
    second = render_inventory(document)

    assert first == second
    assert document == before
    assert "# ReefVision 2.0 Feature Inventory" in first
    assert "| 1.1 | Example verified feature | verified |" in first
    assert "A signed historical exchange fixture" in first


def test_rendering_has_no_trailing_whitespace() -> None:
    rendered = render_inventory(valid_document())

    assert all(line == line.rstrip() for line in rendered.splitlines())
