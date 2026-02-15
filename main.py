from pathlib import Path
import typer

from core.shopify_graph import ShopifyGraph
from core.impact import blast_radius_paths
from core.models import Direction

app = typer.Typer(no_args_is_help=True)

DEFAULT_ONTO = Path("data/shopify_ontology.ttl")
DEFAULT_INST = Path("data/synthetic_instances.ttl")

@app.command()
def blast(
    start: str = typer.Option(..., help="URI of the node to start the blast radius analysis from"),
    depth: int = typer.Option(3, help="Maximum depth to explore in the graph"),
    direction: Direction = typer.Option("out", help="Direction to explore: 'out', 'in', or 'both'"),
    ontology: Path = typer.Option(DEFAULT_ONTO, exists=True, help="Path to the RDF ontology TTL file"),
    instances: Path = typer.Option(DEFAULT_INST, exists=True, help="Path to the RDF instances TTL file"),
    as_json: bool = typer.Option(False, help="Output results as JSON instead of plain text"),
):
    """Perform blast radius analysis on the Shopify graph."""
    graph = ShopifyGraph.from_ttl(ontology, instances)
    results = blast_radius_paths(graph.G, start, depth, direction)

    if as_json:
        typer.echo(results.model_dump_json(indent=2))        
    else:
        print(f"Blast Radius Results for node: {start}")
        print(f"Depth: {depth}, Direction: {direction}")
        print(f"Reached nodes ({len(results.reached)}):")
        for node in results.reached:
            types = graph.get_node_types(node)
            types = types[0] if types else "UnknownType"

            print(f"- {node} (distance: {len(results.paths[node][0]) - 1})")
            print(f"  Path: {' -> '.join(results.paths[node][0])}")

def main():
    print("Hello from blastradius!")


if __name__ == "__main__":
    app()
