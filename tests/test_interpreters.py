"""Tests for orchestration.interpreters — JSON envelope parsing."""

import json

import pytest

from orchestration.interpreters import JsonEnvelopeInterpreter


@pytest.fixture
def interpreter():
    return JsonEnvelopeInterpreter()


# ─── Happy-path tests ────────────────────────────────────────────────────────

class TestJsonEnvelopeInterpreterHappy:
    def test_valid_object(self, interpreter):
        raw = interpreter.interpret('{"intent": "blast"}')
        assert raw == {"intent": "blast"}

    def test_strips_whitespace(self, interpreter):
        raw = interpreter.interpret('   \n\t {"intent": "help"}  \n ')
        assert raw == {"intent": "help"}

    def test_nested_structure_preserved(self, interpreter):
        text = json.dumps({
            "intent": "blast",
            "traversal": {"depth": 3, "direction": "both"},
        })
        raw = interpreter.interpret(text)
        assert raw["traversal"]["depth"] == 3

    def test_empty_object(self, interpreter):
        raw = interpreter.interpret("{}")
        assert raw == {}


# ─── Error-path tests ────────────────────────────────────────────────────────

class TestJsonEnvelopeInterpreterErrors:
    def test_invalid_json_raises_value_error(self, interpreter):
        with pytest.raises(ValueError, match="Invalid JSON envelope"):
            interpreter.interpret("{bad json}")

    def test_empty_string_raises(self, interpreter):
        with pytest.raises(ValueError, match="Invalid JSON envelope"):
            interpreter.interpret("")

    def test_json_array_raises(self, interpreter):
        with pytest.raises(ValueError, match="must be an object"):
            interpreter.interpret('[1, 2, 3]')

    def test_json_string_raises(self, interpreter):
        with pytest.raises(ValueError, match="must be an object"):
            interpreter.interpret('"hello"')

    def test_json_number_raises(self, interpreter):
        with pytest.raises(ValueError, match="must be an object"):
            interpreter.interpret("42")

    def test_json_null_raises(self, interpreter):
        with pytest.raises(ValueError, match="must be an object"):
            interpreter.interpret("null")
