import networkx as nx
import pytest

from core.models import ChangeSpec, TraversalSpec
from core.impact import blast_radius_paths
from core.impact_analysis import analyze_change


def _pick_node_with_successors(G: nx.DiGraph) -> str:
    for n in G.nodes():
        if len(list(G.successors(n))) > 0:
            return n
    raise AssertionError("No node with outgoing edges found. Check instance data or object-property filtering.")


def _pick_node_with_predecessors(G: nx.DiGraph) -> str:
    for n in G.nodes():
        if len(list(G.predecessors(n))) > 0:
            return n
    raise AssertionError("No node with incoming edges found. Check instance data or object-property filtering.")


def test_analyze_change_out_direction_basic(shopify_graph, nx_graph):
    target = _pick_node_with_successors(nx_graph)

    change = ChangeSpec(
        change_type="attribute_change",
        target_uri=target,
        attribute_name="price",
        old_value="10",
        new_value="12",
    )
    traversal = TraversalSpec(depth=3, direction="out", max_results=200, top_n=10)

    report = analyze_change(shopify_graph, change, traversal)

    assert report.change.target_uri == target
    assert report.traversal.direction == "out"
    assert report.summary.total_impacted >= 1

    # counts_by_type should sum to total_impacted (given we don't skip reached nodes)
    assert sum(report.summary.counts_by_type.values()) == report.summary.total_impacted

    # top_n respected
    assert len(report.top_impacts) <= traversal.top_n

    # severity bounds and evidence sanity
    for item in report.top_impacts:
        assert 1 <= item.severity <= 5
        assert item.primary_path[0] == target
        assert item.primary_path[-1] == item.uri

        # path should follow directed edges for out traversal
        for i in range(len(item.primary_path) - 1):
            u, v = item.primary_path[i], item.primary_path[i + 1]
            assert nx_graph.has_edge(u, v), f"Missing directed edge in path: {u} -> {v}"


def test_analyze_change_in_direction_basic(shopify_graph, nx_graph):
    target = _pick_node_with_predecessors(nx_graph)

    change = ChangeSpec(
        change_type="entity_state_change",
        target_uri=target,
        attribute_name="status",
        old_value="active",
        new_value="archived",
    )
    traversal = TraversalSpec(depth=3, direction="in", max_results=200, top_n=10)

    report = analyze_change(shopify_graph, change, traversal)

    assert report.change.target_uri == target
    assert report.traversal.direction == "in"
    assert report.summary.total_impacted >= 1
    assert sum(report.summary.counts_by_type.values()) == report.summary.total_impacted

    for item in report.top_impacts:
        assert 1 <= item.severity <= 5
        assert item.primary_path[0] == target
        assert item.primary_path[-1] == item.uri

        # For "in" traversal, each hop corresponds to a reverse edge in the underlying digraph
        for i in range(len(item.primary_path) - 1):
            a, b = item.primary_path[i], item.primary_path[i + 1]
            assert nx_graph.has_edge(b, a), f"Missing reverse edge for 'in' traversal: {b} -> {a}"


def test_analyze_change_matches_blast_reached_count(shopify_graph, nx_graph):
    """
    Ensures ImpactReport total_impacted aligns with the blast radius primitive.
    """
    target = _pick_node_with_successors(nx_graph)

    traversal = TraversalSpec(depth=4, direction="out", max_results=200, top_n=10)
    blast = blast_radius_paths(nx_graph, target, traversal)

    change = ChangeSpec(change_type="schema_change", target_uri=target)
    report = analyze_change(shopify_graph, change, traversal)

    assert report.summary.total_impacted == len(blast.reached)


def test_top_n_limits_output(shopify_graph, nx_graph):
    target = _pick_node_with_successors(nx_graph)

    change = ChangeSpec(change_type="outage", target_uri=target)
    traversal = TraversalSpec(depth=6, direction="out", max_results=200, top_n=3)

    report = analyze_change(shopify_graph, change, traversal)

    assert len(report.top_impacts) <= 3
