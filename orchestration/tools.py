from __future__ import annotations

from core.impact import blast_radius_paths
from core.impact_analysis import analyze_change
from core.models import (
    BlastRadiusResults,
    ChangeSpec,
    ImpactReport,
    ScenarioResult,
    ScenarioSpec,
    TraversalSpec,
)
from core.shopify_graph import ShopifyGraph
from core.simulate_change import simulate_change


def tool_blast(graph: ShopifyGraph, start_uri: str, traversal: TraversalSpec) -> BlastRadiusResults:
    return blast_radius_paths(graph.nx_graph, start=start_uri, traversalSpec=traversal)


def tool_impact(graph: ShopifyGraph, change: ChangeSpec, traversal: TraversalSpec) -> ImpactReport:
    return analyze_change(graph, change, traversal)


def tool_simulate(
    graph: ShopifyGraph,
    scenario: ScenarioSpec,
    change: ChangeSpec,
    traversal: TraversalSpec,
    *,
    strict: bool,
    validate: bool,
) -> ScenarioResult:
    return simulate_change(
        baseline_graph=graph,
        scenario=scenario,
        change=change,
        traversal=traversal,
        strict=strict,
        validate=validate,
    )