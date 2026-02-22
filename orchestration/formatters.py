from __future__ import annotations

from typing import TYPE_CHECKING

from core.models import BlastRadiusResults, ImpactReport, ScenarioResult
from core.nx_builder import local_name

if TYPE_CHECKING:
    from core.shopify_graph import ShopifyGraph


# ---------------------------------------------------------------------------
# Helpers — URI resolution and grouping (only when graph is available)
# ---------------------------------------------------------------------------

_TYPE_ORDER = [
    "Customer", "Order", "Fulfillment", "Location",
    "Product", "ProductVariant", "InventoryItem",
    "LineItem", "Metafield", "Metaobject",
]


def _label(uri: str, graph: "ShopifyGraph | None") -> str:
    """Best display name for a URI; falls back to the local fragment."""
    if graph is not None:
        data = graph.get_node_data(uri)
        name = data.get("name") or data.get("sku") or data.get("gid")
        if name:
            return str(name)
    return uri


def _type_of(uri: str, graph: "ShopifyGraph | None") -> str:
    if graph is None:
        return "Unknown"
    types = graph.get_node_types(uri)
    return types[0] if types else "Unknown"


def _path_label(path: list[str], graph: "ShopifyGraph | None") -> str:
    return " -> ".join(_label(u, graph) for u in path)


def _grouped_section(
    uris: list[str],
    graph: "ShopifyGraph",
    *,
    max_per_type: int = 20,
) -> list[str]:
    """Return lines grouping URIs by entity type with display names."""
    groups: dict[str, list[tuple[str, str]]] = {}  # type -> [(label, uri)]
    for uri in uris:
        t = _type_of(uri, graph)
        groups.setdefault(t, []).append((_label(uri, graph), uri))

    ordered = {k: groups[k] for k in _TYPE_ORDER if k in groups}
    ordered.update({k: v for k, v in groups.items() if k not in ordered})

    lines: list[str] = []
    for t, items in ordered.items():
        noun = t + ("s" if not t.endswith("s") else "")
        lines.append(f"{noun} ({len(items)})")
        for label, uri in items[:max_per_type]:
            status = graph.get_node_data(uri).get("status", "")
            suffix = f"  [{status}]" if status else ""
            lines.append(f"  - {label}{suffix}")
        if len(items) > max_per_type:
            lines.append(f"  ... ({len(items) - max_per_type} more)")
    return lines


def _removed_list(delta) -> list[str]:
    if hasattr(delta, "removed_impacts"):
        return list(delta.removed_impacts)
    if hasattr(delta, "no_longer_impacted"):
        return list(delta.no_longer_impacted)
    return []


# ---------------------------------------------------------------------------
# Public formatters — graph=None keeps the original compact format (tests).
# graph=ShopifyGraph produces human-readable grouped output.
# ---------------------------------------------------------------------------

def format_blast(
    res: BlastRadiusResults,
    *,
    max_nodes: int = 25,
    graph: "ShopifyGraph | None" = None,
) -> str:
    if graph is None:
        # Backward-compatible compact format (used by tests / CLI)
        lines = [
            f"BLAST start={res.start} depth={res.depth} dir={res.direction}",
            f"Reached={len(res.reached)}",
        ]
        for n in res.reached[:max_nodes]:
            p = res.paths.get(n, [[]])[0]
            lines.append(f"- {n}")
            if p:
                lines.append(f"  path: {' -> '.join(p)}")
        if len(res.reached) > max_nodes:
            lines.append(f"... ({len(res.reached) - max_nodes} more)")
        return "\n".join(lines)

    # Rich human-readable output
    start_label = _label(res.start, graph)
    lines = [
        f"Blast radius of {start_label} - {len(res.reached)} node(s) reached "
        f"(depth {res.depth}, {res.direction} direction)",
    ]

    if not res.reached:
        lines.append("No downstream nodes found.")
        return "\n".join(lines)

    lines.append("")
    lines.extend(_grouped_section(res.reached, graph, max_per_type=max_nodes))

    # Show the path only for the first top-5 nodes (keep it scannable)
    notable = res.reached[:5]
    if notable:
        lines.append("")
        lines.append("Example propagation paths:")
        for n in notable:
            p = res.paths.get(n, [[]])[0]
            if len(p) > 1:
                lines.append(f"  {_path_label(p, graph)}")

    return "\n".join(lines)


def format_impact(
    rep: ImpactReport,
    *,
    graph: "ShopifyGraph | None" = None,
) -> str:
    if graph is None:
        # Backward-compatible compact format
        lines = [
            f"IMPACT change_type={rep.change.change_type} target={rep.change.target_uri}",
            f"Total impacted={rep.summary.total_impacted}",
            "Counts by type:",
        ]
        for k, v in sorted(rep.summary.counts_by_type.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {k}: {v}")
        lines.append("Top impacts:")
        for item in rep.top_impacts:
            lines.append(f"- sev={item.severity} type={item.entity_type}")
            lines.append(f"  uri: {item.uri}")
            lines.append(f"  path: {' -> '.join(item.primary_path)}")
        return "\n".join(lines)

    # Rich human-readable output
    target_label = _label(rep.change.target_uri, graph)
    lines = [
        f"Impact of {rep.change.change_type.replace('_', ' ')} on {target_label} "
        f"- {rep.summary.total_impacted} node(s) affected",
    ]

    if rep.summary.total_impacted == 0:
        lines.append("No downstream nodes affected.")
        return "\n".join(lines)

    lines.append("")
    lines.extend(_grouped_section(rep.impacted_uris, graph))

    if rep.top_impacts:
        lines.append("")
        lines.append("Top impacts by severity:")
        for i, item in enumerate(rep.top_impacts, 1):
            item_label = _label(item.uri, graph)
            path_str = _path_label(item.primary_path, graph)
            lines.append(f"  {i}. {item_label} ({item.entity_type}, severity {item.severity})")
            lines.append(f"     {path_str}")

    return "\n".join(lines)


def format_simulation(
    res: ScenarioResult,
    *,
    max_list: int = 25,
    graph: "ShopifyGraph | None" = None,
) -> str:
    removed = _removed_list(res.delta)

    if graph is None:
        # Backward-compatible compact format
        lines = [f"SIMULATE scenario={res.scenario.scenario_id}"]
        if res.scenario.description:
            lines.append(f"Description: {res.scenario.description}")
        lines.append(f"Baseline impacted={res.baseline.summary.total_impacted}")
        lines.append(f"Simulated impacted={res.simulated.summary.total_impacted}")
        lines.append("Delta counts by type:")
        for k, v in sorted(res.delta.delta_counts_by_type.items(), key=lambda kv: (-abs(kv[1]), kv[0])):
            lines.append(f"  {k}: {v}")
        lines.append(f"Newly impacted={len(res.delta.newly_impacted)}")
        lines.append(f"Removed impacts={len(removed)}")
        if res.delta.newly_impacted:
            lines.append("Newly impacted URIs:")
            for u in res.delta.newly_impacted[:max_list]:
                lines.append(f"- {u}")
            if len(res.delta.newly_impacted) > max_list:
                lines.append(f"... ({len(res.delta.newly_impacted) - max_list} more)")
        if removed:
            lines.append("Removed impacts URIs:")
            for u in removed[:max_list]:
                lines.append(f"- {u}")
            if len(removed) > max_list:
                lines.append(f"... ({len(removed) - max_list} more)")
        lines.append("\nTOP IMPACTS (BASELINE):")
        for i in res.baseline.top_impacts:
            lines.append(f"- sev={i.severity} type={i.entity_type} uri={i.uri}")
        lines.append("TOP IMPACTS (SIMULATED):")
        for i in res.simulated.top_impacts:
            lines.append(f"- sev={i.severity} type={i.entity_type} uri={i.uri}")
        return "\n".join(lines)

    # Rich human-readable output
    b_count = res.baseline.summary.total_impacted
    s_count = res.simulated.summary.total_impacted
    newly = res.delta.newly_impacted
    net_delta = s_count - b_count

    lines = [f"Scenario: {res.scenario.scenario_id}"]
    if res.scenario.description:
        lines.append(res.scenario.description)
    lines.append("")

    # One clear sentence describing what the scenario changed
    if net_delta == 0 and not newly and not removed:
        lines.append(
            f"The scenario does not change the impact set — "
            f"the same {b_count} node(s) are affected before and after."
        )
    elif net_delta == 0:
        lines.append(
            f"Total affected is unchanged ({b_count}), but the composition shifts: "
            f"{len(newly)} newly exposed, {len(removed)} no longer affected."
        )
    elif net_delta > 0:
        lines.append(
            f"Impact grows: {b_count} node(s) affected before the scenario, "
            f"{s_count} after (+{net_delta})."
        )
    else:
        lines.append(
            f"Impact shrinks: {b_count} node(s) affected before the scenario, "
            f"{s_count} after ({net_delta})."
        )

    if newly:
        lines.append("")
        lines.append(f"Newly exposed ({len(newly)}):")
        for line in _grouped_section(newly, graph, max_per_type=max_list):
            lines.append("  " + line)

    if removed:
        lines.append("")
        lines.append(f"No longer affected ({len(removed)}):")
        for line in _grouped_section(removed, graph, max_per_type=max_list):
            lines.append("  " + line)

    if res.simulated.top_impacts:
        lines.append("")
        lines.append(f"Top impacts in simulated graph ({s_count} total affected):")
        for i, item in enumerate(res.simulated.top_impacts, 1):
            item_label = _label(item.uri, graph)
            lines.append(f"  {i}. {item_label} ({item.entity_type}, severity {item.severity})")

    return "\n".join(lines)