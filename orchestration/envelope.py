from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from core.models import ChangeSpec, ScenarioSpec, TraversalSpec

Intent = Literal["blast", "impact", "simulate", "help"]


class RequestEnvelope(BaseModel):
    """
    Day 4 contract for orchestration.
    - intent determines routing
    - start_uri is the anchor node for blast/impact/simulate
    - traversal controls BFS depth/direction/cutoffs
    - change required for impact/simulate (can be defaulted)
    - scenario required for simulate (can be embedded or loaded from scenario_file)
    """

    intent: Intent
    start_uri: Optional[str] = None

    traversal: TraversalSpec = Field(default_factory=TraversalSpec)
    change: Optional[ChangeSpec] = None

    scenario: Optional[ScenarioSpec] = None
    scenario_file: Optional[str] = None

    strict: bool = False
    validate_scenario: bool = True

    assumptions: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _post_validate(self) -> "RequestEnvelope":
        questions: list[str] = []
        assumptions: list[str] = []

        if self.intent in {"blast", "impact", "simulate"} and not self.start_uri:
            questions.append("Provide start_uri (a node URI).")

        if self.intent in {"impact", "simulate"} and self.start_uri and self.change is None:
            assumptions.append(
                "No change provided; defaulting change_type='relationship_change' and target_uri=start_uri."
            )
            self.change = ChangeSpec(change_type="relationship_change", target_uri=self.start_uri)

        if self.intent == "simulate":
            if self.scenario is None and not self.scenario_file:
                questions.append("Provide scenario (embedded) or scenario_file (path to scenario JSON).")

        # set (not append) to avoid duplicating on re-validation
        self.assumptions = assumptions
        self.clarifying_questions = questions
        return self

    def resolve_scenario(self, *, base_dir: Path | None = None) -> "RequestEnvelope":
        """
        If scenario_file is set, load it and populate scenario.
        base_dir allows scenario_file paths relative to the envelope file location.
        """
        if self.intent != "simulate":
            return self
        if self.scenario is not None:
            return self
        if not self.scenario_file:
            return self

        p = Path(self.scenario_file)
        if base_dir and not p.is_absolute():
            p = base_dir / p
        if not p.exists():
            raise ValueError(f"scenario_file not found: {p}")

        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        self.scenario = ScenarioSpec.model_validate(raw)
        return self


def load_envelope_file(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("Envelope JSON must be an object")
    return raw