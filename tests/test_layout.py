import os
import unittest

from csd import cli, layout, schema
from csd.schema import CsdError

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")


def node(nid, **kw):
    defaults = dict(
        qualname=nid.rsplit(".", 1)[1], module="pkg.m", file="pkg/m.py",
        lines=[1, 2], params=[], call_order=0, has_io=False, has_loop=False,
        returns_value=True, is_terminal=False, is_dead=False,
    )
    defaults.update(kw)
    return schema.Node(id=nid, **defaults)


class SpecimenLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.placement = layout.BusLayout().layout(cls.graph)

    def side(self, ids):
        return {i: self.placement["specimen." + i][0] for i in ids}

    def test_entry_is_the_bus(self):
        self.assertEqual(self.placement["specimen.main.main"], ("bus", 0))

    def test_output_chain_tail_goes_below(self):
        below = sorted(
            nid for nid, (side, _) in self.placement.items() if side == "below"
        )
        self.assertEqual(below, [
            "specimen.report.format_footer",
            "specimen.report.format_header",
            "specimen.report.format_rows",
            "specimen.report.render_report",
            "specimen.summarize.build_summary",
            "specimen.summarize.grand_total",
            "specimen.summarize.total_by_category",
        ])

    def test_everything_else_goes_above(self):
        above = sorted(
            nid for nid, (side, _) in self.placement.items() if side == "above"
        )
        self.assertEqual(above, [
            "specimen.categorize.assign_category",
            "specimen.categorize.categorize_all",
            "specimen.ingest.load_transactions",
            "specimen.ingest.parse_line",
            "specimen.ingest.read_lines",
            "specimen.util.clean_text",
            "specimen.util.compute_checksum",
            "specimen.util.normalize_merchant",
            "specimen.util.parse_amount",
        ])

    def test_above_ranks_follow_dataflow(self):
        ranks = {
            nid: rank
            for nid, (side, rank) in self.placement.items()
            if side == "above"
        }
        # edges above: load->categorize_all, categorize_all->compute_checksum,
        # parse_amount->parse_line. Everything else is dataflow-isolated and
        # sits at the rank nearest the bus (max rank).
        self.assertEqual(ranks["specimen.ingest.load_transactions"], 0)
        self.assertEqual(ranks["specimen.util.parse_amount"], 0)
        self.assertEqual(ranks["specimen.categorize.categorize_all"], 1)
        self.assertEqual(ranks["specimen.ingest.parse_line"], 1)
        self.assertEqual(ranks["specimen.util.compute_checksum"], 2)
        for isolated in (
            "specimen.ingest.read_lines",
            "specimen.util.clean_text",
            "specimen.util.normalize_merchant",
            "specimen.categorize.assign_category",
        ):
            self.assertEqual(ranks[isolated], 2, isolated)

    def test_below_ranks_follow_dataflow(self):
        ranks = {
            nid: rank
            for nid, (side, rank) in self.placement.items()
            if side == "below"
        }
        self.assertEqual(ranks["specimen.summarize.total_by_category"], 0)
        self.assertEqual(ranks["specimen.report.format_header"], 0)
        self.assertEqual(ranks["specimen.report.format_rows"], 0)
        self.assertEqual(ranks["specimen.report.format_footer"], 0)
        self.assertEqual(ranks["specimen.summarize.grand_total"], 1)
        self.assertEqual(ranks["specimen.summarize.build_summary"], 2)
        self.assertEqual(ranks["specimen.report.render_report"], 3)


class LayoutErrors(unittest.TestCase):
    def test_pseudo_entry_raises(self):
        graph = schema.Graph(
            meta={"entry_point": "pkg.m.__main__", "entry_locals": [],
                  "resolution": {}, "tool_version": "0.1.0"},
            nodes=[node("pkg.m.run")], call_edges=[], dataflow_edges=[],
        )
        with self.assertRaises(CsdError):
            layout.BusLayout().layout(graph)

    def test_dataflow_cycle_raises(self):
        graph = schema.Graph(
            meta={"entry_point": "pkg.m.main", "entry_locals": [],
                  "resolution": {}, "tool_version": "0.1.0"},
            nodes=[node("pkg.m.main"), node("pkg.m.a"), node("pkg.m.b")],
            call_edges=[
                schema.CallEdge("pkg.m.main", "pkg.m.a", 2),
                schema.CallEdge("pkg.m.main", "pkg.m.b", 3),
            ],
            dataflow_edges=[
                schema.DataflowEdge("pkg.m.a", "pkg.m.b", "x", 2, "call"),
                schema.DataflowEdge("pkg.m.b", "pkg.m.a", "y", 3, "call"),
            ],
        )
        with self.assertRaises(CsdError):
            layout.BusLayout().layout(graph)


if __name__ == "__main__":
    unittest.main()
