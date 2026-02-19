from types import SimpleNamespace

import pytest

from core.models import (
    ChangeSpec,
    ImpactItem,
    ImpactReport,
    ImpactSummary,
    ScenarioSpec,
    TraversalSpec,
    AttributeOverride,
)
from core.simulate_change import (
    _diff_counts_by_type,
    _validate_report_invariants,
    simulate_change,
)
from core.scenario import apply_scenario_to_graph as _real_apply_scenario_to_graph


def _make_report(
    change: ChangeSpec,
    traversal: TraversalSpec,
    impacted_uris: list[str],
    counts_by_type: dict[str, int],
    total_impacted: int | None = None,
    top_impact_uri: str | None = None,
) -> ImpactReport:
    """
    Helper to build minimal ImpactReport objects for pure unit/wiring tests.
    """
    if total_impacted is None:
        total_impacted = len(impacted_uris)

    top_impacts: list[ImpactItem] = []
    if top_impact_uri is not None:
        top_impacts = [
            ImpactItem(
                uri=top_impact_uri,
                entity_type="Product",
                severity=3,
                primary_path=[change.target_uri, top_impact_uri],
            )
        ]

    return ImpactReport(
        change=change,
        traversal=traversal,
        summary=ImpactSummary(counts_by_type=counts_by_type, total_impacted=total_impacted),
        top_impacts=top_impacts,
        impacted_uris=impacted_uris,
    )


# ------------------------
# Unit tests (pure helpers)
# ------------------------

def test_diff_counts_by_type_is_sorted_and_correct():
    baseline = {"Product": 2, "Order": 1}
    simulated = {"Product": 3, "Metafield": 2}

    delta = _diff_counts_by_type(baseline, simulated)

    assert list(delta.keys()) == ["Metafield", "Order", "Product"]
    assert delta["Metafield"] == 2
    assert delta["Order"] == -1
    assert delta["Product"] == 1


def test_validate_report_invariants_accepts_valid_report():
    change = ChangeSpec(change_type="schema_change", target_uri="urn:start")
    traversal = TraversalSpec(depth=2, direction="out")
    report = _make_report(
        change=change,
        traversal=traversal,
        impacted_uris=["urn:a", "urn:b"],
        counts_by_type={"Product": 2},
        top_impact_uri="urn:a",
    )
    _validate_report_invariants(report)


def test_validate_report_invariants_rejects_mismatched_total():
    change = ChangeSpec(change_type="schema_change", target_uri="urn:start")
    traversal = TraversalSpec(depth=2, direction="out")
    report = _make_report(
        change=change,
        traversal=traversal,
        impacted_uris=["urn:a"],
        counts_by_type={"Product": 1},
        total_impacted=2,
    )

    with pytest.raises(ValueError, match="total_impacted"):
        _validate_report_invariants(report)


def test_validate_report_invariants_rejects_duplicate_impacted_uris():
    change = ChangeSpec(change_type="schema_change", target_uri="urn:start")
    traversal = TraversalSpec(depth=2, direction="out")
    report = _make_report(
        change=change,
        traversal=traversal,
        impacted_uris=["urn:a", "urn:a"],
        counts_by_type={"Product": 2},
    )

    with pytest.raises(ValueError, match="duplicates"):
        _validate_report_invariants(report)


def test_validate_report_invariants_rejects_top_impacts_outside_impacted():
    change = ChangeSpec(change_type="schema_change", target_uri="urn:start")
    traversal = TraversalSpec(depth=2, direction="out")
    report = _make_report(
        change=change,
        traversal=traversal,
        impacted_uris=["urn:a"],
        counts_by_type={"Product": 1},
        top_impact_uri="urn:outside",
    )

    with pytest.raises(ValueError, match="top_impacts"):
        _validate_report_invariants(report)


# ------------------------------------
# Wiring test (monkeypatch, no NetworkX)
# ------------------------------------

def test_simulate_change_builds_delta_and_forwards_strict(monkeypatch):
    change = ChangeSpec(change_type="relationship_change", target_uri="urn:start")
    traversal = TraversalSpec(depth=3, direction="both", max_results=50, top_n=5)
    scenario = ScenarioSpec(scenario_id="scenario_x")

    baseline_graph = SimpleNamespace(
        nx_graph="baseline_nx",
        rdf="baseline_rdf",
        object_properties={"p1", "p2"},
    )

    calls: dict[str, object] = {}

    baseline_report = _make_report(
        change=change,
        traversal=traversal,
        impacted_uris=["urn:a", "urn:b"],
        counts_by_type={"Product": 2},
        top_impact_uri="urn:a",
    )
    simulated_report = _make_report(
        change=change,
        traversal=traversal,
        impacted_uris=["urn:b", "urn:c"],
        counts_by_type={"Product": 1, "Metafield": 1},
        top_impact_uri="urn:c",
    )

    def fake_apply_scenario_to_graph(nx_graph, scenario_arg, strict=False):
        calls["apply_args"] = (nx_graph, scenario_arg, strict)
        return SimpleNamespace(nx_graph="scenario_nx")

    def fake_shopify_graph_ctor(*, rdf, nx_graph, object_properties):
        calls["shopify_graph_ctor"] = (rdf, nx_graph, object_properties)
        return SimpleNamespace(kind="scenario_graph")

    def fake_analyze_change(graph, _change, _traversal):
        if graph is baseline_graph:
            return baseline_report
        return simulated_report

    # IMPORTANT: adjust these paths if your module name differs
    monkeypatch.setattr("core.simulate_change.apply_scenario_to_graph", fake_apply_scenario_to_graph)
    monkeypatch.setattr("core.simulate_change.ShopifyGraph", fake_shopify_graph_ctor)
    monkeypatch.setattr("core.simulate_change.analyze_change", fake_analyze_change)

    result = simulate_change(
        baseline_graph,
        scenario,
        change,
        traversal,
        strict=True,
        validate=True,
    )

    assert calls["apply_args"] == ("baseline_nx", scenario, True)
    assert calls["shopify_graph_ctor"] == ("baseline_rdf", "scenario_nx", {"p1", "p2"})
    assert result.delta.newly_impacted == ["urn:c"]
    assert result.delta.no_longer_impacted == ["urn:a"]
    assert result.delta.delta_counts_by_type == {"Metafield": 1, "Product": -1}


# -----------------------------------
# Integration tests (real shopify_graph)
# -----------------------------------

@pytest.fixture
def simulate_change_strict_adapter(monkeypatch):
    def _adapter(graph, scenario, strict=False):
        applied = _real_apply_scenario_to_graph(graph, scenario)
        if strict and (
            applied.skipped_attribute_overrides > 0
            or applied.skipped_edge_adds > 0
            or applied.skipped_edge_removes > 0
        ):
            raise ValueError("Strict scenario mode: one or more scenario operations were skipped")
        return applied

    monkeypatch.setattr("core.simulate_change.apply_scenario_to_graph", _adapter)


def test_simulate_change_smoke_integration(shopify_graph, simulate_change_strict_adapter):
    target = next(iter(shopify_graph.nx_graph.nodes))

    change = ChangeSpec(target_uri=target, change_type="relationship_change")
    traversal = TraversalSpec(depth=2, direction="both")
    scenario = ScenarioSpec(scenario_id="smoke")

    res = simulate_change(shopify_graph, scenario, change, traversal, validate=True)

    assert res.baseline.summary.total_impacted == len(res.baseline.impacted_uris)
    assert res.simulated.summary.total_impacted == len(res.simulated.impacted_uris)
    assert len(set(res.baseline.impacted_uris)) == len(res.baseline.impacted_uris)
    assert len(set(res.simulated.impacted_uris)) == len(res.simulated.impacted_uris)


def test_simulate_change_deterministic_integration(shopify_graph, simulate_change_strict_adapter):
    target = next(iter(shopify_graph.nx_graph.nodes))

    change = ChangeSpec(target_uri=target, change_type="relationship_change")
    traversal = TraversalSpec(depth=2, direction="both")
    scenario = ScenarioSpec(scenario_id="determinism")

    r1 = simulate_change(shopify_graph, scenario, change, traversal)
    r2 = simulate_change(shopify_graph, scenario, change, traversal)

    assert r1.baseline.impacted_uris == r2.baseline.impacted_uris
    assert r1.simulated.impacted_uris == r2.simulated.impacted_uris
    assert r1.delta.newly_impacted == r2.delta.newly_impacted
    assert r1.delta.no_longer_impacted == r2.delta.no_longer_impacted
    assert r1.delta.delta_counts_by_type == r2.delta.delta_counts_by_type


def test_strict_mode_raises_on_missing_node_override_integration(shopify_graph, simulate_change_strict_adapter):
    target = next(iter(shopify_graph.nx_graph.nodes))

    change = ChangeSpec(target_uri=target, change_type="entity_state_change")
    traversal = TraversalSpec(depth=1, direction="both")
    scenario = ScenarioSpec(
        scenario_id="strict_missing_node",
        attribute_overrides=[
            AttributeOverride(op="set", node_uri="https://example.com/does-not-exist", key="status", value="outage")
        ],
    )

    with pytest.raises(ValueError):
        simulate_change(shopify_graph, scenario, change, traversal, strict=True)
