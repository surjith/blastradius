import networkx as nx
import pytest

from core.models import TraversalSpec
from core.impact import blast_radius_paths


def _pick_any_edge(G: nx.DiGraph) -> tuple[str, str]:
    for u, v in G.edges():
        return u, v
    raise AssertionError("No edges found in graph. Check instance data + object property filtering.")


def _pick_two_hop_chain(G: nx.DiGraph) -> tuple[str, str, str]:
    for a in G.nodes():
        for b in G.successors(a):
            for c in G.successors(b):
                if c != a:
                    return a, b, c
    raise AssertionError("No 2-hop chain (a->b->c) found. Add at least one multi-hop relationship in instances.")


def _assert_path_valid_directed(G: nx.DiGraph, path: list[str]) -> None:
    assert len(path) >= 2
    for i in range(len(path) - 1):
        assert G.has_edge(path[i], path[i + 1]), f"Missing directed edge: {path[i]} -> {path[i+1]}"


def test_blast_out_reaches_direct_neighbor(nx_graph):
    u, v = _pick_any_edge(nx_graph)

    traversal = TraversalSpec(depth=1, direction="out")
    res = blast_radius_paths(nx_graph, start=u, traversalSpec=traversal)
    assert v in res.reached
    assert v in res.paths

    first_path = res.paths[v][0]
    assert first_path[0] == u
    assert first_path[-1] == v
    _assert_path_valid_directed(nx_graph, first_path)


def test_blast_in_reaches_reverse_neighbor(nx_graph):
    u, v = _pick_any_edge(nx_graph)

    traversal = TraversalSpec(depth=1, direction="in")
    res = blast_radius_paths(nx_graph, start=v, traversalSpec=traversal)
    assert u in res.reached
    assert u in res.paths

    first_path = res.paths[u][0]
    assert first_path[0] == v
    assert first_path[-1] == u
    # For direction="in", the underlying edges are still forward in NX,
    # but your traversal uses predecessors, so the path hops are reversed edges.
    # Therefore we validate using reverse direction:
    for i in range(len(first_path) - 1):
        assert nx_graph.has_edge(first_path[i + 1], first_path[i]), (
            f"Missing reverse edge for 'in' traversal: {first_path[i+1]} -> {first_path[i]}"
        )


def test_blast_two_hop_path(nx_graph):
    a, b, c = _pick_two_hop_chain(nx_graph)

    traversal = TraversalSpec(depth=2, direction="out")
    res = blast_radius_paths(nx_graph, start=a, traversalSpec=traversal)
    assert c in res.reached

    path = res.paths[c][0]
    assert path[0] == a
    assert path[-1] == c
    _assert_path_valid_directed(nx_graph, path)


def test_invalid_start_raises(nx_graph):
    with pytest.raises(ValueError):
        traversal = TraversalSpec(depth=2, direction="out")
        blast_radius_paths(nx_graph, start="urn:does:not:exist", traversalSpec=traversal)
