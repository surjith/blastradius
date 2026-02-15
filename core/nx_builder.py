from __future__ import annotations
from typing import Set

import networkx as nx
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, OWL

from core.models import NXBuildResults


def local_name(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1]


def extract_object_properties(rdf: Graph) -> Set[str]:
    return set(str(p) for p in rdf.subjects(RDF.type, OWL.ObjectProperty))


def rdf_to_networkx(rdf: Graph) -> NXBuildResults:
    obj_props = extract_object_properties(rdf)
    G = nx.DiGraph()

    # Nodes + literal attributes
    for s in set(rdf.subjects()):
        if not isinstance(s, URIRef):
            continue
        s_str = str(s)
        G.add_node(s_str, uri=s_str)

        for p, o in rdf.predicate_objects(s):
            if isinstance(o, Literal):
                p_uri = str(p)
                G.nodes[s_str][local_name(p_uri)] = str(o)

    # Edges: only semantic object properties
    for s, p, o in rdf:
        if not (isinstance(s, URIRef) and isinstance(o, URIRef)):
            continue
        p_uri = str(p)
        if p_uri not in obj_props:
            continue

        G.add_edge(
            str(s),
            str(o),
            predicate_uri=p_uri,
            relation=local_name(p_uri),
        )

    return NXBuildResults(nx_graph=G, object_properties=sorted(obj_props))
