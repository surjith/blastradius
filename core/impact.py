from __future__ import annotations
from collections import deque
from typing import Dict, Optional, Iterable, Set

import networkx as nx

from core.models import BlastRadiusResults, Direction


def _neighbors(G: nx.DiGraph, node: str, direction: Direction) -> Iterable[str]:
    if direction == "out":
        return G.successors(node)
    if direction == "in":
        return G.predecessors(node)
    # both
    return set(G.successors(node)).union(set(G.predecessors(node)))


def blast_radius_paths(
    G: nx.DiGraph,
    start: str,
    depth: int = 3,
    direction: Direction = "out",
) -> BlastRadiusResults:
    if start not in G:
        raise ValueError(f"Start node not in graph: {start}")

    parent: Dict[str, Optional[str]] = {start: None}
    dist: Dict[str, int] = {start: 0}
    q = deque([start])

    while q:
        u = q.popleft()
        if dist[u] >= depth:
            continue

        for v in _neighbors(G, u, direction):
            if v not in dist:
                dist[v] = dist[u] + 1
                parent[v] = u
                q.append(v)

    def path_to(n: str) -> list[str]:
        path: list[str] = []
        cur: Optional[str] = n
        while cur is not None:
            path.append(cur)
            cur = parent.get(cur)
        return list(reversed(path))

    reached = [n for n in dist.keys() if n != start]
    reached.sort(key=lambda x: dist[x])    
    paths = {n: [path_to(n)] for n in reached}  # ✅ list of paths, each path is a list[str]


    return BlastRadiusResults(
        start=start,
        depth=depth,
        direction=direction,
        reached=reached,
        paths=paths,
    )
