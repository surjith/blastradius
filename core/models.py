from typing import Dict, List, Literal
from pydantic import BaseModel, Field, ConfigDict

Direction = Literal["out", "in", "both"]

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