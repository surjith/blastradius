from __future__ import annotations

import json
from pathlib import Path

import typer

from core.shopify_graph import ShopifyGraph
from core.models import (
    Direction,
    ChangeSpec,
    ChangeType,
    TraversalSpec,
    ScenarioSpec,
)
from core.impact import blast_radius_paths
from core.impact_analysis import analyze_change
from core.simulate_change import simulate_change

app = typer.Typer(no_args_is_help=True)

DEFAULT_ONTO = Path("data/shopify_ontology.ttl")
DEFAULT_INST = Path("data/synthetic_instances.ttl")


def _load_scenario(path: Path) -> ScenarioSpec:
    if not path.exists():
        raise typer.BadParameter(f"scenario-json file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"Invalid JSON in {path}: {e}") from e

    # Pydantic v2
    if hasattr(ScenarioSpec, "model_validate"):
        return ScenarioSpec.model_validate(raw)

    # Pydantic v1 fallback (not expected here, but safe)
    return ScenarioSpec.parse_obj(raw)


def _print_counts(title: str, counts: dict[str, int]) -> None:
    typer.echo(title)
    for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        typer.echo(f"  {t}: {c}")


@app.command()
def blast(
    start: str = typer.Option(..., help="Start node URI"),
    depth: int = typer.Option(3, help="Max hop depth"),
    direction: Direction = typer.Option("out", help="Traversal direction: out|in|both"),
    max_results: int = typer.Option(200, help="Safety limit for traversal expansion"),
    ontology: Path = typer.Option(DEFAULT_ONTO, exists=True),
    instances: Path = typer.Option(DEFAULT_INST, exists=True),
    as_json: bool = typer.Option(False, help="Print traversal result as JSON"),
):
    sg = ShopifyGraph.from_ttl(ontology, instances)
    traversal = TraversalSpec(depth=depth, direction=direction, max_results=max_results)

    res = blast_radius_paths(sg.nx_graph, start=start, traversal=traversal)

    if as_json:
        typer.echo(res.model_dump_json(indent=2))
        raise typer.Exit()

    typer.echo(f"\nBlast Radius Results for node: {res.start}")
    typer.echo(f"Depth: {res.depth}, Direction: {res.direction}")
    typer.echo(f"Reached nodes ({len(res.reached)}):")

    # Show one primary path per reached node
    for node in res.reached:
        path = res.paths[node][0]
        typer.echo(f"- {node}")
        typer.echo(f"  Path: {' -> '.join(path)}")


@app.command()
def impact(
    change_type: ChangeType = typer.Option(..., help="Change category"),
    target: str = typer.Option(..., help="Target node URI"),
    depth: int = typer.Option(4, help="Max hop depth"),
    direction: Direction = typer.Option("both", help="Traversal direction: out|in|both"),
    max_results: int = typer.Option(200, help="Safety limit for traversal expansion"),
    top_n: int = typer.Option(10, help="How many top impacts to show"),
    ontology: Path = typer.Option(DEFAULT_ONTO, exists=True),
    instances: Path = typer.Option(DEFAULT_INST, exists=True),
    # For attribute/state changes
    attribute_name: str = typer.Option(None, help="Attribute name (e.g., status, price)"),
    old_value: str = typer.Option(None, help="Old value"),
    new_value: str = typer.Option(None, help="New value"),
    # For relationship changes (reserved for later)
    relation: str = typer.Option(None, help="Predicate local name (e.g., hasVariant)"),
    related_uri: str = typer.Option(None, help="Other endpoint URI"),
    operation: str = typer.Option(None, help="add/remove"),
    as_json: bool = typer.Option(False, help="Print impact report as JSON"),
):
    sg = ShopifyGraph.from_ttl(ontology, instances)

    change = ChangeSpec(
        change_type=change_type,
        target_uri=target,
        attribute_name=attribute_name,
        old_value=old_value,
        new_value=new_value,
        relation=relation,
        related_uri=related_uri,
        operation=operation,  # type: ignore[arg-type]
    )

    traversal = TraversalSpec(
        depth=depth,
        direction=direction,
        max_results=max_results,
        top_n=top_n,
    )

    report = analyze_change(sg, change, traversal)

    if as_json:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit()

    typer.echo("\n=== IMPACT REPORT ===")
    typer.echo(f"Change Type: {report.change.change_type}")
    typer.echo(f"Target: {report.change.target_uri}")

    if report.change.attribute_name:
        typer.echo(
            f"Attribute: {report.change.attribute_name} "
            f"{report.change.old_value} -> {report.change.new_value}"
        )
    if report.change.relation:
        typer.echo(
            f"Relation: {report.change.operation} "
            f"{report.change.relation} {report.change.related_uri}"
        )

    typer.echo(f"\nTotal impacted: {report.summary.total_impacted}")

    _print_counts("\nCounts by type:", report.summary.counts_by_type)

    typer.echo("\nTop impacts:")
    for item in report.top_impacts:
        typer.echo(f"- {item.uri}")
        typer.echo(f"  Type: {item.entity_type} | Severity: {item.severity}")
        typer.echo(f"  Evidence: {' -> '.join(item.primary_path)}\n")


@app.command()
def simulate(
    change_type: ChangeType = typer.Option(..., help="Change category"),
    start: str = typer.Option(..., "--start", help="Start/target node URI"),
    depth: int = typer.Option(4, help="Max hop depth"),
    direction: Direction = typer.Option("both", help="Traversal direction: out|in|both"),
    max_results: int = typer.Option(200, help="Safety limit for traversal expansion"),
    top_n: int = typer.Option(10, help="How many top impacts to show"),
    scenario_json: Path = typer.Option(..., "--scenario-json", help="ScenarioSpec JSON file"),
    strict: bool = typer.Option(False, help="Strict scenario application mode"),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate report invariants"),
    ontology: Path = typer.Option(DEFAULT_ONTO, exists=True),
    instances: Path = typer.Option(DEFAULT_INST, exists=True),
    # For attribute/state changes
    attribute_name: str = typer.Option(None, help="Attribute name (e.g., status, price)"),
    old_value: str = typer.Option(None, help="Old value"),
    new_value: str = typer.Option(None, help="New value"),
    # For relationship changes (reserved for later)
    relation: str = typer.Option(None, help="Predicate local name (e.g., hasVariant)"),
    related_uri: str = typer.Option(None, help="Other endpoint URI"),
    operation: str = typer.Option(None, help="add/remove"),
    as_json: bool = typer.Option(False, help="Print ScenarioResult as JSON"),
):
    """
    Run baseline vs simulated impact and compute deltas.
    """
    sg = ShopifyGraph.from_ttl(ontology, instances)

    change = ChangeSpec(
        change_type=change_type,
        target_uri=start,
        attribute_name=attribute_name,
        old_value=old_value,
        new_value=new_value,
        relation=relation,
        related_uri=related_uri,
        operation=operation,  # type: ignore[arg-type]
    )

    traversal = TraversalSpec(
        depth=depth,
        direction=direction,
        max_results=max_results,
        top_n=top_n,
    )

    scenario = _load_scenario(scenario_json)

    result = simulate_change(
        baseline_graph=sg,
        scenario=scenario,
        change=change,
        traversal=traversal,
        strict=strict,
        validate=validate,
    )

    if as_json:
        typer.echo(result.model_dump_json(indent=2))
        raise typer.Exit()

    typer.echo("\n=== SCENARIO SIMULATION RESULT ===")
    typer.echo(f"Scenario: {result.scenario.scenario_id}")
    if getattr(result.scenario, "description", None):
        typer.echo(f"Description: {result.scenario.description}")

    typer.echo("\n--- BASELINE ---")
    typer.echo(f"Total impacted: {result.baseline.summary.total_impacted}")
    _print_counts("Counts by type:", result.baseline.summary.counts_by_type)

    typer.echo("\n--- SIMULATED ---")
    typer.echo(f"Total impacted: {result.simulated.summary.total_impacted}")
    _print_counts("Counts by type:", result.simulated.summary.counts_by_type)

    typer.echo("\n--- DELTA ---")
    typer.echo(f"Newly impacted: {len(result.delta.newly_impacted)}")
    typer.echo(f"No longer impacted: {len(result.delta.removed_impacts)}")
    _print_counts("Delta counts by type:", result.delta.delta_counts_by_type)

    if result.delta.newly_impacted:
        typer.echo("\nNewly impacted URIs:")
        for u in result.delta.newly_impacted[:50]:
            typer.echo(f"- {u}")
        if len(result.delta.newly_impacted) > 50:
            typer.echo(f"... ({len(result.delta.newly_impacted) - 50} more)")

    if result.delta.removed_impacts:
        typer.echo("\nRemoved impacts URIs:")
        for u in result.delta.removed_impacts[:50]:
            typer.echo(f"- {u}")
        if len(result.delta.removed_impacts) > 50:
            typer.echo(f"... ({len(result.delta.removed_impacts) - 50} more)")


if __name__ == "__main__":
    app()
