"""Input fingerprints survive standalone and saved ecological workflow execution."""

from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.domain.model_agreement import compare_paired_counts
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest
from reefvision.schemas.model_agreement import PairedCountComparisonRequest
from reefvision.tests.test_longitudinal_monitoring import observation
from reefvision.tests.test_workflow_model_agreement_1_2 import _pairs


def _observations() -> list[dict[str, object]]:
    return [
        observation("coral-1", "2026-04-01T12:00:00Z", 10, "day-0"),
        observation("coral-1", "2026-04-02T12:00:00Z", 12, "day-1"),
    ]


def test_longitudinal_digest_is_order_independent_and_normalizes_timezones() -> None:
    records = _observations()
    baseline = analyze_longitudinal(LongitudinalAnalysisRequest(observations=records))
    reversed_records = [dict(row) for row in reversed(records)]
    reversed_records[0]["observed_at"] = "2026-04-02T07:00:00-05:00"
    again = analyze_longitudinal(LongitudinalAnalysisRequest(observations=reversed_records))
    assert baseline.analysis_provenance == again.analysis_provenance
    assert baseline.analysis_provenance.source_record_ids == ["day-0", "day-1"]
    assert baseline.analysis_provenance.source_verification == "caller_supplied_unverified"


def test_longitudinal_digest_detects_changed_measurements_and_source_identity() -> None:
    records = _observations()
    original = analyze_longitudinal(LongitudinalAnalysisRequest(observations=records))
    modified = [dict(row) for row in records]
    modified[1]["value"] = 13
    changed = analyze_longitudinal(LongitudinalAnalysisRequest(observations=modified))
    assert original.analysis_provenance.canonical_input_sha256 != (
        changed.analysis_provenance.canonical_input_sha256
    )
    modified[1]["source_record_id"] = "day-1-new"
    changed_source = analyze_longitudinal(LongitudinalAnalysisRequest(observations=modified))
    assert changed.analysis_provenance.canonical_input_sha256 != (
        changed_source.analysis_provenance.canonical_input_sha256
    )


def test_paired_digest_includes_reference_kind_and_counts() -> None:
    pairs = _pairs()
    request = PairedCountComparisonRequest(pairs=pairs, reference_kind="human_consensus")
    original = compare_paired_counts(request)
    reversed_result = compare_paired_counts(
        PairedCountComparisonRequest(pairs=list(reversed(pairs)), reference_kind="human_consensus")
    )
    assert original.analysis_provenance == reversed_result.analysis_provenance
    assert original.analysis_provenance.source_record_ids == sorted(
        ["human-image-1", "human-image-2", "model-image-1", "model-image-2"]
    )
    different_reference = compare_paired_counts(
        PairedCountComparisonRequest(pairs=pairs, reference_kind="human_observer")
    )
    assert original.analysis_provenance.canonical_input_sha256 != (
        different_reference.analysis_provenance.canonical_input_sha256
    )
    modified = [dict(row) for row in pairs]
    modified[0]["model_count"] = 13
    changed_count = compare_paired_counts(
        PairedCountComparisonRequest(pairs=modified, reference_kind="human_consensus")
    )
    assert original.analysis_provenance.canonical_input_sha256 != (
        changed_count.analysis_provenance.canonical_input_sha256
    )


def test_standalone_api_exposes_versioned_unverified_fingerprints(client: TestClient) -> None:
    longitudinal = client.post(
        "/api/v1/ecology/longitudinal-analysis", json={"observations": _observations()}
    )
    paired = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": _pairs(), "reference_kind": "human_consensus"},
    )
    assert longitudinal.status_code == 200, longitudinal.text
    assert paired.status_code == 200, paired.text
    for response in (longitudinal, paired):
        provenance = response.json()["analysis_provenance"]
        assert len(provenance["canonical_input_sha256"]) == 64
        assert provenance["canonicalization"] == "normalized_sorted_json_v1"
        assert provenance["source_verification"] == "caller_supplied_unverified"
        assert provenance["algorithm_version"].startswith("ecology-")
