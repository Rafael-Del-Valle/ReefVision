"""Source-unverified lineage safeguards against pseudoreplication."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from reefvision.domain.ecology_lineage_policy import validate_declared_lineage
from reefvision.domain.errors import ValidationError


@dataclass(frozen=True)
class Pair:
    organism_id: str
    parent_colony_id: str | None
    experimental_unit_id: str | None


def test_organism_unit_cannot_contain_multiple_organisms() -> None:
    rows = [Pair("frag-A", None, "unit-1"), Pair("frag-B", None, "unit-1")]
    with pytest.raises(ValidationError, match="distinct organisms"):
        validate_declared_lineage(rows, experimental_unit_type="organism")


def test_colony_unit_cannot_mix_parents() -> None:
    rows = [Pair("frag-A", "colony-1", "unit-1"), Pair("frag-B", "colony-2", "unit-1")]
    with pytest.raises(ValidationError, match="different parent colonies"):
        validate_declared_lineage(rows, experimental_unit_type="colony")


def test_one_colony_cannot_be_split_into_multiple_colony_units() -> None:
    rows = [Pair("frag-A", "colony-1", "unit-1"), Pair("frag-B", "colony-1", "unit-2")]
    with pytest.raises(ValidationError, match="multiple independent colony units"):
        validate_declared_lineage(rows, experimental_unit_type="parent_colony")


def test_organism_parent_reassignment_rejected() -> None:
    rows = [Pair("frag-A", "colony-1", "tank-1"), Pair("frag-A", "colony-2", "tank-1")]
    with pytest.raises(ValidationError, match="cannot change parent_colony_id"):
        validate_declared_lineage(rows, experimental_unit_type="tank")


def test_partial_parent_coverage_rejected() -> None:
    rows = [Pair("frag-A", "colony-1", "tank-1"), Pair("frag-B", None, "tank-1")]
    with pytest.raises(ValidationError, match="Partial parent_colony_id coverage"):
        validate_declared_lineage(rows, experimental_unit_type="tank")


def test_fragments_from_one_parent_across_tanks_are_allowed() -> None:
    rows = [Pair("frag-A", "colony-1", "tank-1"), Pair("frag-B", "colony-1", "tank-2")]
    validate_declared_lineage(rows, experimental_unit_type="tank")


def test_two_fragments_from_one_parent_in_colony_unit_are_allowed() -> None:
    rows = [Pair("frag-A", "colony-1", "colony-unit"), Pair("frag-B", "colony-1", "colony-unit")]
    validate_declared_lineage(rows, experimental_unit_type="colony")


def test_unlabeled_legacy_colony_inputs_remain_unverified_and_compatible() -> None:
    rows = [Pair("frag-A", None, "unit-1"), Pair("frag-B", None, "unit-2")]
    validate_declared_lineage(rows, experimental_unit_type="colony")


@pytest.mark.parametrize("unit_type", ["colony replicate", "parent colony sampling unit"])
def test_colony_level_descriptors_cannot_bypass_parent_check(unit_type: str) -> None:
    rows = [Pair("frag-A", "colony-1", "unit-1"), Pair("frag-B", "colony-2", "unit-1")]
    with pytest.raises(ValidationError, match="different parent colonies"):
        validate_declared_lineage(rows, experimental_unit_type=unit_type)


@pytest.mark.parametrize("unit_type", ["fragment replicate", "individual sample"])
def test_organism_level_descriptors_cannot_merge_individuals(unit_type: str) -> None:
    rows = [Pair("frag-A", None, "unit-1"), Pair("frag-B", None, "unit-1")]
    with pytest.raises(ValidationError, match="distinct organisms"):
        validate_declared_lineage(rows, experimental_unit_type=unit_type)


@pytest.mark.parametrize(
    "unit_type",
    ["colony/tank", "tank and site", "organism-colony", "TankColony", "OrganismTank"],
)
def test_compound_biological_levels_are_rejected(unit_type: str) -> None:
    rows = [Pair("frag-A", "colony-1", "unit-1"), Pair("frag-B", "colony-2", "unit-1")]
    with pytest.raises(ValidationError, match="Ambiguous experimental_unit_type"):
        validate_declared_lineage(rows, experimental_unit_type=unit_type)
