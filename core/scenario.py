from __future__ import annotations

from typing import List, Optional, Tuple

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from core.models import ScenarioSpec, AttributeOverride, EdgeMutation


class ScenarioApplied(BaseModel):
    """
    Result of applying a ScenarioSpec to a baseline NetworkX graph.

    nx_graph is arbitrary (non-Pydantic-native), so arbitrary_types_allowed=True.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    nx_graph: nx.MultiDiGraph
    applied_attribute_overrides: int = 0
    skipped_attribute_overrides: int = 0
    applied_edge_adds: int = 0
    skipped_edge_adds: int = 0
    applied_edge_removes: int = 0
    skipped_edge_removes: int = 0
    audit_log: List[str] = Field(default_factory=list)


def _ensure_node_exists(scenario_graph: nx.MultiDiGraph, node_uri: str) -> None:
    """
    Ensure a node exists in the graph.
    Minimal metadata: store its uri.
    """
    if node_uri not in scenario_graph:
        scenario_graph.add_node(node_uri, uri=node_uri)


def _apply_attribute_override(
    scenario_graph: nx.MultiDiGraph,
    override: AttributeOverride,
) -> Tuple[bool, Optional[str]]:
    """
    Apply a single AttributeOverride.
    Returns (applied, reason_if_skipped).
    """
    if override.node_uri not in scenario_graph:
        return False, f'attribute override skipped: missing node "{override.node_uri}"'

    node_data = scenario_graph.nodes[override.node_uri]

    if override.op == "set":
        if node_data.get(override.key) == override.value:
            return False, (
                f'attribute override skipped: no-op set on "{override.node_uri}" '
                f'for key "{override.key}"'
            )
        node_data[override.key] = override.value
        return True, None

    # unset
    if override.key in node_data:
        del node_data[override.key]
        return True, None

    return False, (
        f'attribute override skipped: key "{override.key}" absent on node "{override.node_uri}"'
    )


def _edge_bundle(
    scenario_graph: nx.MultiDiGraph,
    src_uri: str,
    dst_uri: str,
) -> dict:
    return scenario_graph.get_edge_data(src_uri, dst_uri) or {}


def _find_matching_edge_key(
    scenario_graph: nx.MultiDiGraph,
    mutation: EdgeMutation,
) -> Optional[str]:
    bundle = _edge_bundle(scenario_graph, mutation.src_uri, mutation.dst_uri)
    for key in sorted(bundle.keys()):
        data = bundle[key] or {}
        if data.get("relation") != mutation.relation:
            continue
        if mutation.predicate_uri is not None and data.get("predicate_uri") != mutation.predicate_uri:
            continue
        return key
    return None


def _apply_edge_mutation(
    scenario_graph: nx.MultiDiGraph,
    mutation: EdgeMutation,
    scenario_id: str,
) -> Tuple[int, int, Optional[str]]:
    """
    Apply a single EdgeMutation.
    Returns (adds, removes, reason_if_skipped).
    """
    if mutation.op == "add":
        _ensure_node_exists(scenario_graph, mutation.src_uri)
        _ensure_node_exists(scenario_graph, mutation.dst_uri)
        if _find_matching_edge_key(scenario_graph, mutation) is not None:
            return (0, 0, "edge add skipped: identical edge already exists")

        key_prefix = mutation.predicate_uri or mutation.relation
        key = f"{key_prefix}:{scenario_id}:0"
        suffix = 1
        while scenario_graph.has_edge(mutation.src_uri, mutation.dst_uri, key=key):
            key = f"{key_prefix}:{scenario_id}:{suffix}"
            suffix += 1

        scenario_graph.add_edge(
            mutation.src_uri,
            mutation.dst_uri,
            key=key,
            relation=mutation.relation,
            predicate_uri=mutation.predicate_uri,
            scenario_id=scenario_id,
        )

        return (1, 0, None)

    # remove
    matching_key = _find_matching_edge_key(scenario_graph, mutation)
    if matching_key is None:
        if scenario_graph.has_edge(mutation.src_uri, mutation.dst_uri):
            return (
                0,
                0,
                "edge remove skipped: no matching edge for "
                f'"{mutation.src_uri}" -> "{mutation.dst_uri}" '
                f'with relation="{mutation.relation}"',
            )
        return (0, 0, "edge remove skipped: edge does not exist")
    scenario_graph.remove_edge(mutation.src_uri, mutation.dst_uri, key=matching_key)
    return (0, 1, None)


def apply_scenario_to_graph(
    baseline_graph: nx.MultiDiGraph,
    scenario: ScenarioSpec,
) -> ScenarioApplied:
    """
    Apply ScenarioSpec to a baseline NetworkX graph.

    Day 3 POC strategy:
    - Copy baseline graph
    - Apply attribute overrides
    - Apply edge mutations
    - Return simulated graph + audit counters
    """
    scenario_graph = baseline_graph.copy()

    applied_attribute_overrides = 0
    skipped_attribute_overrides = 0
    applied_edge_adds = 0
    skipped_edge_adds = 0
    applied_edge_removes = 0
    skipped_edge_removes = 0
    audit_log: List[str] = []

    # ---- Apply attribute overrides ----
    for override in scenario.attribute_overrides:
        applied, reason = _apply_attribute_override(scenario_graph, override)
        if applied:
            applied_attribute_overrides += 1
        else:
            skipped_attribute_overrides += 1
            if reason:
                audit_log.append(reason)

    # ---- Apply edge mutations ----
    for mutation in scenario.edge_mutations:
        adds, removes, reason = _apply_edge_mutation(
            scenario_graph,
            mutation,
            scenario.scenario_id,
        )
        applied_edge_adds += adds
        applied_edge_removes += removes
        if mutation.op == "add" and adds == 0:
            skipped_edge_adds += 1
        if mutation.op == "remove" and removes == 0:
            skipped_edge_removes += 1
        if reason:
            audit_log.append(reason)

    return ScenarioApplied(
        nx_graph=scenario_graph,
        applied_attribute_overrides=applied_attribute_overrides,
        skipped_attribute_overrides=skipped_attribute_overrides,
        applied_edge_adds=applied_edge_adds,
        skipped_edge_adds=skipped_edge_adds,
        applied_edge_removes=applied_edge_removes,
        skipped_edge_removes=skipped_edge_removes,
        audit_log=audit_log,
    )
