from __future__ import annotations

from pathlib import Path
import typer

from core.shopify_graph import ShopifyGraph
from core.models import Direction, ChangeSpec, ChangeType, TraversalSpec
from core.impact import blast_radius_paths
from core.impact_analysis import analyze_change

app = typer.Typer(no_args_is_help=True)

DEFAULT_ONTO = Path("data/shopify_ontology.ttl")
DEFAULT_INST = Path("data/synthetic_instances.ttl")


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

    res = blast_radius_paths(sg.G, start=start, traversal=traversal)

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
        typer.echo(f"Attribute: {report.change.attribute_name} {report.change.old_value} -> {report.change.new_value}")
    if report.change.relation:
        typer.echo(f"Relation: {report.change.operation} {report.change.relation} {report.change.related_uri}")

    typer.echo(f"\nTotal impacted: {report.summary.total_impacted}")

    typer.echo("\nCounts by type:")
    for t, c in sorted(report.summary.counts_by_type.items(), key=lambda kv: (-kv[1], kv[0])):
        typer.echo(f"  {t}: {c}")

    typer.echo("\nTop impacts:")
    for item in report.top_impacts:
        typer.echo(f"- {item.uri}")
        typer.echo(f"  Type: {item.entity_type} | Severity: {item.severity}")
        typer.echo(f"  Evidence: {' -> '.join(item.primary_path)}\n")


if __name__ == "__main__":
    app()
