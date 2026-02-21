from __future__ import annotations

from typing import Hashable, List, Optional, Tuple

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
) -> Hashable | None:
    bundle = _edge_bundle(scenario_graph, mutation.src_uri, mutation.dst_uri)

    # Deterministic ordering even if keys are int/str mixed
    for key in sorted(bundle.keys(), key=lambda k: str(k)):
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

    MultiDiGraph-safe + deterministic:
    - ADD: skips if an identical edge (relation + predicate_uri) already exists
    - REMOVE: removes *all* matching edges (relation + predicate_uri if provided)
    """
    # Helper: match edge data
    def _matches(data: dict) -> bool:
        if data.get("relation") != mutation.relation:
            return False
        if mutation.predicate_uri is not None and data.get("predicate_uri") != mutation.predicate_uri:
            return False
        return True

    if mutation.op == "add":
        _ensure_node_exists(scenario_graph, mutation.src_uri)
        _ensure_node_exists(scenario_graph, mutation.dst_uri)

        # Skip if identical edge already exists (any key, including int keys from baseline)
        bundle = _edge_bundle(scenario_graph, mutation.src_uri, mutation.dst_uri)
        for k in sorted(bundle.keys(), key=lambda x: str(x)):
            data = bundle[k] or {}
            if _matches(data):
                return (0, 0, "edge add skipped: identical edge already exists")

        # Deterministic key generation (string keys for scenario-added edges)
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

    # REMOVE: delete all matching edges between src->dst (handles multi-edges properly)
    bundle = _edge_bundle(scenario_graph, mutation.src_uri, mutation.dst_uri)
    if not bundle:
        return (0, 0, "edge remove skipped: edge does not exist")

    keys_to_remove = [
        k for k in sorted(bundle.keys(), key=lambda x: str(x))
        if _matches(bundle[k] or {})
    ]

    if not keys_to_remove:
        return (
            0,
            0,
            "edge remove skipped: no matching edge for "
            f'"{mutation.src_uri}" -> "{mutation.dst_uri}" '
            f'with relation="{mutation.relation}"',
        )

    for k in keys_to_remove:
        scenario_graph.remove_edge(mutation.src_uri, mutation.dst_uri, key=k)

    return (0, len(keys_to_remove), None)


def apply_scenario_to_graph(
    baseline_graph: nx.MultiDiGraph,
    scenario: ScenarioSpec,
    *,
    strict: bool = False,
) -> ScenarioApplied:
    """
    Apply ScenarioSpec to a baseline NetworkX graph.

    Day 3 POC strategy:
    - Copy baseline graph
    - Apply attribute overrides
    - Apply edge mutations
    - Return simulated graph + audit counters

    strict:
      - If True, raise if any scenario operation is skipped (missing node, no-op, missing edge, etc.)
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

    applied = ScenarioApplied(
        nx_graph=scenario_graph,
        applied_attribute_overrides=applied_attribute_overrides,
        skipped_attribute_overrides=skipped_attribute_overrides,
        applied_edge_adds=applied_edge_adds,
        skipped_edge_adds=skipped_edge_adds,
        applied_edge_removes=applied_edge_removes,
        skipped_edge_removes=skipped_edge_removes,
        audit_log=audit_log,
    )

    if strict and (
        applied.skipped_attribute_overrides > 0
        or applied.skipped_edge_adds > 0
        or applied.skipped_edge_removes > 0
    ):
        raise ValueError("Strict scenario mode: one or more scenario operations were skipped")

    return applied

def _remove_matching_edges(
    G: nx.MultiDiGraph,
    src: str,
    dst: str,
    relation: str,
    predicate_uri: str | None = None,
) -> int:
    edge_data = G.get_edge_data(src, dst) or {}
    if not edge_data:
        return 0

    to_remove: list[Hashable] = []
    for k, d in edge_data.items():
        if d.get("relation") != relation:
            continue
        if predicate_uri is not None and d.get("predicate_uri") != predicate_uri:
            continue
        to_remove.append(k)

    for k in to_remove:
        G.remove_edge(src, dst, key=k)

    return len(to_remove)
