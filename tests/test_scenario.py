import networkx as nx

from core.models import EdgeMutation, ScenarioSpec
from core.scenario import apply_scenario_to_graph


def _pick_any_edge_with_data(G: nx.MultiDiGraph) -> tuple[str, str, str, dict]:
    for u, v, k, data in G.edges(keys=True, data=True):
        return u, v, k, data
    raise AssertionError("No edges found in graph. Check instance data + object property filtering.")


def test_scenario_add_parallel_edge_same_pair(nx_graph):
    u, v, _, data = _pick_any_edge_with_data(nx_graph)
    new_relation = f'{data.get("relation", "rel")}_scenario'

    scenario = ScenarioSpec(
        scenario_id="scenario_add_parallel",
        edge_mutations=[
            EdgeMutation(
                op="add",
                src_uri=u,
                dst_uri=v,
                relation=new_relation,
                predicate_uri=f"urn:scenario#{new_relation}",
            )
        ],
    )

    applied = apply_scenario_to_graph(nx_graph, scenario)
    edge_bundle = applied.nx_graph.get_edge_data(u, v) or {}
    relations = {d.get("relation") for d in edge_bundle.values()}

    assert applied.applied_edge_adds == 1
    assert applied.skipped_edge_adds == 0
    assert new_relation in relations
    assert len(edge_bundle) >= 2


def test_scenario_add_identical_edge_skips_with_audit(nx_graph):
    u, v, _, data = _pick_any_edge_with_data(nx_graph)

    scenario = ScenarioSpec(
        scenario_id="scenario_add_identical",
        edge_mutations=[
            EdgeMutation(
                op="add",
                src_uri=u,
                dst_uri=v,
                relation=str(data.get("relation")),
                predicate_uri=data.get("predicate_uri"),
            )
        ],
    )

    applied = apply_scenario_to_graph(nx_graph, scenario)

    assert applied.applied_edge_adds == 0
    assert applied.skipped_edge_adds == 1
    assert any("identical edge already exists" in msg for msg in applied.audit_log)


def test_scenario_remove_missing_relation_skips_with_audit(nx_graph):
    u, v, _, _ = _pick_any_edge_with_data(nx_graph)

    scenario = ScenarioSpec(
        scenario_id="scenario_remove_missing_relation",
        edge_mutations=[
            EdgeMutation(
                op="remove",
                src_uri=u,
                dst_uri=v,
                relation="__nonexistent_relation__",
            )
        ],
    )

    applied = apply_scenario_to_graph(nx_graph, scenario)

    assert applied.applied_edge_removes == 0
    assert applied.skipped_edge_removes == 1
    assert any("no matching edge" in msg for msg in applied.audit_log)
