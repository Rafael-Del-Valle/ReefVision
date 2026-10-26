"""Do not count a tank twice when its registered sampling level uses aliases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyProjectedUnitSummary,
)
from reefvision.services.ecology_measurement_candidates import (
    summarize_projected_endpoint_changes,
    summarize_projected_population_summaries,
    summarize_projected_unit_summaries,
    summarize_projected_visit_coverage,
    summarize_sampling_date_qc,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def _unit(unit_type: str, organism: str, parent: str) -> EcologyProjectedUnitSummary:
    return EcologyProjectedUnitSummary(
        experimental_unit_type=unit_type,
        experimental_unit_id="tank-1",
        metric="box_width",
        units=["mm"],
        organism_keys=[organism],
        complete_organism_keys=[organism],
        incomplete_organism_keys=[],
        parent_colony_keys=[parent],
        sampling_windows_utc=["2026-04-03/2026-04-05"],
        unit_status="candidate",
        mean_absolute_change=2.0,
        mean_percent_change=20.0,
    )


@pytest.mark.parametrize("alias", ["aquarium", "aquaria", "tanks", "Tank-level"])
def test_population_rejects_aliases_of_one_independent_tank(alias: str) -> None:
    """An alias must not turn one physical tank into two statistical replicates."""
    rows = [_unit("tank", "fragment-A", "parent-A"), _unit(alias, "fragment-B", "parent-B")]
    with pytest.raises(ValidationError, match="Duplicate projected experimental-unit metric"):
        summarize_projected_population_summaries(rows)
    with pytest.raises(ValidationError, match="Duplicate projected experimental-unit metric"):
        summarize_projected_population_summaries(list(reversed(rows)))


def test_distinct_tanks_remain_distinct_declared_units() -> None:
    second = _unit("aquarium", "fragment-B", "parent-B").model_copy(
        update={"experimental_unit_id": "tank-2"}
    )
    summaries = summarize_projected_population_summaries(
        [_unit("tank", "fragment-A", "parent-A"), second]
    )
    # Aliases of one biological level must share a descriptive stratum;
    # different physical tank IDs still each contribute exactly one vote.
    assert len(summaries) == 1
    assert summaries[0].experimental_unit_type == "tank"
    assert summaries[0].experimental_unit_ids == ["tank-1", "tank-2"]
    assert summaries[0].declared_unit_count == 2
    assert summaries[0].mean_unit_absolute_change == pytest.approx(2.0)
    assert summaries[0].mean_unit_percent_change == pytest.approx(20.0)
    assert summaries[0].independent_unit_inference_allowed is False
    assert summaries[0].review_gate == "scientist_review_required"


def test_aliases_across_metrics_preserve_one_organism_owner() -> None:
    # A width/height analysis may legitimately use different spelling for
    # the same physical tank without reassigning the organism.
    width = _unit("tank", "fragment-A", "parent-A")
    height = _unit("aquarium", "fragment-A", "parent-A").model_copy(update={"metric": "box_height"})
    summaries = summarize_projected_population_summaries([width, height])
    assert len(summaries) == 2
    assert {row.metric for row in summaries} == {"box_width", "box_height"}
    assert all(row.experimental_unit_type == "tank" for row in summaries)
    assert all(row.declared_unit_count == 1 for row in summaries)
    assert all(row.independent_unit_inference_allowed is False for row in summaries)


def test_aliases_cannot_hide_cross_tank_organism_reassignment() -> None:
    width = _unit("tank", "fragment-A", "parent-A")
    height = _unit("aquarium", "fragment-A", "parent-A").model_copy(
        update={"metric": "box_height", "experimental_unit_id": "tank-2"}
    )
    with pytest.raises(
        ValidationError, match="One organism cannot be pooled across declared experimental units"
    ):
        summarize_projected_population_summaries([width, height])


def test_registered_aliases_remain_reviewable_in_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Tank aliases are one biological sampling level")
    project_id = str(project["id"])
    url = f"/api/v1/projects/{project_id}/ecology/organisms"
    for parent in ("parent-A", "parent-B"):
        registered = client.post(
            url,
            json={
                "organism_key": parent,
                "kind": "colony",
                "reason": "Registered parent colony for sampling-design audit",
            },
        )
        assert registered.status_code == 201, registered.text
    for organism, parent, unit_type in (
        ("fragment-A", "parent-A", "tank"),
        ("fragment-B", "parent-B", "aquarium"),
    ):
        registered = client.post(
            url,
            json={
                "organism_key": organism,
                "kind": "fragment",
                "parent_colony_key": parent,
                "experimental_unit_type": unit_type,
                "experimental_unit_id": "tank-1",
                "reason": "Same physical tank recorded with a biological unit alias",
            },
        )
        assert registered.status_code == 201, registered.text
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["review_gate"] == "scientist_review_required"
    assert {
        row["experimental_unit_type"]
        for row in registry.json()["identities"]
        if row["kind"] == "fragment"
    } == {"tank", "aquarium"}
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    registry_artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(registry_artifacts) == 1
    assert registry_artifacts[0]["payload_json"] == registry.json()
    candidate_artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(candidate_artifacts) == 1
    assert candidate_artifacts[0]["payload_json"]["projected_population_summaries"] == []
    standalone = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert standalone.status_code == 200, standalone.text
    assert (
        candidate_artifacts[0]["payload_json"]["projected_visit_coverage"]
        == standalone.json()["projected_visit_coverage"]
    )


def _visit_candidate(
    organism: str, unit_type: str, unit_id: str, day: int, image_id: str
) -> EcologyMeasurementCandidate:
    """Synthetic linked-unverified geometry for a bounded visit-coverage test."""
    return EcologyMeasurementCandidate(
        organism_key=organism,
        identity_revision=1,
        parent_colony_key="parent-A",
        experimental_unit_type=unit_type,
        experimental_unit_id=unit_id,
        image_id=image_id,
        image_sha256="a" * 64,
        annotation_evidence_id=f"annotation-{image_id}",
        calibration_evidence_id=f"calibration-{image_id}",
        annotation_kind="box",
        annotation_id=f"box-{image_id}",
        annotation_revision=1,
        annotation_sha256="b" * 64,
        calibration_sha256="c" * 64,
        metric="box_width",
        value=10.0,
        unit="mm",
        capture_timestamp_utc=datetime(2026, 4, day, tzinfo=UTC),
        capture_time_status="timezone_aware",
    )


def test_visit_coverage_combines_tank_aliases_without_claiming_absence() -> None:
    rows = summarize_projected_visit_coverage(
        [
            _visit_candidate("fragment-A", "tank", "tank-1", 3, "image-a"),
            _visit_candidate("fragment-B", "aquarium", "tank-1", 5, "image-b"),
        ]
    )
    assert len(rows) == 2
    assert [row.experimental_unit_type for row in rows] == ["tank", "tank"]
    assert [row.sampling_date_utc for row in rows] == ["2026-04-03", "2026-04-05"]
    assert all(row.series_organism_keys == ["fragment-A", "fragment-B"] for row in rows)
    assert [row.measured_organism_keys for row in rows] == [
        ["fragment-A"],
        ["fragment-B"],
    ]
    assert [row.no_linked_measurement_organism_keys for row in rows] == [
        ["fragment-B"],
        ["fragment-A"],
    ]
    assert all(row.evidence_level == "linked_unverified" for row in rows)
    assert all(row.review_gate == "scientist_review_required" for row in rows)


def test_visit_coverage_detects_same_day_alias_technical_replicates() -> None:
    rows = summarize_projected_visit_coverage(
        [
            _visit_candidate("fragment-A", "tank", "tank-1", 3, "image-a"),
            _visit_candidate("fragment-A", "aquarium", "tank-1", 3, "image-b"),
        ]
    )
    assert len(rows) == 1
    assert rows[0].linked_measurement_count == 2
    assert rows[0].same_day_repeat_organism_keys == ["fragment-A"]
    assert rows[0].no_linked_measurement_organism_keys == []


def test_visit_coverage_keeps_distinct_physical_tanks_separate() -> None:
    rows = summarize_projected_visit_coverage(
        [
            _visit_candidate("fragment-A", "tank", "tank-1", 3, "image-a"),
            _visit_candidate("fragment-B", "aquarium", "tank-2", 3, "image-b"),
        ]
    )
    assert len(rows) == 2
    assert {row.experimental_unit_id for row in rows} == {"tank-1", "tank-2"}
    assert all(row.experimental_unit_type == "tank" for row in rows)
    assert all(row.no_linked_measurement_organism_keys == [] for row in rows)


def _dated_alias_series(
    organism: str, unit_type: str, unit_id: str, image_offset: int, delta: float
) -> list[EcologyMeasurementCandidate]:
    """Unique image bytes/IDs; two source-linked UTC dates for one fragment."""
    result: list[EcologyMeasurementCandidate] = []
    for position, day in enumerate((3, 5)):
        image_number = image_offset + position
        image_id = f"image-{image_number}"
        source = _visit_candidate(organism, unit_type, unit_id, day, image_id)
        result.append(
            source.model_copy(
                update={
                    "image_sha256": f"{image_number:064x}",
                    "value": 10.0 + (delta if position else 0.0),
                }
            )
        )
    return result


def test_source_linked_aliases_pool_into_one_unit_not_two_replicates() -> None:
    """Alias normalization must happen before source-derived unit aggregation."""
    records = [
        *_dated_alias_series("fragment-A", "tank", "tank-1", 101, 2.0),
        *_dated_alias_series("fragment-B", "aquarium", "tank-1", 201, 4.0),
    ]
    qc = summarize_sampling_date_qc(records)
    assert [row.qc_status for row in qc] == ["date_series_candidate"] * 2
    changes = summarize_projected_endpoint_changes(records, qc)
    summaries = summarize_projected_unit_summaries(records, changes)
    assert len(summaries) == 1
    assert summaries[0].experimental_unit_type == "tank"
    assert summaries[0].experimental_unit_id == "tank-1"
    assert summaries[0].organism_keys == ["fragment-A", "fragment-B"]
    assert summaries[0].mean_absolute_change == pytest.approx(3.0)
    assert summaries[0].mean_percent_change == pytest.approx(30.0)
    assert summaries[0].review_gate == "scientist_review_required"
    population = summarize_projected_population_summaries(summaries)
    assert len(population) == 1
    assert population[0].declared_unit_count == 1
    assert population[0].contributing_organism_count == 2
    assert population[0].independent_unit_inference_allowed is False
    assert population[0].mean_unit_absolute_change == pytest.approx(3.0)
    reversed_records = list(reversed(records))
    reversed_changes = summarize_projected_endpoint_changes(
        reversed_records, summarize_sampling_date_qc(reversed_records)
    )
    assert summarize_projected_unit_summaries(reversed_records, reversed_changes) == summaries


def test_source_alias_across_metrics_preserves_one_organism_owner() -> None:
    width = _dated_alias_series("fragment-A", "tank", "tank-1", 301, 2.0)
    height = [
        record.model_copy(
            update={
                "metric": "box_height",
                "experimental_unit_type": "aquarium",
                "value": record.value * 2,
            }
        )
        for record in width
    ]
    records = width + height
    qc = summarize_sampling_date_qc(records)
    assert all(row.qc_status == "date_series_candidate" for row in qc)
    changes = summarize_projected_endpoint_changes(records, qc)
    summaries = summarize_projected_unit_summaries(records, changes)
    assert {row.metric for row in summaries} == {"box_width", "box_height"}
    assert {row.experimental_unit_type for row in summaries} == {"tank"}
    population = summarize_projected_population_summaries(summaries)
    assert len(population) == 2
    assert all(row.declared_unit_count == 1 for row in population)
    assert all(row.review_gate == "scientist_review_required" for row in population)


def test_source_alias_does_not_hide_cross_tank_reassignment() -> None:
    width = _dated_alias_series("fragment-A", "tank", "tank-1", 401, 2.0)
    height = [
        record.model_copy(
            update={
                "metric": "box_height",
                "experimental_unit_type": "aquarium",
                "experimental_unit_id": "tank-2",
                "value": record.value * 2,
            }
        )
        for record in width
    ]
    records = width + height
    changes = summarize_projected_endpoint_changes(records, summarize_sampling_date_qc(records))
    with pytest.raises(ValidationError, match="identity or experimental unit changed"):
        summarize_projected_unit_summaries(records, changes)


def test_source_mixed_biological_levels_fail_closed() -> None:
    records = _dated_alias_series("fragment-A", "tank/site", "tank-1", 501, 2.0)
    changes = summarize_projected_endpoint_changes(records, summarize_sampling_date_qc(records))
    with pytest.raises(ValidationError, match="mixes biological sampling levels"):
        summarize_projected_unit_summaries(records, changes)


@pytest.mark.parametrize("technical_type", ["camera tank", "image-tank", "frame aquarium"])
def test_technical_compound_label_is_not_laundered_into_biological_unit(
    technical_type: str,
) -> None:
    records = _dated_alias_series("fragment-A", technical_type, "tank-1", 601, 2.0)
    changes = summarize_projected_endpoint_changes(records, summarize_sampling_date_qc(records))
    summaries = summarize_projected_unit_summaries(records, changes)
    assert len(summaries) == 1
    assert summaries[0].experimental_unit_type == technical_type
    assert summaries[0].unit_status == "technical_replicate_unit"
    assert summaries[0].review_gate == "scientist_review_required"
    assert summarize_projected_population_summaries(summaries) == []


@pytest.mark.parametrize(
    "technical_type",
    ["camera tank", "image-tank", "frame aquarium", "camera"],
)
def test_forged_technical_candidate_cannot_enter_population(
    technical_type: str,
) -> None:
    # A tampered intermediate unit row must not bypass source-level QC.
    forged = _unit(technical_type, "fragment-A", "parent-A")
    with pytest.raises(
        ValidationError, match="Technical replicate cannot enter projected population"
    ):
        summarize_projected_population_summaries([forged])


def test_organism_level_unit_cannot_pool_distinct_fragments() -> None:
    forged = _unit("organism", "fragment-A", "parent-A").model_copy(
        update={
            "organism_keys": ["fragment-A", "fragment-B"],
            "complete_organism_keys": ["fragment-A", "fragment-B"],
        }
    )
    with pytest.raises(ValidationError, match="organism-level unit"):
        summarize_projected_population_summaries([forged])


def test_colony_level_unit_cannot_pool_different_parents() -> None:
    forged = _unit("colony", "fragment-A", "parent-A").model_copy(
        update={"parent_colony_keys": ["parent-A", "parent-B"]}
    )
    with pytest.raises(ValidationError, match="different parent colonies"):
        summarize_projected_population_summaries([forged])


def test_parent_colony_cannot_be_split_into_independent_colony_units() -> None:
    first = _unit("colony", "fragment-A", "parent-A").model_copy(
        update={"experimental_unit_id": "colony-1"}
    )
    second = _unit("colonies", "fragment-B", "parent-A").model_copy(
        update={"experimental_unit_id": "colony-2"}
    )
    with pytest.raises(ValidationError, match="multiple independent colony units"):
        summarize_projected_population_summaries([first, second])


def test_source_linked_colony_split_is_rejected_but_tank_split_is_reviewable() -> None:
    colony_records = [
        *_dated_alias_series("fragment-A", "colony", "colony-1", 701, 2.0),
        *_dated_alias_series("fragment-B", "colonies", "colony-2", 801, 4.0),
    ]
    qc = summarize_sampling_date_qc(colony_records)
    assert all(row.qc_status == "date_series_candidate" for row in qc)
    changes = summarize_projected_endpoint_changes(colony_records, qc)
    units = summarize_projected_unit_summaries(colony_records, changes)
    assert len(units) == 2
    with pytest.raises(ValidationError, match="multiple independent colony units"):
        summarize_projected_population_summaries(units)

    tank_records = [
        *_dated_alias_series("fragment-A", "tank", "tank-1", 901, 2.0),
        *_dated_alias_series("fragment-B", "aquarium", "tank-2", 1001, 4.0),
    ]
    tank_qc = summarize_sampling_date_qc(tank_records)
    tank_changes = summarize_projected_endpoint_changes(tank_records, tank_qc)
    tank_units = summarize_projected_unit_summaries(tank_records, tank_changes)
    tank_population = summarize_projected_population_summaries(tank_units)
    assert len(tank_population) == 1
    assert tank_population[0].declared_unit_count == 2
    assert tank_population[0].shared_parent_colony_keys == ["parent-A"]
    assert "shared_parent_colonies" in tank_population[0].design_review_blockers
    assert tank_population[0].independent_unit_inference_allowed is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("experimental_unit_id", " "),
        ("experimental_unit_id", "tank-1 "),
        ("experimental_unit_id", " tank-1"),
        ("organism_keys", ["fragment-A", " "]),
        ("organism_keys", [" fragment-A"]),
        ("parent_colony_keys", ["parent-A "]),
    ],
)
def test_forged_population_unit_rejects_blank_or_padded_lineage(
    field: str, value: str | list[str]
) -> None:
    """Re-signed intermediate summaries cannot invent distinct biological IDs."""
    forged = _unit("tank", "fragment-A", "parent-A").model_copy(update={field: value})
    with pytest.raises(ValidationError, match="blank or padded"):
        summarize_projected_population_summaries([forged])


def test_source_linked_padded_unit_id_cannot_enter_population() -> None:
    """Even complete projected time series must not promote padded tank IDs."""
    records = _dated_alias_series("fragment-A", "tank", "tank-1 ", 1101, 2.0)
    qc = summarize_sampling_date_qc(records)
    changes = summarize_projected_endpoint_changes(records, qc)
    units = summarize_projected_unit_summaries(records, changes)
    assert len(units) == 1
    assert units[0].unit_status == "candidate"
    with pytest.raises(ValidationError, match="experimental-unit ID is blank or padded"):
        summarize_projected_population_summaries(units)


@pytest.mark.parametrize("second_parents", [["parent-B"], []])
def test_forged_cross_metric_parent_lineage_cannot_change(
    second_parents: list[str],
) -> None:
    """The same physical unit and complete organism roster have one parent set."""
    width = _unit("tank", "fragment-A", "parent-A")
    height = _unit("aquarium", "fragment-A", "parent-A").model_copy(
        update={"metric": "box_height", "parent_colony_keys": second_parents}
    )
    with pytest.raises(ValidationError, match="parent-colony provenance changes"):
        summarize_projected_population_summaries([width, height])
    with pytest.raises(ValidationError, match="parent-colony provenance changes"):
        summarize_projected_population_summaries([height, width])


def test_forged_parent_count_cannot_exceed_complete_organism_count() -> None:
    """One fragment cannot independently represent two registered parents."""
    forged = _unit("tank", "fragment-A", "parent-A").model_copy(
        update={"parent_colony_keys": ["parent-A", "parent-B"]}
    )
    with pytest.raises(ValidationError, match="more parent colonies than organisms"):
        summarize_projected_population_summaries([forged])


def test_cross_metric_parent_lineage_is_order_invariant_for_same_roster() -> None:
    """Biological unit aliases and parent ordering cannot change the decision."""
    width = _unit("tank", "fragment-A", "parent-A").model_copy(
        update={
            "organism_keys": ["fragment-A", "fragment-B"],
            "complete_organism_keys": ["fragment-A", "fragment-B"],
            "parent_colony_keys": ["parent-A", "parent-B"],
        }
    )
    height = width.model_copy(
        update={
            "metric": "box_height",
            "experimental_unit_type": "aquarium",
            "parent_colony_keys": ["parent-B", "parent-A"],
        }
    )
    for rows in ([width, height], [height, width]):
        summaries = summarize_projected_population_summaries(rows)
        assert len(summaries) == 2
        assert all(row.declared_unit_count == 1 for row in summaries)
        assert all(row.review_gate == "scientist_review_required" for row in summaries)


def test_different_metric_organism_rosters_are_not_assumed_identical() -> None:
    """A missing measurement metric does not imply changed biological parentage."""
    width = _unit("tank", "fragment-A", "parent-A")
    height = _unit("aquarium", "fragment-B", "parent-B").model_copy(update={"metric": "box_height"})
    summaries = summarize_projected_population_summaries([width, height])
    assert len(summaries) == 2
    assert all(row.independent_unit_inference_allowed is False for row in summaries)


def _partial_metric_roster(
    metric: str, organisms: list[str], parents: list[str]
) -> EcologyProjectedUnitSummary:
    unit_type = "aquarium" if metric == "box_height" else "tank"
    return _unit(unit_type, "fragment-A", "parent-A").model_copy(
        update={
            "metric": metric,
            "organism_keys": organisms,
            "complete_organism_keys": organisms,
            "parent_colony_keys": parents,
        }
    )


def test_overlapping_metric_rosters_reject_impossible_parent_lineage() -> None:
    """A shared fragment cannot have disjoint fully known parent candidates."""
    width = _partial_metric_roster(
        "box_width", ["fragment-A", "fragment-B"], ["parent-A", "parent-B"]
    )
    height = _partial_metric_roster(
        "box_height", ["fragment-A", "fragment-C"], ["parent-C", "parent-D"]
    )
    for rows in ([width, height], [height, width]):
        with pytest.raises(ValidationError, match="parent-colony candidates conflict"):
            summarize_projected_population_summaries(rows)


def test_overlapping_metric_rosters_preserve_possible_parent_lineage() -> None:
    """Shared parent candidates do not establish which parent owns a fragment."""
    width = _partial_metric_roster(
        "box_width", ["fragment-A", "fragment-B"], ["parent-A", "parent-B"]
    )
    height = _partial_metric_roster(
        "box_height", ["fragment-A", "fragment-C"], ["parent-B", "parent-C"]
    )
    for rows in ([width, height], [height, width]):
        summaries = summarize_projected_population_summaries(rows)
        assert len(summaries) == 2
        assert all(row.review_gate == "scientist_review_required" for row in summaries)
        assert all(row.independent_unit_inference_allowed is False for row in summaries)


def test_partial_parent_rosters_do_not_invent_organism_parent_assignments() -> None:
    """A parent list shorter than the organism roster is not a full mapping."""
    width = _partial_metric_roster("box_width", ["fragment-A", "fragment-B"], ["parent-A"])
    height = _partial_metric_roster("box_height", ["fragment-A", "fragment-C"], ["parent-B"])
    summaries = summarize_projected_population_summaries([width, height])
    assert len(summaries) == 2
    assert all(row.review_gate == "scientist_review_required" for row in summaries)


@pytest.mark.parametrize("reverse_order", [False, True])
def test_full_parent_rosters_require_jointly_feasible_assignments(
    reverse_order: bool,
) -> None:
    """Pairwise overlap is insufficient when every parent is forced to A."""
    width = _partial_metric_roster(
        "box_width", ["fragment-A", "fragment-B"], ["parent-A", "parent-B"]
    )
    height = _partial_metric_roster(
        "box_height", ["fragment-A", "fragment-C"], ["parent-A", "parent-C"]
    )
    area = _partial_metric_roster(
        "mask_projected_area",
        ["fragment-B", "fragment-C"],
        ["parent-A", "parent-D"],
    )
    rows = [width, height, area]
    if reverse_order:
        rows.reverse()
    with pytest.raises(ValidationError, match="jointly impossible across metrics"):
        summarize_projected_population_summaries(rows)


@pytest.mark.parametrize("reverse_order", [False, True])
def test_full_parent_rosters_allow_a_feasible_unverified_mapping(
    reverse_order: bool,
) -> None:
    """Do not infer a parent mapping, but retain feasible descriptive rows."""
    width = _partial_metric_roster(
        "box_width", ["fragment-A", "fragment-B"], ["parent-A", "parent-B"]
    )
    height = _partial_metric_roster(
        "box_height", ["fragment-A", "fragment-C"], ["parent-A", "parent-C"]
    )
    area = _partial_metric_roster(
        "mask_projected_area",
        ["fragment-B", "fragment-C"],
        ["parent-B", "parent-C"],
    )
    rows = [width, height, area]
    if reverse_order:
        rows.reverse()
    summaries = summarize_projected_population_summaries(rows)
    assert len(summaries) == 3
    assert all(row.declared_unit_count == 1 for row in summaries)
    assert all(row.independent_unit_inference_allowed is False for row in summaries)
    assert all(row.review_gate == "scientist_review_required" for row in summaries)


def test_partial_parent_roster_does_not_require_invented_distinct_parents() -> None:
    """Partial lineage evidence cannot justify a one-to-one parent constraint."""
    width = _partial_metric_roster(
        "box_width", ["fragment-A", "fragment-B"], ["parent-A", "parent-B"]
    )
    height = _partial_metric_roster(
        "box_height", ["fragment-A", "fragment-C"], ["parent-A", "parent-C"]
    )
    area = _partial_metric_roster(
        "mask_projected_area", ["fragment-B", "fragment-C"], ["parent-A"]
    )
    summaries = summarize_projected_population_summaries([width, height, area])
    assert len(summaries) == 3
    assert all(row.review_gate == "scientist_review_required" for row in summaries)
