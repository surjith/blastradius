import networkx as nx
import pytest

from core.models import AttributeOverride, EdgeMutation, ScenarioSpec
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


def test_scenario_remove_deletes_all_matching_parallel_edges():
    G = nx.MultiDiGraph()
    src = "urn:src"
    dst = "urn:dst"
    pred = "https://example.com/p#hasVariant"
    G.add_edge(src, dst, key="k1", relation="hasVariant", predicate_uri=pred)
    G.add_edge(src, dst, key="k2", relation="hasVariant", predicate_uri=pred)
    G.add_edge(src, dst, key="k3", relation="otherRelation", predicate_uri="https://example.com/p#other")

    scenario = ScenarioSpec(
        scenario_id="remove_all_matches",
        edge_mutations=[
            EdgeMutation(
                op="remove",
                src_uri=src,
                dst_uri=dst,
                relation="hasVariant",
                predicate_uri=pred,
            )
        ],
    )

    applied = apply_scenario_to_graph(G, scenario)
    bundle = applied.nx_graph.get_edge_data(src, dst) or {}
    remaining_relations = {d.get("relation") for d in bundle.values()}

    assert applied.applied_edge_removes == 2
    assert applied.skipped_edge_removes == 0
    assert "hasVariant" not in remaining_relations
    assert "otherRelation" in remaining_relations


def test_scenario_attribute_override_counts_and_audit():
    G = nx.MultiDiGraph()
    G.add_node("urn:ok", uri="urn:ok", status="active")

    scenario = ScenarioSpec(
        scenario_id="attr_counts",
        attribute_overrides=[
            AttributeOverride(op="set", node_uri="urn:ok", key="status", value="outage"),
            AttributeOverride(op="set", node_uri="urn:missing", key="status", value="outage"),
            AttributeOverride(op="unset", node_uri="urn:ok", key="nonexistent"),
        ],
    )

    applied = apply_scenario_to_graph(G, scenario)

    assert applied.applied_attribute_overrides == 1
    assert applied.skipped_attribute_overrides == 2
    assert applied.nx_graph.nodes["urn:ok"]["status"] == "outage"
    assert len(applied.audit_log) >= 2
    assert any("missing node" in msg for msg in applied.audit_log)
    assert any("absent on node" in msg for msg in applied.audit_log)


def test_scenario_strict_mode_raises_on_skip(nx_graph):
    u, v, _, _ = _pick_any_edge_with_data(nx_graph)
    scenario = ScenarioSpec(
        scenario_id="strict_skip",
        edge_mutations=[
            EdgeMutation(
                op="remove",
                src_uri=u,
                dst_uri=v,
                relation="__nonexistent_relation__",
            )
        ],
    )

    with pytest.raises(ValueError, match="Strict scenario mode"):
        apply_scenario_to_graph(nx_graph, scenario, strict=True)
