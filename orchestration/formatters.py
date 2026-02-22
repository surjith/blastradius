from __future__ import annotations

from core.models import BlastRadiusResults, ImpactReport, ScenarioResult


def _removed_list(delta) -> list[str]:
    # supports your rename (removed_impacts) or older name (no_longer_impacted)
    if hasattr(delta, "removed_impacts"):
        return list(delta.removed_impacts)
    if hasattr(delta, "no_longer_impacted"):
        return list(delta.no_longer_impacted)
    return []


def format_blast(res: BlastRadiusResults, *, max_nodes: int = 25) -> str:
    lines: list[str] = []
    lines.append(f"BLAST start={res.start} depth={res.depth} dir={res.direction}")
    lines.append(f"Reached={len(res.reached)}")
    for n in res.reached[:max_nodes]:
        p = res.paths.get(n, [[]])[0]
        lines.append(f"- {n}")
        if p:
            lines.append(f"  path: {' -> '.join(p)}")
    if len(res.reached) > max_nodes:
        lines.append(f"... ({len(res.reached) - max_nodes} more)")
    return "\n".join(lines)


def format_impact(rep: ImpactReport) -> str:
    lines: list[str] = []
    lines.append(f"IMPACT change_type={rep.change.change_type} target={rep.change.target_uri}")
    lines.append(f"Total impacted={rep.summary.total_impacted}")
    lines.append("Counts by type:")
    for k, v in sorted(rep.summary.counts_by_type.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {k}: {v}")
    lines.append("Top impacts:")
    for item in rep.top_impacts:
        lines.append(f"- sev={item.severity} type={item.entity_type}")
        lines.append(f"  uri: {item.uri}")
        lines.append(f"  path: {' -> '.join(item.primary_path)}")
    return "\n".join(lines)


def format_simulation(res: ScenarioResult, *, max_list: int = 25) -> str:
    lines: list[str] = []
    lines.append(f"SIMULATE scenario={res.scenario.scenario_id}")
    if res.scenario.description:
        lines.append(f"Description: {res.scenario.description}")

    lines.append(f"Baseline impacted={res.baseline.summary.total_impacted}")
    lines.append(f"Simulated impacted={res.simulated.summary.total_impacted}")

    lines.append("Delta counts by type:")
    for k, v in sorted(res.delta.delta_counts_by_type.items(), key=lambda kv: (-abs(kv[1]), kv[0])):
        lines.append(f"  {k}: {v}")

    removed = _removed_list(res.delta)
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

    # PoC-friendly: show severity visibility without adding severity-delta model yet
    lines.append("\nTOP IMPACTS (BASELINE):")
    for i in res.baseline.top_impacts:
        lines.append(f"- sev={i.severity} type={i.entity_type} uri={i.uri}")
    lines.append("TOP IMPACTS (SIMULATED):")
    for i in res.simulated.top_impacts:
        lines.append(f"- sev={i.severity} type={i.entity_type} uri={i.uri}")

    return "\n".join(lines)