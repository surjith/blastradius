from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping

from core.models import (
    ChangeSpec,
    TraversalSpec,
    ImpactItem,
    ImpactReport,
    ImpactSummary,
)
from core.impact import blast_radius_paths
from core.shopify_graph import ShopifyGraph


# Deterministic base severity by entity type (heuristic)
TYPE_BASE_SEVERITY: Dict[str, int] = {
    "Order": 5,
    "Fulfillment": 4,
    "Location": 4,
    "LineItem": 3,
    "InventoryItem": 3,
    "Customer": 2,
    "ProductVariant": 2,
    "Product": 2,
    "Metafield": 1,
    "Metaobject": 1,
    "Unknown": 1,
}

# Prefer types with higher business impact (derived from severity)
PREFERRED_TYPES: List[str] = [
    t for t, _ in sorted(TYPE_BASE_SEVERITY.items(), key=lambda kv: kv[1], reverse=True)
    if t != "Unknown"
]


def classify_entity(graph: ShopifyGraph, uri: str) -> str:
    """
    Classify entity using RDF type(s).
    If multiple types exist, prefer the one with higher business impact.
    """
    types = graph.get_node_types(uri)
    if not types:
        return "Unknown"

    type_set = set(types)
    for t in PREFERRED_TYPES:
        if t in type_set:
            return t

    # fallback: stable choice (sorted)
    return sorted(types)[0]


def compute_severity(
    change: ChangeSpec,
    entity_type: str,
    path_len: int,
    node_data: Mapping[str, Any],
) -> int:
    """
    Deterministic severity scoring.

    Goal: credibility + consistency for demo; not perfect risk quantification.
    """
    score = TYPE_BASE_SEVERITY.get(entity_type, 1)

    # closer dependency chain often implies more immediate impact
    if path_len <= 2:
        score += 1

    # change-type modifier (only apply where it matters)
    if change.change_type == "outage":
        score += 1

    # status-based bump (if present in literals)
    status = str(node_data.get("status", "")).strip().lower()
    if status in {"unfulfilled", "pending", "processing", "outage", "failed"}:
        score += 1

    return max(1, min(score, 5))


def analyze_change(graph: ShopifyGraph, change: ChangeSpec, traversal: TraversalSpec) -> ImpactReport:
    """
    Produce a structured ImpactReport from a ChangeSpec and traversal controls.
    """
    if not graph.node_exists(change.target_uri):
        raise ValueError(f"target_uri not found in graph: {change.target_uri}")

    blast = blast_radius_paths(graph.G, start=change.target_uri, traversal=traversal)

    counts = defaultdict(int)
    items: List[ImpactItem] = []

    for uri in blast.reached:
        paths_for_uri = blast.paths.get(uri)
        if not paths_for_uri:
            # Should not happen for reached nodes; skip rather than fabricate evidence.
            continue

        primary_path = paths_for_uri[0]
        entity_type = classify_entity(graph, uri)
        counts[entity_type] += 1

        node_data = graph.get_node_data(uri)
        severity = compute_severity(
            change=change,
            entity_type=entity_type,
            path_len=len(primary_path),
            node_data=node_data,
        )

        items.append(
            ImpactItem(
                uri=uri,
                entity_type=entity_type,
                severity=severity,
                primary_path=primary_path,
            )
        )

    # Sort: highest severity first, then shortest path (more direct), then stable tie-breakers
    items.sort(key=lambda x: (-x.severity, len(x.primary_path), x.entity_type, x.uri))

    summary = ImpactSummary(
        counts_by_type=dict(counts),
        total_impacted=len(blast.reached),
    )

    return ImpactReport(
        change=change,
        traversal=traversal,
        summary=summary,
        top_impacts=items[: traversal.top_n],
    )
