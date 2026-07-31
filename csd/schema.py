"""graph.json data model + shared error type.

The ONLY module both the analyze side and the render side import.
"""
import json
from dataclasses import asdict, dataclass, field

TOOL_VERSION = "0.2.1"


class CsdError(Exception):
    """Any condition v1 refuses to handle. CLI turns this into exit 1."""


@dataclass
class Node:
    id: str
    qualname: str
    module: str
    file: str
    lines: list
    params: list
    call_order: int = -1
    has_io: bool = False
    has_loop: bool = False
    returns_value: bool = False
    is_terminal: bool = False
    is_dead: bool = False


@dataclass
class CallEdge:
    caller: str
    callee: str
    line: int


@dataclass
class DataflowEdge:
    producer: str
    consumer: str
    var: str
    line: int
    consumed_by: str  # "call" | "external_call" | "return"


@dataclass
class Graph:
    meta: dict
    nodes: list = field(default_factory=list)
    call_edges: list = field(default_factory=list)
    dataflow_edges: list = field(default_factory=list)

    def to_json(self):
        return json.dumps(
            {
                "meta": self.meta,
                "nodes": [asdict(n) for n in self.nodes],
                "call_edges": [asdict(e) for e in self.call_edges],
                "dataflow_edges": [asdict(e) for e in self.dataflow_edges],
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text):
        raw = json.loads(text)
        return cls(
            meta=raw["meta"],
            nodes=[Node(**n) for n in raw["nodes"]],
            call_edges=[CallEdge(**e) for e in raw["call_edges"]],
            dataflow_edges=[DataflowEdge(**e) for e in raw["dataflow_edges"]],
        )
