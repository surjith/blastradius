from __future__ import annotations

from typing import Dict, Mapping, Set

from core.models import (
    ChangeSpec,
    TraversalSpec,
    ScenarioSpec,
    ScenarioResult,
    ScenarioDeltaSummary,
    ImpactReport,
)
from core.impact_analysis import analyze_change
from core.scenario import apply_scenario_to_graph
from core.shopify_graph import ShopifyGraph


def _impacted_set(report: ImpactReport) -> Set[str]:
    return set(report.impacted_uris)


def _diff_counts_by_type(baseline: Mapping[str, int], simulated: Mapping[str, int]) -> Dict[str, int]:
    all_types = sorted(set(baseline.keys()) | set(simulated.keys()))
    return {t: simulated.get(t, 0) - baseline.get(t, 0) for t in all_types}


def _validate_report_invariants(report: ImpactReport) -> None:
    impacted = report.impacted_uris
    impacted_set = set(impacted)

    if report.summary.total_impacted != len(impacted):
        raise ValueError(
            "ImpactReport invariant violated: "
            f"total_impacted={report.summary.total_impacted} "
            f"but impacted_uris={len(impacted)}"
        )

    if len(impacted_set) != len(impacted):
        raise ValueError("ImpactReport invariant violated: impacted_uris contains duplicates")

    top_uris = {item.uri for item in report.top_impacts}
    if not top_uris.issubset(impacted_set):
        raise ValueError("ImpactReport invariant violated: top_impacts contains URIs not in impacted_uris")


def simulate_change(
    baseline_graph: ShopifyGraph,
    scenario: ScenarioSpec,
    change: ChangeSpec,
    traversal: TraversalSpec,
    *,
    strict: bool = False,
    validate: bool = True,
) -> ScenarioResult:
    baseline_report = analyze_change(baseline_graph, change, traversal)

    scenario_applied = apply_scenario_to_graph(
        baseline_graph.nx_graph,
        scenario,
        strict=strict,
    )

    scenario_graph = ShopifyGraph(
        rdf=baseline_graph.rdf,
        nx_graph=scenario_applied.nx_graph,
        object_properties=baseline_graph.object_properties,
    )

    simulated_report = analyze_change(scenario_graph, change, traversal)

    if validate:
        _validate_report_invariants(baseline_report)
        _validate_report_invariants(simulated_report)

    baseline_set = _impacted_set(baseline_report)
    simulated_set = _impacted_set(simulated_report)

    newly_impacted = sorted(simulated_set - baseline_set)
    removed_impacts = sorted(baseline_set - simulated_set)

    delta_counts = _diff_counts_by_type(
        baseline_report.summary.counts_by_type,
        simulated_report.summary.counts_by_type,
    )

    delta_summary = ScenarioDeltaSummary(
        total_impacted_baseline=baseline_report.summary.total_impacted,
        total_impacted_simulated=simulated_report.summary.total_impacted,
        delta_counts_by_type=delta_counts,
        newly_impacted=newly_impacted,
        removed_impacts=removed_impacts,
    )

    return ScenarioResult(
        scenario=scenario,
        change=change,
        traversal=traversal,
        baseline=baseline_report,
        simulated=simulated_report,
        delta=delta_summary,
    )
