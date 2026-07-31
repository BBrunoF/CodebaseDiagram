import json
import unittest

from csd import schema


def sample_graph():
    return schema.Graph(
        meta={
            "tool_version": schema.TOOL_VERSION,
            "entry_point": "pkg.main.main",
            "resolution": {"resolved": 1, "unresolved_dynamic": 2, "external": 3},
            "entry_locals": [
                {"var": "x", "producer": "pkg.a.f", "status": "consumed"}
            ],
        },
        nodes=[
            schema.Node(
                id="pkg.a.f", qualname="f", module="pkg.a", file="pkg/a.py",
                lines=[1, 3], params=["n"], call_order=1, has_io=False,
                has_loop=True, returns_value=True, is_terminal=False,
                is_dead=False,
            )
        ],
        call_edges=[schema.CallEdge(caller="pkg.main.main", callee="pkg.a.f", line=4)],
        dataflow_edges=[
            schema.DataflowEdge(
                producer="pkg.a.f", consumer="pkg.main.main", var="x",
                line=5, consumed_by="external_call",
            )
        ],
    )


class SchemaRoundTrip(unittest.TestCase):
    def test_round_trip(self):
        graph = sample_graph()
        text = graph.to_json()
        loaded = schema.Graph.from_json(text)
        self.assertEqual(loaded, graph)

    def test_json_is_deterministic(self):
        self.assertEqual(sample_graph().to_json(), sample_graph().to_json())

    def test_csd_error_is_exception(self):
        self.assertTrue(issubclass(schema.CsdError, Exception))


class KeyOrder(unittest.TestCase):
    """graph.json reads in the order the schema declares, not alphabetically."""

    def setUp(self):
        self.raw = json.loads(sample_graph().to_json())

    def test_top_level_order(self):
        self.assertEqual(
            list(self.raw),
            ["meta", "nodes", "call_edges", "dataflow_edges"],
        )

    def test_meta_order(self):
        self.assertEqual(
            list(self.raw["meta"]),
            ["tool_version", "entry_point", "resolution", "entry_locals"],
        )

    def test_resolution_reads_in_the_printed_order(self):
        self.assertEqual(
            list(self.raw["meta"]["resolution"]),
            ["resolved", "unresolved_dynamic", "external"],
        )

    def test_node_field_order(self):
        self.assertEqual(
            list(self.raw["nodes"][0]),
            ["id", "qualname", "module", "file", "lines", "params",
             "call_order", "has_io", "has_loop", "returns_value",
             "is_terminal", "is_dead"],
        )

    def test_edge_field_order(self):
        self.assertEqual(
            list(self.raw["call_edges"][0]), ["caller", "callee", "line"]
        )
        self.assertEqual(
            list(self.raw["dataflow_edges"][0]),
            ["producer", "consumer", "var", "line", "consumed_by"],
        )


if __name__ == "__main__":
    unittest.main()
