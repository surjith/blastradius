from __future__ import annotations

from typing import Any, Set

import networkx as nx
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, OWL

from core.models import NXBuildResults


def local_name(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1]


def extract_object_properties(rdf_graph: Graph) -> Set[str]:
    return set(str(p) for p in rdf_graph.subjects(RDF.type, OWL.ObjectProperty))


def _ensure_node(G: nx.MultiDiGraph, node_uri: str) -> None:
    if node_uri not in G:
        G.add_node(node_uri, uri=node_uri)
    elif "uri" not in G.nodes[node_uri]:
        G.nodes[node_uri]["uri"] = node_uri


def _add_literal_attr(G: nx.MultiDiGraph, subject_uri: str, key: str, value: str) -> None:
    """
    Preserve multi-valued literal predicates deterministically:
    - first value stored as string
    - subsequent distinct values stored as list
    """
    existing: Any = G.nodes[subject_uri].get(key)

    if existing is None:
        G.nodes[subject_uri][key] = value
        return

    if isinstance(existing, list):
        if value not in existing:
            existing.append(value)
        return

    # existing is scalar -> convert to list if different
    if existing != value:
        G.nodes[subject_uri][key] = [existing, value]


def rdf_to_networkx(rdf_graph: Graph) -> NXBuildResults:
    object_property_uris = extract_object_properties(rdf_graph)
    nx_graph = nx.MultiDiGraph()

    # ---- Nodes + literal attributes (unique + deterministic subject order) ----
    subjects = sorted(
        {subject for subject in rdf_graph.subjects() if isinstance(subject, URIRef)},
        key=lambda s: str(s),
    )
    for subject in subjects:

        subject_uri = str(subject)
        _ensure_node(nx_graph, subject_uri)

        for predicate, obj in rdf_graph.predicate_objects(subject):
            if not isinstance(obj, Literal):
                continue

            predicate_uri = str(predicate)
            attr_name = local_name(predicate_uri)
            _add_literal_attr(nx_graph, subject_uri, attr_name, str(obj))

    # ---- Edges: only OWL-declared ObjectProperties ----
    for subject, predicate, obj in rdf_graph:
        if not (isinstance(subject, URIRef) and isinstance(obj, URIRef)):
            continue

        predicate_uri = str(predicate)
        if predicate_uri not in object_property_uris:
            continue

        subject_uri = str(subject)
        object_uri = str(obj)

        _ensure_node(nx_graph, subject_uri)
        _ensure_node(nx_graph, object_uri)

        nx_graph.add_edge(
            subject_uri,
            object_uri,
            relation=local_name(predicate_uri),
            predicate_uri=predicate_uri,
        )

    return NXBuildResults(nx_graph=nx_graph, object_properties=sorted(object_property_uris))
