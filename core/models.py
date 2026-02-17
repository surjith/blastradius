from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

Direction = Literal["out", "in", "both"]
ChangeType = Literal[
    "entity_state_change",   # status/availability/activation changes
    "attribute_change",      # price/discount/tax/config value changes
    "relationship_change",   # add/remove relationship edge(s)
    "schema_change",         # ontology/schema/contract changes
    "outage",                # external disruption / service unavailable
]


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
    depth: int = 4
    direction: Direction = "both"
    max_results: int = 200
    top_n : int = 10

class ImpactSummary(BaseModel):
    counts_by_type: Dict[str, int] = Field(default_factory=dict)
    total_impacted: int = 0

class ImpactReport(BaseModel):
    change: ChangeSpec
    traversal: TraversalSpec
    summary: ImpactSummary
    top_impacts: List[ImpactItem] = Field(default_factory=list)
