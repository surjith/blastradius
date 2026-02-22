"""Tests for orchestration.tools — thin wrappers over core functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.models import ChangeSpec, ScenarioSpec, TraversalSpec
from orchestration.tools import tool_blast, tool_impact, tool_simulate


@pytest.fixture
def mock_graph():
    g = MagicMock()
    g.nx_graph = MagicMock()
    return g


@pytest.fixture
def traversal():
    return TraversalSpec(depth=2, direction="out")


@pytest.fixture
def change():
    return ChangeSpec(change_type="relationship_change", target_uri="urn:x")


@pytest.fixture
def scenario():
    return ScenarioSpec(
        scenario_id="tool_test",
        attribute_overrides=[],
        edge_mutations=[],
    )


class TestToolBlast:
    @patch("orchestration.tools.blast_radius_paths")
    def test_delegates_to_blast_radius_paths(self, mock_blast, mock_graph, traversal):
        mock_blast.return_value = "blast_result"
        result = tool_blast(mock_graph, "urn:start", traversal)
        mock_blast.assert_called_once_with(mock_graph.nx_graph, start="urn:start", traversalSpec=traversal)
        assert result == "blast_result"


class TestToolImpact:
    @patch("orchestration.tools.analyze_change")
    def test_delegates_to_analyze_change(self, mock_analyze, mock_graph, change, traversal):
        mock_analyze.return_value = "impact_result"
        result = tool_impact(mock_graph, change, traversal)
        mock_analyze.assert_called_once_with(mock_graph, change, traversal)
        assert result == "impact_result"


class TestToolSimulate:
    @patch("orchestration.tools.simulate_change")
    def test_delegates_to_simulate_change(self, mock_sim, mock_graph, scenario, change, traversal):
        mock_sim.return_value = "sim_result"
        result = tool_simulate(mock_graph, scenario, change, traversal, strict=True, validate=False)
        mock_sim.assert_called_once_with(
            baseline_graph=mock_graph,
            scenario=scenario,
            change=change,
            traversal=traversal,
            strict=True,
            validate=False,
        )
        assert result == "sim_result"
