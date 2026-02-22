"""
Orchestration workflow — LangGraph state-machine that routes JSON envelopes
through parse → validate → execute → format.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from core.models import BlastRadiusResults, ImpactReport, ScenarioResult
from core.shopify_graph import ShopifyGraph
from orchestration.envelope import RequestEnvelope
from orchestration.formatters import format_blast, format_impact, format_simulation
from orchestration.interpreters import EnvelopeInterpreter
from orchestration.tools import tool_blast, tool_impact, tool_simulate

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

# Known intents that map to execution nodes
_VALID_INTENTS = frozenset({"blast", "impact", "simulate", "help"})


# ---------------------------------------------------------------------------
# State — all values are JSON-serializable (dicts / strings / None).
# Pydantic models are reconstructed inside nodes that need them.
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    user_input: str
    envelope_raw: Optional[dict[str, Any]]
    envelope: Optional[dict[str, Any]]        # RequestEnvelope.model_dump()
    response: Optional[str]
    error: Optional[str]
    result: Optional[dict[str, Any]]          # result model .model_dump()
    base_dir: Optional[str]                   # str(Path) — serializable


# ---------------------------------------------------------------------------
# WorkflowBuilder — each public method is a LangGraph node.
# ---------------------------------------------------------------------------

class WorkflowBuilder:
    """
    Builds and compiles a LangGraph state-machine for envelope-driven
    blast / impact / simulate workflows.

    Usage::

        wf = WorkflowBuilder(graph=sg, interpreter=interp)
        compiled = wf.compile()
        result = compiled.invoke({"user_input": json_text})
    """

    def __init__(
        self,
        *,
        graph: ShopifyGraph,
        interpreter: EnvelopeInterpreter,
    ) -> None:
        self._graph = graph
        self._interpreter = interpreter

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _load_envelope(state: AgentState) -> RequestEnvelope | None:
        """Reconstruct a validated RequestEnvelope from the serialised dict."""
        raw = state.get("envelope")
        if raw is None:
            return None
        return RequestEnvelope.model_validate(raw)

    # -- node methods ---------------------------------------------------------

    def parse_node(self, state: AgentState) -> dict[str, Any]:
        try:
            raw = self._interpreter.interpret(state["user_input"])
            return {"envelope_raw": raw}
        except Exception as e:
            return {"error": f"Parse failed: {e}"}

    def validate_node(self, state: AgentState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        try:
            env = RequestEnvelope.model_validate(state.get("envelope_raw") or {})

            base_dir_str = state.get("base_dir")
            base_dir = Path(base_dir_str) if base_dir_str else None
            env.resolve_scenario(base_dir=base_dir)

            if env.clarifying_questions:
                q = "\n".join(f"- {x}" for x in env.clarifying_questions)
                a = "\n".join(f"- {x}" for x in env.assumptions) if env.assumptions else ""
                msg = "Need clarification:\n" + q
                if a:
                    msg += "\n\nAssumptions applied:\n" + a
                return {"envelope": env.model_dump(), "response": msg}

            return {"envelope": env.model_dump()}
        except Exception as e:
            return {"error": f"Envelope validation failed: {e}"}

    @staticmethod
    def route(state: AgentState) -> str:
        if state.get("response"):
            return "done"               # response already set (clarification) → skip format
        if state.get("error"):
            return "format"             # error needs to be surfaced via format
        env = state.get("envelope")
        if env is None:
            return "format"
        intent = env.get("intent")
        if intent in _VALID_INTENTS:
            return intent
        return "format"                 # unknown intent → let format surface a help message

    def run_blast(self, state: AgentState) -> dict[str, Any]:
        env = self._load_envelope(state)
        if not env or not env.start_uri:
            return {"error": "Envelope missing start_uri for blast."}
        try:
            result = tool_blast(self._graph, env.start_uri, env.traversal)
            return {"result": result.model_dump()}
        except Exception as e:
            return {"error": f"Blast failed: {e}"}

    def run_impact(self, state: AgentState) -> dict[str, Any]:
        env = self._load_envelope(state)
        if not env or not env.change:
            return {"error": "Envelope missing change spec for impact."}
        try:
            result = tool_impact(self._graph, env.change, env.traversal)
            return {"result": result.model_dump()}
        except Exception as e:
            return {"error": f"Impact failed: {e}"}

    def run_simulate(self, state: AgentState) -> dict[str, Any]:
        env = self._load_envelope(state)
        if not env or not env.change or not env.scenario:
            return {"error": "Envelope missing change/scenario for simulate."}
        try:
            result = tool_simulate(
                self._graph,
                env.scenario,
                env.change,
                env.traversal,
                strict=env.strict,
                validate=env.validate_scenario,
            )
            return {"result": result.model_dump()}
        except Exception as e:
            return {"error": f"Simulate failed: {e}"}

    def format_node(self, state: AgentState) -> dict[str, Any]:
        if state.get("response"):
            return {}
        if state.get("error"):
            return {"response": state["error"]}

        env_dict = state.get("envelope")
        res_dict = state.get("result")
        if env_dict is None:
            return {"response": "Internal error: missing envelope at format stage."}

        intent = env_dict.get("intent")

        if intent in {"blast", "impact", "simulate"} and res_dict is None:
            return {"response": "Internal error: missing result at format stage."}

        try:
            if intent == "blast":
                return {"response": format_blast(BlastRadiusResults.model_validate(res_dict), graph=self._graph)}
            if intent == "impact":
                return {"response": format_impact(ImpactReport.model_validate(res_dict), graph=self._graph)}
            if intent == "simulate":
                return {"response": format_simulation(ScenarioResult.model_validate(res_dict), graph=self._graph)}
            return {"response": "help: provide a JSON envelope with intent=blast|impact|simulate"}
        except Exception as e:
            return {"response": f"Formatting failed: {e}"}

    @staticmethod
    def help_node(state: AgentState) -> dict[str, Any]:
        return {"response": "help: provide a JSON envelope with intent=blast|impact|simulate"}

    # -- graph wiring & compilation -------------------------------------------

    def compile(self) -> CompiledStateGraph:
        """Wire and compile the LangGraph state-machine."""
        g = StateGraph(AgentState)
        g.add_node("parse", self.parse_node)
        g.add_node("validate", self.validate_node)
        g.add_node("run_blast", self.run_blast)
        g.add_node("run_impact", self.run_impact)
        g.add_node("run_simulate", self.run_simulate)
        g.add_node("help", self.help_node)
        g.add_node("format", self.format_node)

        g.set_entry_point("parse")
        g.add_edge("parse", "validate")

        g.add_conditional_edges(
            "validate",
            self.route,
            {
                "blast": "run_blast",
                "impact": "run_impact",
                "simulate": "run_simulate",
                "help": "help",
                "done": END,            # response already set → skip format
                "format": "format",     # error / fallback → format surfaces it
            },
        )

        g.add_edge("run_blast", "format")
        g.add_edge("run_impact", "format")
        g.add_edge("run_simulate", "format")
        g.add_edge("help", "format")
        g.add_edge("format", END)

        return g.compile()


# ---------------------------------------------------------------------------
# Convenience factory (preserves the old call-site signature)
# ---------------------------------------------------------------------------

def build_workflow(
    *,
    graph: ShopifyGraph,
    interpreter: EnvelopeInterpreter,
) -> CompiledStateGraph:
    """Shortcut: construct a WorkflowBuilder and compile in one step."""
    return WorkflowBuilder(graph=graph, interpreter=interpreter).compile()