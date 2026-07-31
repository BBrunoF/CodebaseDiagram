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


if __name__ == "__main__":
    unittest.main()
