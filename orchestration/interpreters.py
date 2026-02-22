from __future__ import annotations

import json
from typing import Any, Protocol


class EnvelopeInterpreter(Protocol):
    def interpret(self, text: str) -> dict[str, Any]: ...


class JsonEnvelopeInterpreter:
    """
    Deterministic interpreter: user provides the envelope as JSON text.
    """

    def interpret(self, text: str) -> dict[str, Any]:
        t = text.strip()
        try:
            raw = json.loads(t)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON envelope: {e}")
        if not isinstance(raw, dict):
            raise ValueError("Envelope JSON must be an object (dict).")
        return raw