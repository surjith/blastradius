from __future__ import annotations
from collections import deque
from typing import Dict, Optional, Iterable

import networkx as nx

from core.models import BlastRadiusResults, Direction, TraversalSpec


def _neighbors(G: nx.MultiDiGraph, node: str, direction: Direction) -> Iterable[str]:
    if direction == "out":
        return sorted(G.successors(node))
    if direction == "in":
        return sorted(G.predecessors(node))
    # both
    return sorted(set(G.successors(node)).union(set(G.predecessors(node))))


def blast_radius_paths(
    G: nx.MultiDiGraph,
    start: str,
    traversalSpec: TraversalSpec
) -> BlastRadiusResults:
    if start not in G:
        raise ValueError(f"Start node not in graph: {start}")

    parent: Dict[str, Optional[str]] = {start: None}
    dist: Dict[str, int] = {start: 0}
    q = deque([start])
    visited_count = 1

    while q:
        u = q.popleft()
        if dist[u] >= traversalSpec.depth:
            continue

        for v in _neighbors(G, u, traversalSpec.direction):
            if v not in dist:
                dist[v] = dist[u] + 1
                parent[v] = u
                q.append(v)
                visited_count += 1

                if visited_count >= traversalSpec.max_results:
                    # Safety cutoff to prevent runaway graphs.
                    q.clear()
                    break

    def path_to(n: str) -> list[str]:
        path: list[str] = []
        cur: Optional[str] = n
        while cur is not None:
            path.append(cur)
            cur = parent.get(cur)
        return list(reversed(path))

    reached = [n for n in dist.keys() if n != start]
    reached.sort(key=lambda x: (dist[x], x))
    paths = {n: [path_to(n)] for n in reached} 


    return BlastRadiusResults(
        start = start,
        depth = traversalSpec.depth,
        direction = traversalSpec.direction,
        reached = reached,
        paths = paths,
    )
