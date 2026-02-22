"""Tests for orchestration.openai_interpreter — AutoEnvelope, OpenAI mock, and schema guards."""

import json
from types import SimpleNamespace
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest

from core.models import ChangeType
from orchestration.openai_interpreter import (
    AutoEnvelopeInterpreter,
    ENVELOPE_SCHEMA,
    OpenAIEnvelopeInterpreter,
    _CHANGE_TYPES,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

class FakeNLInterpreter:
    """Records calls so we can assert delegation."""

    def __init__(self, result: dict | None = None):
        self.calls: list[str] = []
        self._result = result or {"intent": "help"}

    def interpret(self, text: str) -> dict:
        self.calls.append(text)
        return self._result


# ─── Schema-level guards ─────────────────────────────────────────────────────

class TestSchemaIntegrity:
    def test_change_types_match_canonical_literal(self):
        """_CHANGE_TYPES must mirror core.models.ChangeType exactly."""
        assert set(_CHANGE_TYPES) == set(get_args(ChangeType))

    def test_schema_uses_validate_scenario_not_validate(self):
        props = ENVELOPE_SCHEMA["properties"]
        assert "validate_scenario" in props, "Schema should use 'validate_scenario'"
        assert "validate" not in props, "Schema should NOT have bare 'validate'"

    def test_validate_scenario_in_required(self):
        required = ENVELOPE_SCHEMA["required"]
        assert "validate_scenario" in required
        assert "validate" not in required


# ─── AutoEnvelopeInterpreter ─────────────────────────────────────────────────

class TestAutoEnvelopeInterpreterJSON:
    """When input looks like JSON (starts with '{'), parse locally."""

    @pytest.fixture
    def nl(self):
        return FakeNLInterpreter()

    @pytest.fixture
    def auto(self, nl):
        return AutoEnvelopeInterpreter(nl=nl)

    def test_valid_json_parsed_locally(self, auto, nl):
        result = auto.interpret('{"intent": "blast"}')
        assert result == {"intent": "blast"}
        assert nl.calls == [], "NL interpreter should NOT be called for JSON input"

    def test_valid_json_with_whitespace(self, auto):
        result = auto.interpret('  \n  {"intent": "help"}  ')
        assert result == {"intent": "help"}

    def test_nested_json_preserved(self, auto):
        text = json.dumps({"intent": "blast", "traversal": {"depth": 3}})
        result = auto.interpret(text)
        assert result["traversal"]["depth"] == 3

    def test_bom_prefixed_json_parsed(self, auto, nl):
        bom_text = "\ufeff" + '{"intent": "simulate"}'
        result = auto.interpret(bom_text)
        assert result == {"intent": "simulate"}
        assert nl.calls == [], "BOM JSON should be parsed locally, not delegated"

    def test_malformed_json_raises_value_error(self, auto):
        with pytest.raises(ValueError, match="Invalid JSON envelope"):
            auto.interpret("{bad json!!}")

    def test_empty_object(self, auto):
        result = auto.interpret("{}")
        assert result == {}


class TestAutoEnvelopeInterpreterDelegation:
    """When input does NOT start with '{', delegate to NL interpreter."""

    @pytest.fixture
    def nl(self):
        return FakeNLInterpreter(result={"intent": "blast", "start_uri": "https://example.com/shopify-inst#prod_mug"})

    @pytest.fixture
    def auto(self, nl):
        return AutoEnvelopeInterpreter(nl=nl)

    def test_plain_text_delegates(self, auto, nl):
        auto.interpret("show me the blast radius for prod_mug")
        assert len(nl.calls) == 1
        assert "prod_mug" in nl.calls[0]

    def test_json_array_delegates(self, auto, nl):
        """A JSON array doesn't start with '{', so it delegates to NL."""
        auto.interpret("[1, 2, 3]")
        assert len(nl.calls) == 1

    def test_json_string_delegates(self, auto, nl):
        auto.interpret('"hello"')
        assert len(nl.calls) == 1

    def test_empty_string_delegates(self, auto, nl):
        auto.interpret("")
        assert len(nl.calls) == 1

    def test_delegation_returns_nl_result(self, auto):
        result = auto.interpret("what is the impact?")
        assert result["intent"] == "blast"


# ─── OpenAIEnvelopeInterpreter (mocked) ──────────────────────────────────────

class TestOpenAIEnvelopeInterpreter:

    @pytest.fixture
    def mock_openai(self):
        with patch("orchestration.openai_interpreter.OpenAI") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            yield client

    @pytest.fixture
    def interp(self, mock_openai):
        with patch("orchestration.openai_interpreter.load_dotenv"):
            return OpenAIEnvelopeInterpreter()

    def _set_response(self, mock_openai, output_text: str):
        resp = SimpleNamespace(output_text=output_text)
        mock_openai.responses.create.return_value = resp

    def test_valid_structured_output(self, interp, mock_openai):
        envelope = {"intent": "blast", "start_uri": "https://example.com/shopify-inst#prod_mug"}
        self._set_response(mock_openai, json.dumps(envelope))

        result = interp.interpret("blast radius for prod_mug")
        assert result == envelope

    def test_empty_output_text_raises(self, interp, mock_openai):
        self._set_response(mock_openai, "")
        with pytest.raises(ValueError, match="no output_text"):
            interp.interpret("something")

    def test_non_json_output_raises(self, interp, mock_openai):
        self._set_response(mock_openai, "This is not JSON at all")
        with pytest.raises(ValueError, match="non-JSON output"):
            interp.interpret("something")

    def test_json_array_output_raises(self, interp, mock_openai):
        self._set_response(mock_openai, "[1, 2, 3]")
        with pytest.raises(ValueError, match="must be a JSON object"):
            interp.interpret("something")

    def test_passes_system_prompt_and_user_text(self, interp, mock_openai):
        envelope = {"intent": "help"}
        self._set_response(mock_openai, json.dumps(envelope))

        interp.interpret("help me")

        call_kwargs = mock_openai.responses.create.call_args
        messages = call_kwargs.kwargs.get("input") or call_kwargs[1].get("input")
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "help me"
