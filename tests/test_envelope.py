"""Tests for orchestration.envelope — RequestEnvelope validation & scenario resolution."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestration.envelope import RequestEnvelope, load_envelope_file


# ─── RequestEnvelope construction / validation ────────────────────────────────

class TestRequestEnvelopeValidation:
    def test_blast_with_start_uri_no_questions(self):
        env = RequestEnvelope(intent="blast", start_uri="urn:x")
        assert env.intent == "blast"
        assert env.clarifying_questions == []
        assert env.assumptions == []

    def test_blast_without_start_uri_asks_question(self):
        env = RequestEnvelope(intent="blast")
        assert len(env.clarifying_questions) == 1
        assert "start_uri" in env.clarifying_questions[0]

    def test_impact_without_change_defaults_change(self):
        env = RequestEnvelope(intent="impact", start_uri="urn:x")
        assert env.change is not None
        assert env.change.target_uri == "urn:x"
        assert env.change.change_type == "relationship_change"
        assert len(env.assumptions) == 1

    def test_impact_without_start_uri_asks(self):
        env = RequestEnvelope(intent="impact")
        assert any("start_uri" in q for q in env.clarifying_questions)

    def test_simulate_without_scenario_asks(self):
        env = RequestEnvelope(intent="simulate", start_uri="urn:x")
        assert any("scenario" in q.lower() for q in env.clarifying_questions)

    def test_simulate_with_scenario_file_no_question(self):
        # scenario_file provided suppresses the "provide scenario" question
        env = RequestEnvelope(intent="simulate", start_uri="urn:x", scenario_file="fake.json")
        scenario_questions = [q for q in env.clarifying_questions if "scenario" in q.lower()]
        assert len(scenario_questions) == 0

    def test_help_no_questions(self):
        env = RequestEnvelope(intent="help")
        assert env.clarifying_questions == []
        assert env.assumptions == []

    def test_invalid_intent_rejected(self):
        with pytest.raises(ValidationError):
            RequestEnvelope(intent="unknown")

    def test_traversal_defaults(self):
        env = RequestEnvelope(intent="blast", start_uri="urn:x")
        assert env.traversal.depth == 4
        assert env.traversal.direction == "both"
        assert env.traversal.max_results == 200
        assert env.traversal.top_n == 10

    def test_custom_traversal(self):
        env = RequestEnvelope(
            intent="blast",
            start_uri="urn:x",
            traversal={"depth": 2, "direction": "out"},
        )
        assert env.traversal.depth == 2
        assert env.traversal.direction == "out"

    def test_model_dump_roundtrip(self):
        env = RequestEnvelope(intent="blast", start_uri="urn:x")
        d = env.model_dump()
        env2 = RequestEnvelope.model_validate(d)
        assert env2.intent == env.intent
        assert env2.start_uri == env.start_uri


# ─── resolve_scenario ────────────────────────────────────────────────────────

class TestResolveScenario:
    def test_resolve_from_file(self, tmp_path):
        scenario_data = {
            "scenario_id": "test_resolve",
            "description": "test",
            "attribute_overrides": [],
            "edge_mutations": [],
        }
        sf = tmp_path / "test_scenario.json"
        sf.write_text(json.dumps(scenario_data), encoding="utf-8")

        env = RequestEnvelope(
            intent="simulate",
            start_uri="urn:x",
            scenario_file=str(sf),
        )
        env.resolve_scenario()
        assert env.scenario is not None
        assert env.scenario.scenario_id == "test_resolve"

    def test_resolve_with_base_dir(self, tmp_path):
        scenario_data = {
            "scenario_id": "relative_test",
            "attribute_overrides": [],
            "edge_mutations": [],
        }
        sf = tmp_path / "sub" / "sc.json"
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(scenario_data), encoding="utf-8")

        env = RequestEnvelope(
            intent="simulate",
            start_uri="urn:x",
            scenario_file="sub/sc.json",
        )
        env.resolve_scenario(base_dir=tmp_path)
        assert env.scenario is not None
        assert env.scenario.scenario_id == "relative_test"

    def test_resolve_missing_file_raises(self, tmp_path):
        env = RequestEnvelope(
            intent="simulate",
            start_uri="urn:x",
            scenario_file="nonexistent.json",
        )
        with pytest.raises(ValueError, match="not found"):
            env.resolve_scenario(base_dir=tmp_path)

    def test_resolve_skips_non_simulate(self):
        env = RequestEnvelope(intent="blast", start_uri="urn:x")
        result = env.resolve_scenario()
        assert result is env  # no-op

    def test_resolve_skips_if_scenario_already_set(self):
        from core.models import ScenarioSpec

        env = RequestEnvelope(
            intent="simulate",
            start_uri="urn:x",
            scenario=ScenarioSpec(scenario_id="embedded", attribute_overrides=[], edge_mutations=[]),
        )
        result = env.resolve_scenario()
        assert result.scenario.scenario_id == "embedded"


# ─── load_envelope_file ──────────────────────────────────────────────────────

class TestLoadEnvelopeFile:
    def test_loads_valid_json(self, tmp_path):
        p = tmp_path / "env.json"
        p.write_text('{"intent": "blast"}', encoding="utf-8")
        result = load_envelope_file(p)
        assert result == {"intent": "blast"}

    def test_rejects_non_object(self, tmp_path):
        p = tmp_path / "env.json"
        p.write_text("[1,2,3]", encoding="utf-8")
        with pytest.raises(ValueError, match="must be an object"):
            load_envelope_file(p)

    def test_rejects_invalid_json(self, tmp_path):
        p = tmp_path / "env.json"
        p.write_text("{bad}", encoding="utf-8")
        with pytest.raises(Exception):
            load_envelope_file(p)
