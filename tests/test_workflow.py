"""Tests for orchestration.workflow — WorkflowBuilder node methods and routing."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from orchestration.envelope import RequestEnvelope
from orchestration.interpreters import JsonEnvelopeInterpreter
from orchestration.workflow import AgentState, WorkflowBuilder, _VALID_INTENTS


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fake_graph():
    """Return a MagicMock standing in for ShopifyGraph."""
    return MagicMock()


def _builder() -> WorkflowBuilder:
    return WorkflowBuilder(graph=_fake_graph(), interpreter=JsonEnvelopeInterpreter())


def _blast_envelope_dict(**overrides) -> dict[str, Any]:
    base = {
        "intent": "blast",
        "start_uri": "urn:test#node",
        "traversal": {"depth": 2, "direction": "out", "max_results": 50, "top_n": 5},
    }
    base.update(overrides)
    return RequestEnvelope.model_validate(base).model_dump()


def _impact_envelope_dict(**overrides) -> dict[str, Any]:
    base = {
        "intent": "impact",
        "start_uri": "urn:test#node",
        "change": {"change_type": "relationship_change", "target_uri": "urn:test#node"},
        "traversal": {"depth": 2, "direction": "out", "max_results": 50, "top_n": 5},
    }
    base.update(overrides)
    return RequestEnvelope.model_validate(base).model_dump()


# ─── parse_node ──────────────────────────────────────────────────────────────

class TestParseNode:
    def test_valid_json_returns_envelope_raw(self):
        wb = _builder()
        state: AgentState = {"user_input": '{"intent": "blast", "start_uri": "urn:x"}'}
        result = wb.parse_node(state)
        assert "envelope_raw" in result
        assert result["envelope_raw"]["intent"] == "blast"

    def test_invalid_json_returns_error(self):
        wb = _builder()
        state: AgentState = {"user_input": "not json at all"}
        result = wb.parse_node(state)
        assert "error" in result
        assert "Parse failed" in result["error"]


# ─── validate_node ───────────────────────────────────────────────────────────

class TestValidateNode:
    def test_skips_if_error_present(self):
        wb = _builder()
        state: AgentState = {"error": "something broke"}
        result = wb.validate_node(state)
        assert result == {}

    def test_valid_blast_envelope(self):
        wb = _builder()
        state: AgentState = {
            "envelope_raw": {"intent": "blast", "start_uri": "urn:x"},
        }
        result = wb.validate_node(state)
        assert "envelope" in result
        assert result["envelope"]["intent"] == "blast"
        assert "error" not in result

    def test_missing_start_uri_returns_clarification(self):
        wb = _builder()
        state: AgentState = {"envelope_raw": {"intent": "blast"}}
        result = wb.validate_node(state)
        assert "response" in result
        assert "clarification" in result["response"].lower() or "start_uri" in result["response"]

    def test_invalid_envelope_returns_error(self):
        wb = _builder()
        state: AgentState = {"envelope_raw": {"intent": "nope"}}
        result = wb.validate_node(state)
        assert "error" in result
        assert "validation failed" in result["error"].lower()


# ─── route ───────────────────────────────────────────────────────────────────

class TestRoute:
    def test_response_set_returns_done(self):
        result = WorkflowBuilder.route({"response": "something"})
        assert result == "done"

    def test_error_returns_format(self):
        result = WorkflowBuilder.route({"error": "oops"})
        assert result == "format"

    def test_no_envelope_returns_format(self):
        result = WorkflowBuilder.route({})
        assert result == "format"

    @pytest.mark.parametrize("intent", ["blast", "impact", "simulate", "help"])
    def test_valid_intent_routed(self, intent):
        result = WorkflowBuilder.route({"envelope": {"intent": intent}})
        assert result == intent

    def test_unknown_intent_falls_to_format(self):
        result = WorkflowBuilder.route({"envelope": {"intent": "mystery"}})
        assert result == "format"


# ─── run_blast ───────────────────────────────────────────────────────────────

class TestRunBlast:
    def test_missing_envelope_returns_error(self):
        wb = _builder()
        state: AgentState = {}
        result = wb.run_blast(state)
        assert "error" in result

    def test_missing_start_uri_returns_error(self):
        wb = _builder()
        env = RequestEnvelope(intent="blast").model_dump()
        state: AgentState = {"envelope": env}
        result = wb.run_blast(state)
        assert "error" in result
        assert "start_uri" in result["error"]

    @patch("orchestration.workflow.tool_blast")
    def test_success_returns_serialized_result(self, mock_tool):
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"start": "urn:x", "reached": []}
        mock_tool.return_value = mock_result

        wb = _builder()
        state: AgentState = {"envelope": _blast_envelope_dict()}
        result = wb.run_blast(state)
        assert "result" in result
        assert result["result"]["start"] == "urn:x"

    @patch("orchestration.workflow.tool_blast", side_effect=RuntimeError("boom"))
    def test_exception_returns_error(self, mock_tool):
        wb = _builder()
        state: AgentState = {"envelope": _blast_envelope_dict()}
        result = wb.run_blast(state)
        assert "error" in result
        assert "Blast failed" in result["error"]


# ─── run_impact ──────────────────────────────────────────────────────────────

class TestRunImpact:
    def test_missing_change_returns_error(self):
        wb = _builder()
        # envelope with no change and no start_uri → no auto-default
        env = RequestEnvelope(intent="help").model_dump()
        env["intent"] = "impact"  # force intent after construction
        state: AgentState = {"envelope": env}
        result = wb.run_impact(state)
        assert "error" in result

    @patch("orchestration.workflow.tool_impact")
    def test_success(self, mock_tool):
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"change": {}, "summary": {}}
        mock_tool.return_value = mock_result

        wb = _builder()
        state: AgentState = {"envelope": _impact_envelope_dict()}
        result = wb.run_impact(state)
        assert "result" in result


# ─── run_simulate ────────────────────────────────────────────────────────────

class TestRunSimulate:
    def test_missing_scenario_returns_error(self):
        wb = _builder()
        env = _impact_envelope_dict(intent="simulate")
        # no scenario set
        state: AgentState = {"envelope": env}
        result = wb.run_simulate(state)
        assert "error" in result

    @patch("orchestration.workflow.tool_simulate")
    def test_success(self, mock_tool):
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"scenario": {}, "delta": {}}
        mock_tool.return_value = mock_result

        wb = _builder()
        env = _impact_envelope_dict(intent="simulate")
        env["scenario"] = {
            "scenario_id": "test_sim",
            "attribute_overrides": [],
            "edge_mutations": [],
        }
        state: AgentState = {"envelope": env}
        result = wb.run_simulate(state)
        assert "result" in result


# ─── format_node ─────────────────────────────────────────────────────────────

class TestFormatNode:
    def test_skips_if_response_set(self):
        result = WorkflowBuilder.format_node({"response": "already done"})
        assert result == {}

    def test_surfaces_error(self):
        result = WorkflowBuilder.format_node({"error": "something broke"})
        assert result["response"] == "something broke"

    def test_missing_envelope_returns_internal_error(self):
        result = WorkflowBuilder.format_node({})
        assert "Internal error" in result["response"]

    def test_missing_result_returns_internal_error(self):
        result = WorkflowBuilder.format_node({
            "envelope": {"intent": "blast"},
            # result is None / missing
        })
        assert "Internal error" in result["response"]
        assert "missing result" in result["response"]

    @patch("orchestration.workflow.format_blast", return_value="BLAST output")
    def test_blast_formatting(self, mock_fmt):
        from core.models import BlastRadiusResults

        res = BlastRadiusResults(
            start="urn:x", depth=2, direction="out", reached=[], paths={}
        )
        result = WorkflowBuilder.format_node({
            "envelope": {"intent": "blast"},
            "result": res.model_dump(),
        })
        assert result["response"] == "BLAST output"

    def test_unknown_intent_returns_help(self):
        result = WorkflowBuilder.format_node({
            "envelope": {"intent": "unknown_thing"},
            "result": {"some": "data"},
        })
        assert "help" in result["response"]


# ─── help_node ───────────────────────────────────────────────────────────────

class TestHelpNode:
    def test_returns_help_message(self):
        result = WorkflowBuilder.help_node({})
        assert "help" in result["response"]
        assert "blast" in result["response"]
        assert "impact" in result["response"]
        assert "simulate" in result["response"]


# ─── _load_envelope (static helper) ─────────────────────────────────────────

class TestLoadEnvelope:
    def test_returns_none_when_missing(self):
        result = WorkflowBuilder._load_envelope({})
        assert result is None

    def test_reconstructs_envelope(self):
        env = RequestEnvelope(intent="blast", start_uri="urn:x")
        result = WorkflowBuilder._load_envelope({"envelope": env.model_dump()})
        assert result is not None
        assert result.intent == "blast"
        assert result.start_uri == "urn:x"


# ─── compile / build_workflow ────────────────────────────────────────────────

class TestCompile:
    def test_compile_returns_compiled_graph(self):
        wb = _builder()
        compiled = wb.compile()
        # LangGraph compiled graphs have an invoke method
        assert hasattr(compiled, "invoke")

    def test_build_workflow_shortcut(self):
        from orchestration.workflow import build_workflow

        compiled = build_workflow(
            graph=_fake_graph(),
            interpreter=JsonEnvelopeInterpreter(),
        )
        assert hasattr(compiled, "invoke")
