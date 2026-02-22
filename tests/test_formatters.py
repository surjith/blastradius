"""Tests for orchestration.formatters — output formatting functions."""

from __future__ import annotations

import pytest

from core.models import (
    BlastRadiusResults,
    ChangeSpec,
    ImpactItem,
    ImpactReport,
    ImpactSummary,
    ScenarioDeltaSummary,
    ScenarioResult,
    ScenarioSpec,
    TraversalSpec,
)
from orchestration.formatters import (
    format_blast,
    format_impact,
    format_simulation,
    _removed_list,
)


# ─── Fixtures / helpers ──────────────────────────────────────────────────────

@pytest.fixture
def blast_result():
    return BlastRadiusResults(
        start="urn:a",
        depth=2,
        direction="out",
        reached=["urn:b", "urn:c"],
        paths={
            "urn:b": [["urn:a", "urn:b"]],
            "urn:c": [["urn:a", "urn:b", "urn:c"]],
        },
    )


@pytest.fixture
def impact_report():
    change = ChangeSpec(change_type="relationship_change", target_uri="urn:a")
    traversal = TraversalSpec(depth=2, direction="out")
    return ImpactReport(
        change=change,
        traversal=traversal,
        summary=ImpactSummary(counts_by_type={"Product": 2, "Variant": 1}, total_impacted=3),
        top_impacts=[
            ImpactItem(uri="urn:b", entity_type="Product", severity=5, primary_path=["urn:a", "urn:b"]),
        ],
        impacted_uris=["urn:b", "urn:c", "urn:d"],
    )


@pytest.fixture
def scenario_result(impact_report):
    change = ChangeSpec(change_type="relationship_change", target_uri="urn:a")
    traversal = TraversalSpec(depth=2, direction="out")
    scenario = ScenarioSpec(scenario_id="test_sc", description="A test scenario")

    sim_report = ImpactReport(
        change=change,
        traversal=traversal,
        summary=ImpactSummary(counts_by_type={"Product": 1}, total_impacted=1),
        top_impacts=[
            ImpactItem(uri="urn:b", entity_type="Product", severity=3, primary_path=["urn:a", "urn:b"]),
        ],
        impacted_uris=["urn:b"],
    )

    return ScenarioResult(
        scenario=scenario,
        change=change,
        traversal=traversal,
        baseline=impact_report,
        simulated=sim_report,
        delta=ScenarioDeltaSummary(
            total_impacted_baseline=3,
            total_impacted_simulated=1,
            delta_counts_by_type={"Product": -1, "Variant": -1},
            newly_impacted=[],
            removed_impacts=["urn:c", "urn:d"],
        ),
    )


# ─── format_blast ────────────────────────────────────────────────────────────

class TestFormatBlast:
    def test_contains_start_and_depth(self, blast_result):
        output = format_blast(blast_result)
        assert "start=urn:a" in output
        assert "depth=2" in output

    def test_lists_reached_nodes(self, blast_result):
        output = format_blast(blast_result)
        assert "urn:b" in output
        assert "urn:c" in output

    def test_shows_paths(self, blast_result):
        output = format_blast(blast_result)
        assert "urn:a -> urn:b" in output

    def test_truncation_message(self):
        reached = [f"urn:node{i}" for i in range(30)]
        paths = {n: [[f"urn:start", n]] for n in reached}
        res = BlastRadiusResults(start="urn:start", depth=1, direction="out", reached=reached, paths=paths)
        output = format_blast(res, max_nodes=5)
        assert "25 more" in output

    def test_empty_reached(self):
        res = BlastRadiusResults(start="urn:x", depth=1, direction="out", reached=[], paths={})
        output = format_blast(res)
        assert "Reached=0" in output


# ─── format_impact ───────────────────────────────────────────────────────────

class TestFormatImpact:
    def test_contains_change_info(self, impact_report):
        output = format_impact(impact_report)
        assert "relationship_change" in output
        assert "urn:a" in output

    def test_contains_totals(self, impact_report):
        output = format_impact(impact_report)
        assert "Total impacted=3" in output

    def test_counts_by_type(self, impact_report):
        output = format_impact(impact_report)
        assert "Product: 2" in output
        assert "Variant: 1" in output

    def test_top_impacts_listed(self, impact_report):
        output = format_impact(impact_report)
        assert "sev=5" in output
        assert "urn:b" in output


# ─── format_simulation ──────────────────────────────────────────────────────

class TestFormatSimulation:
    def test_contains_scenario_id(self, scenario_result):
        output = format_simulation(scenario_result)
        assert "test_sc" in output

    def test_contains_description(self, scenario_result):
        output = format_simulation(scenario_result)
        assert "A test scenario" in output

    def test_baseline_and_simulated_counts(self, scenario_result):
        output = format_simulation(scenario_result)
        assert "Baseline impacted=3" in output
        assert "Simulated impacted=1" in output

    def test_delta_counts(self, scenario_result):
        output = format_simulation(scenario_result)
        assert "Product: -1" in output

    def test_removed_impacts(self, scenario_result):
        output = format_simulation(scenario_result)
        assert "Removed impacts=2" in output
        assert "urn:c" in output
        assert "urn:d" in output


# ─── _removed_list helper ───────────────────────────────────────────────────

class TestRemovedList:
    def test_with_removed_impacts_attr(self):
        from types import SimpleNamespace

        delta = SimpleNamespace(removed_impacts=["a", "b"])
        assert _removed_list(delta) == ["a", "b"]

    def test_with_no_longer_impacted_attr(self):
        from types import SimpleNamespace

        delta = SimpleNamespace(no_longer_impacted=["c"])
        assert _removed_list(delta) == ["c"]

    def test_with_neither_attr(self):
        from types import SimpleNamespace

        delta = SimpleNamespace()
        assert _removed_list(delta) == []
