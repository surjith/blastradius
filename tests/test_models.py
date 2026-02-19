import pytest
from pydantic import ValidationError

from core.models import AttributeOverride, EdgeMutation, ScenarioSpec, TraversalSpec


def test_traversal_spec_rejects_non_positive_limits():
    with pytest.raises(ValidationError):
        TraversalSpec(depth=0)
    with pytest.raises(ValidationError):
        TraversalSpec(max_results=0)
    with pytest.raises(ValidationError):
        TraversalSpec(top_n=0)


def test_attribute_override_validates_op_value_and_identity():
    with pytest.raises(ValidationError):
        AttributeOverride(node_uri=" ", key="status", op="set", value="outage")
    with pytest.raises(ValidationError):
        AttributeOverride(node_uri="urn:x", key="status", op="set", value=None)
    with pytest.raises(ValidationError):
        AttributeOverride(node_uri="urn:x", key="status", op="unset", value="x")

    model = AttributeOverride(node_uri="urn:x", key="status", op="set", value="outage")
    assert model.value == "outage"


def test_edge_mutation_and_scenario_spec_reject_blank_identity():
    with pytest.raises(ValidationError):
        EdgeMutation(op="add", src_uri="", dst_uri="urn:b", relation="hasVariant")
    with pytest.raises(ValidationError):
        ScenarioSpec(scenario_id="   ")
