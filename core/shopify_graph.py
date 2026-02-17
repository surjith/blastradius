from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional, Set

import networkx as nx
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from core.rdf_loader import load_rdf_file
from core.nx_builder import rdf_to_networkx, local_name


class ShopifyGraph:
    """Facade over RDFLib Graph + NetworkX execution graph."""

    def __init__(self, rdf: Graph, nx_graph: nx.MultiDiGraph, object_properties: Set[str]):
        self.rdf = rdf
        self.G = nx_graph
        self.object_properties = object_properties

    @classmethod
    def from_ttl(cls, ontology_path: str | Path, instances_path: str | Path) -> "ShopifyGraph":
        rdf = load_rdf_file(ontology_path, instances_path)
        build = rdf_to_networkx(rdf)
        # build.nx_graph is typed as object in the model; cast for clarity
        nx_graph = build.nx_graph  # type: ignore[assignment]
        return cls(rdf=rdf, nx_graph=nx_graph, object_properties=set(build.object_properties))

    # ---- RDF helpers ----
    def get_node_types(self, node_uri: str) -> List[str]:
        types: List[str] = []
        for _, _, o in self.rdf.triples((URIRef(node_uri), RDF.type, None)):
            types.append(local_name(str(o)))
        return types

    # ---- NX helpers ----
    def node_exists(self, node_uri: str) -> bool:
        return node_uri in self.G

    def get_node_data(self, node_uri: str) -> Dict:
        if node_uri not in self.G:
            return {}
        return dict(self.G.nodes[node_uri])

    def successors(self, node_uri: str, relation: Optional[str] = None) -> List[str]:
        if node_uri not in self.G:
            return []
        out: List[str] = []
        for v in self.G.successors(node_uri):
            if relation is None:
                out.append(v)
                continue
            edge_bundle = self.G.get_edge_data(node_uri, v) or {}
            if any(data.get("relation") == relation for data in edge_bundle.values()):
                out.append(v)
        return out

    def predecessors(self, node_uri: str, relation: Optional[str] = None) -> List[str]:
        if node_uri not in self.G:
            return []
        out: List[str] = []
        for u in self.G.predecessors(node_uri):
            if relation is None:
                out.append(u)
                continue
            edge_bundle = self.G.get_edge_data(u, node_uri) or {}
            if any(data.get("relation") == relation for data in edge_bundle.values()):
                out.append(u)
        return out

    def find_by_literal(self, key: str, value: str) -> List[str]:
        """Exact match over node attributes (e.g., name/status)."""
        target = value.strip().lower()
        matches: List[str] = []
        for n, data in self.G.nodes(data=True):
            if str(data.get(key, "")).strip().lower() == target:
                matches.append(n)
        return matches
