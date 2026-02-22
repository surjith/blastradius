from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
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
from core.scenario import apply_scenario_to_graph
from core.nx_builder import local_name

# Day 4 (LangGraph orchestration)
from orchestration.interpreters import JsonEnvelopeInterpreter
from orchestration.workflow import build_workflow

app = typer.Typer(no_args_is_help=True)

DEFAULT_ONTO = Path("data/shopify_ontology.ttl")
DEFAULT_INST = Path("data/synthetic_instances.ttl")


def _load_scenario(path: Path) -> ScenarioSpec:
    if not path.exists():
        raise typer.BadParameter(f"scenario-json file not found: {path}")

    try:
        raw = json.loads(_read_file_robust(path))
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"Invalid JSON in {path}: {e}") from e

    # Pydantic v2
    if hasattr(ScenarioSpec, "model_validate"):
        return ScenarioSpec.model_validate(raw)

    # Pydantic v1 fallback (not expected here, but safe)
    return ScenarioSpec.parse_obj(raw)


def _read_file_robust(path: Path) -> str:
    # Try utf-8-sig first (handles BOM and non-BOM UTF-8)
    # Then utf-16 (Windows default)
    # Then cp1252 (Windows legacy)
    for encoding in ["utf-8-sig", "utf-16", "cp1252"]:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode file {path} with common encodings.")


def _print_counts(title: str, counts: dict[str, int]) -> None:
    typer.echo(title)
    for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        typer.echo(f"  {t}: {c}")


def _require_pyvis():
    try:
        from pyvis.network import Network
    except ImportError as e:
        raise typer.BadParameter(
            "pyvis is required for visualize. Install with: uv add pyvis"
        ) from e
    return Network


def _node_label(uri: str) -> str:
    return local_name(uri)


def _node_color(status: str) -> str:
    s = str(status or "").strip().lower()
    if s in {"outage", "failed"}:
        return "#e74c3c"
    if s in {"pending", "processing", "unfulfilled"}:
        return "#f39c12"
    return "#3498db"


def _render_graph_html(
    G: nx.MultiDiGraph,
    out_path: Path,
    title: str,
) -> None:
    Network = _require_pyvis()
    net = Network(height="820px", width="100%", directed=True, notebook=False)
    net.barnes_hut()

    for n, data in G.nodes(data=True):
        label = _node_label(str(n))
        node_type = data.get("type", "")
        status = data.get("status", "")
        tooltip = f"uri: {n}<br>type: {node_type}<br>status: {status}"
        net.add_node(
            str(n),
            label=label,
            title=tooltip,
            color=_node_color(str(status)),
        )

    for u, v, _k, data in G.edges(keys=True, data=True):
        relation = str(data.get("relation", "edge"))
        edge_color = "#e67e22" if data.get("scenario_id") else "#95a5a6"
        net.add_edge(
            str(u),
            str(v),
            label=relation,
            title=str(data.get("predicate_uri", relation)),
            arrows="to",
            color=edge_color,
        )

    net.set_options(
        """
        {
          "edges": { "smooth": false, "font": { "size": 10 } },
          "nodes": { "shape": "dot", "size": 12, "font": { "size": 12 } },
          "physics": { "stabilization": true }
        }
        """
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_path), open_browser=False)


def _write_compare_html(compare_path: Path, baseline_name: str, simulated_name: str) -> None:
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Blast Radius Graph Compare</title>
  <style>
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }}
    .wrap {{ display: flex; gap: 10px; height: 100vh; padding: 10px; box-sizing: border-box; }}
    .panel {{ flex: 1; min-width: 0; display: flex; flex-direction: column; }}
    h3 {{ margin: 0 0 8px 0; font-size: 14px; }}
    iframe {{ flex: 1; border: 1px solid #d0d7de; border-radius: 8px; }}
    @media (max-width: 960px) {{
      .wrap {{ flex-direction: column; height: auto; }}
      iframe {{ min-height: 60vh; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <h3>Baseline</h3>
      <iframe src="{baseline_name}"></iframe>
    </div>
    <div class="panel">
      <h3>Simulated</h3>
      <iframe src="{simulated_name}"></iframe>
    </div>
  </div>
</body>
</html>
"""
    compare_path.write_text(html, encoding="utf-8")


def _focused_subgraph(
    G: nx.MultiDiGraph,
    start: str,
    traversal: TraversalSpec,
) -> nx.MultiDiGraph:
    blast = blast_radius_paths(G, start=start, traversalSpec=traversal)
    nodes = set(blast.reached)
    nodes.add(start)
    return G.subgraph(nodes).copy()


def _print_top_impacts(label: str, report) -> None:
    typer.echo(f"\n--- TOP IMPACTS ({label}) ---")
    for item in report.top_impacts:
        typer.echo(f"- severity={item.severity} | type={item.entity_type}")
        typer.echo(f"  uri: {item.uri}")
        typer.echo(f"  path: {' -> '.join(item.primary_path)}")


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

    res = blast_radius_paths(sg.nx_graph, start=start, traversalSpec=traversal)

    if as_json:
        typer.echo(res.model_dump_json(indent=2))
        raise typer.Exit()

    typer.echo(f"\nBlast Radius Results for node: {res.start}")
    typer.echo(f"Depth: {res.depth}, Direction: {res.direction}")
    typer.echo(f"Reached nodes ({len(res.reached)}):")

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
    attribute_name: str = typer.Option(None, help="Attribute name (e.g., status, price)"),
    old_value: str = typer.Option(None, help="Old value"),
    new_value: str = typer.Option(None, help="New value"),
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
    show_top: bool = typer.Option(
        True, "--show-top/--no-show-top", help="Show top impacts for baseline and simulated"
    ),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate report invariants"),
    ontology: Path = typer.Option(DEFAULT_ONTO, exists=True),
    instances: Path = typer.Option(DEFAULT_INST, exists=True),
    attribute_name: str = typer.Option(None, help="Attribute name (e.g., status, price)"),
    old_value: str = typer.Option(None, help="Old value"),
    new_value: str = typer.Option(None, help="New value"),
    relation: str = typer.Option(None, help="Predicate local name (e.g., hasVariant)"),
    related_uri: str = typer.Option(None, help="Other endpoint URI"),
    operation: str = typer.Option(None, help="add/remove"),
    as_json: bool = typer.Option(False, help="Print ScenarioResult as JSON"),
):
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
    typer.echo(f"Removed impacts: {len(result.delta.removed_impacts)}")
    _print_counts("Delta counts by type:", result.delta.delta_counts_by_type)

    if show_top:
        _print_top_impacts("BASELINE", result.baseline)
        _print_top_impacts("SIMULATED", result.simulated)

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


# -------------------------
# Day 4: LangGraph agent CLI
# -------------------------
@app.command()
def agent(
    message: str = typer.Option(None, "--message", help="JSON envelope as a string"),
    envelope_file: Path = typer.Option(None, "--envelope-file", help="Path to JSON envelope file"),
    ontology: Path = typer.Option(DEFAULT_ONTO, exists=True),
    instances: Path = typer.Option(DEFAULT_INST, exists=True),
):
    """
    Day 4 orchestrator entrypoint (JSON-envelope driven).
    """
    if envelope_file:
        message = _read_file_robust(envelope_file)
        base_dir = str(envelope_file.parent)
    else:
        base_dir = str(Path("."))

    if not message:
        raise typer.BadParameter("Provide --message or --envelope-file")

    sg = ShopifyGraph.from_ttl(ontology, instances)
    wf = build_workflow(graph=sg, interpreter=JsonEnvelopeInterpreter())

    out = wf.invoke({"user_input": message, "base_dir": base_dir})
    typer.echo(out.get("response", ""))


@app.command()
def visualize(
    scenario_json: Path = typer.Option(..., "--scenario-json", help="ScenarioSpec JSON file"),
    ontology: Path = typer.Option(DEFAULT_ONTO, exists=True),
    instances: Path = typer.Option(DEFAULT_INST, exists=True),
    out_dir: Path = typer.Option(Path("artifacts/graph_viz"), help="Output directory for HTML files"),
    compare_file: str = typer.Option("compare.html", help="Output compare HTML filename"),
    baseline_file: str = typer.Option("baseline.html", help="Baseline graph HTML filename"),
    simulated_file: str = typer.Option("simulated.html", help="Simulated graph HTML filename"),
    strict: bool = typer.Option(False, help="Strict scenario application mode"),
    focus_start: str = typer.Option(None, "--focus-start", help="Optional start URI to visualize local neighborhood"),
    depth: int = typer.Option(2, help="Focus traversal depth (used only with --focus-start)"),
    direction: Direction = typer.Option("both", help="Focus traversal direction"),
    max_results: int = typer.Option(200, help="Focus traversal safety cutoff"),
):
    """
    Generate side-by-side HTML visualization for baseline vs simulated graphs.
    """
    _require_pyvis()

    sg = ShopifyGraph.from_ttl(ontology, instances)
    scenario = _load_scenario(scenario_json)
    applied = apply_scenario_to_graph(sg.nx_graph, scenario, strict=strict)

    baseline_graph = sg.nx_graph
    simulated_graph = applied.nx_graph

    if focus_start:
        traversal = TraversalSpec(
            depth=depth,
            direction=direction,
            max_results=max_results,
            top_n=10,
        )
        baseline_graph = _focused_subgraph(baseline_graph, focus_start, traversal)
        simulated_graph = _focused_subgraph(simulated_graph, focus_start, traversal)

    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = out_dir / baseline_file
    simulated_path = out_dir / simulated_file
    compare_path = out_dir / compare_file

    _render_graph_html(baseline_graph, baseline_path, "Baseline")
    _render_graph_html(simulated_graph, simulated_path, "Simulated")
    _write_compare_html(compare_path, baseline_file, simulated_file)

    typer.echo("\n=== GRAPH VISUALIZATION ===")
    typer.echo(f"Scenario: {scenario.scenario_id}")
    typer.echo(f"Baseline HTML: {baseline_path}")
    typer.echo(f"Simulated HTML: {simulated_path}")
    typer.echo(f"Compare HTML: {compare_path}")
    typer.echo(
        "Scenario apply summary: "
        f"attr_applied={applied.applied_attribute_overrides}, "
        f"attr_skipped={applied.skipped_attribute_overrides}, "
        f"edge_adds={applied.applied_edge_adds}, "
        f"edge_adds_skipped={applied.skipped_edge_adds}, "
        f"edge_removes={applied.applied_edge_removes}, "
        f"edge_removes_skipped={applied.skipped_edge_removes}"
    )


if __name__ == "__main__":
    app()