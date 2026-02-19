from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

Direction = Literal["out", "in", "both"]
ChangeType = Literal[
    "entity_state_change",   # status/availability/activation changes
    "attribute_change",      # price/discount/tax/config value changes
    "relationship_change",   # add/remove relationship edge(s)
    "schema_change",         # ontology/schema/contract changes
    "outage",                # external disruption / service unavailable
]

#Scenario analysis
OverrideOp = Literal["set", "unset"]
EdgeOp = Literal["add", "remove"]


# capture change
class ChangeSpec(BaseModel):
    change_type: ChangeType
    target_uri: str

    # For attribute / state changes
    attribute_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None

    # For relationship changes (reserved for later)
    relation: Optional[str] = None           # predicate local name (e.g., hasVariant)
    related_uri: Optional[str] = None        # the other endpoint if relevant
    operation: Optional[Literal["add", "remove"]] = None

# ----- Build results / traversal results -----
class NXBuildResults(BaseModel):
    '''Holds the executable NetworkX build results.'''
    model_config = ConfigDict(arbitrary_types_allowed=True)

    nx_graph:object
    object_properties:List[str] = Field(default_factory=list)

class BlastRadiusResults(BaseModel):
    start: str
    depth: int
    direction: Direction
    reached: List[str] = Field(default_factory=list)
    paths: Dict[str, List[List[str]]] = Field(default_factory=dict)

# ----- Impact report (business-facing output) -----

class ImpactItem(BaseModel):
    uri: str
    entity_type: str
    severity: int
    primary_path: List[str]

class TraversalSpec(BaseModel):
    depth: int = Field(default=4, ge=1)
    direction: Direction = "both"
    max_results: int = Field(default=200, ge=1)
    top_n: int = Field(default=10, ge=1)

class ImpactSummary(BaseModel):
    counts_by_type: Dict[str, int] = Field(default_factory=dict)
    total_impacted: int = 0

class ImpactReport(BaseModel):
    change: ChangeSpec
    traversal: TraversalSpec
    summary: ImpactSummary
    top_impacts: List[ImpactItem] = Field(default_factory=list)
    impacted_uris: List[str] = Field(default_factory=list)


#-----------What if / scenario analysis models -----------
class AttributeOverride(BaseModel):
    """
    Override a node attribute for the duration of a scenario.

    Rules:
    - op="set"   -> value must be provided
    - op="unset" -> value must be None
    """
    node_uri: str
    key: str
    op: OverrideOp = "set"
    value: Optional[Any] = None

    @field_validator("node_uri", "key")
    @classmethod
    def _require_non_blank_identity_fields(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty, non-whitespace string")
        return v

    @model_validator(mode="after")
    def _validate_op_value(self) -> "AttributeOverride":
        if self.op == "set" and self.value is None:
            raise ValueError('AttributeOverride: op="set" requires value != None')
        if self.op == "unset" and self.value is not None:
            raise ValueError('AttributeOverride: op="unset" requires value == None')
        return self


class EdgeMutation(BaseModel):
    """
    Add/remove an edge for the duration of a scenario.

    Identification:
    - relation is the NX edge label (edge attribute "relation"), e.g. "hasVariant"
    - src_uri + dst_uri + relation is sufficient for this POC.

    Optional parity fields:
    - predicate_uri can be supplied when adding edges to keep parity with baseline edges
      that store predicate URIs (useful for consistent debugging/auditing).
    """
    op: EdgeOp
    src_uri: str
    dst_uri: str
    relation: str
    predicate_uri: Optional[str] = None  # optional, recommended for op="add"

    @field_validator("src_uri", "dst_uri", "relation")
    @classmethod
    def _require_non_blank_identity_fields(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty, non-whitespace string")
        return v


class ScenarioSpec(BaseModel):
    """
    A what-if scenario represented as deltas on top of the baseline graph.

    scenario_id is required to avoid accidental collisions when comparing runs.
    """
    scenario_id: str = Field(min_length=1)
    description: Optional[str] = None

    attribute_overrides: List[AttributeOverride] = Field(default_factory=list)
    edge_mutations: List[EdgeMutation] = Field(default_factory=list)

    @field_validator("scenario_id")
    @classmethod
    def _require_non_blank_scenario_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("scenario_id must be a non-empty, non-whitespace string")
        return v


class ScenarioDeltaSummary(BaseModel):
    """
    High-level diff summary between baseline and simulated outcomes.

    Determinism:
    - newly_impacted / no_longer_impacted are sorted for stable output.
    """
    total_impacted_baseline: int
    total_impacted_simulated: int

    delta_counts_by_type: Dict[str, int] = Field(default_factory=dict)

    newly_impacted: List[str] = Field(default_factory=list)
    no_longer_impacted: List[str] = Field(default_factory=list)

    @field_validator("newly_impacted", "no_longer_impacted", mode="after")
    @classmethod
    def _sort_uri_lists(cls, v: List[str]) -> List[str]:
        return sorted(v)


class ScenarioResult(BaseModel):
    """
    Output of a simulation: baseline impact, simulated impact, and deltas.
    """
    scenario: ScenarioSpec
    change: "ChangeSpec"
    traversal: "TraversalSpec"

    baseline: "ImpactReport"
    simulated: "ImpactReport"
    delta: ScenarioDeltaSummary
