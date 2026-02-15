def test_nx_graph_has_nodes(nx_graph):
    assert nx_graph.number_of_nodes() > 0


def test_nx_graph_has_edges(nx_graph):
    # If this fails, your instances may not use owl:ObjectProperty predicates
    assert nx_graph.number_of_edges() > 0


def test_all_edges_are_object_properties(nx_build):
    G = nx_build.nx_graph
    obj_props = set(nx_build.object_properties)

    assert len(obj_props) > 0  # ensures ontology actually declares object properties

    for u, v, data in G.edges(data=True):
        pred_uri = data.get("predicate_uri")
        assert pred_uri is not None, "Edge missing predicate_uri"
        assert pred_uri in obj_props, f"Edge predicate not an OWL object property: {pred_uri}"
