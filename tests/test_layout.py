import os
import unittest

from csd import cli, layout, schema
from csd.schema import CsdError

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")


def node(nid, order=0, **kw):
    defaults = dict(
        qualname=nid.rsplit(".", 1)[1], module="pkg.m", file="pkg/m.py",
        lines=[1, 2], params=[], call_order=order, has_io=False, has_loop=False,
        returns_value=True, is_terminal=False, is_dead=False,
    )
    defaults.update(kw)
    return schema.Node(id=nid, **defaults)


def graph_of(nodes, edges, entry="pkg.m.main"):
    return schema.Graph(
        meta={"entry_point": entry, "entry_locals": [], "resolution": {},
              "tool_version": "0.1.0"},
        nodes=nodes,
        call_edges=[schema.CallEdge(c, e, 1) for c, e in edges],
        dataflow_edges=[],
    )


class SpecimenCallTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.placement = layout.CallTreeLayout().layout(cls.graph)

    def test_entry_is_degree_zero(self):
        self.assertEqual(self.placement["specimen.main.main"], ("reached", 0))

    def test_degrees_match_call_depth(self):
        expected = {
            "specimen.ingest.load_transactions": 1,
            "specimen.categorize.categorize_all": 1,
            "specimen.util.compute_checksum": 1,
            "specimen.summarize.build_summary": 1,
            "specimen.report.render_report": 1,
            "specimen.ingest.read_lines": 2,
            "specimen.ingest.parse_line": 2,
            "specimen.categorize.assign_category": 2,
            "specimen.summarize.total_by_category": 2,
            "specimen.summarize.grand_total": 2,
            "specimen.report.format_header": 2,
            "specimen.report.format_rows": 2,
            "specimen.report.format_footer": 2,
            "specimen.util.clean_text": 3,
            "specimen.util.parse_amount": 3,
            "specimen.util.normalize_merchant": 3,
        }
        for nid, degree in expected.items():
            self.assertEqual(self.placement[nid], ("reached", degree), nid)

    def test_caller_is_always_above_callee(self):
        for edge in self.graph.call_edges:
            self.assertLess(
                self.placement[edge.caller][1],
                self.placement[edge.callee][1],
                "%s -> %s" % (edge.caller, edge.callee),
            )

    def test_specimen_has_no_unreached_band(self):
        bands = {band for band, _ in self.placement.values()}
        self.assertEqual(bands, {"reached"})


class LongestPathDegree(unittest.TestCase):
    def test_multi_depth_callee_takes_the_deepest(self):
        # b is called by main (0) and by a (1): it must sit below BOTH
        graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.a", 1), node("pkg.m.b", 2)],
            [("pkg.m.main", "pkg.m.a"), ("pkg.m.main", "pkg.m.b"),
             ("pkg.m.a", "pkg.m.b")],
        )
        placement = layout.CallTreeLayout().layout(graph)
        self.assertEqual(placement["pkg.m.a"], ("reached", 1))
        self.assertEqual(placement["pkg.m.b"], ("reached", 2))


class UnreachedBand(unittest.TestCase):
    def test_uncalled_subtree_gets_its_own_band(self):
        graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.used", 1),
             node("pkg.m.orphan", 2), node("pkg.m.helper", 3)],
            [("pkg.m.main", "pkg.m.used"), ("pkg.m.orphan", "pkg.m.helper")],
        )
        placement = layout.CallTreeLayout().layout(graph)
        self.assertEqual(placement["pkg.m.main"], ("reached", 0))
        self.assertEqual(placement["pkg.m.used"], ("reached", 1))
        self.assertEqual(placement["pkg.m.orphan"], ("unreached", 0))
        self.assertEqual(placement["pkg.m.helper"], ("unreached", 1))


class LayoutErrors(unittest.TestCase):
    def test_pseudo_entry_raises(self):
        graph = graph_of([node("pkg.m.run")], [], entry="pkg.m.__main__")
        with self.assertRaises(CsdError):
            layout.CallTreeLayout().layout(graph)

    def test_call_cycle_raises(self):
        graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.a", 1), node("pkg.m.b", 2)],
            [("pkg.m.main", "pkg.m.a"), ("pkg.m.a", "pkg.m.b"),
             ("pkg.m.b", "pkg.m.a")],
        )
        with self.assertRaises(CsdError):
            layout.CallTreeLayout().layout(graph)


if __name__ == "__main__":
    unittest.main()
