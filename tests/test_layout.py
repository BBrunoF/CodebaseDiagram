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


def instances(result, nid):
    """Every bar drawn for one function, left to right."""
    return sorted(
        (s for s in result.slots.values() if s.node_id == nid),
        key=lambda s: (s.band, s.column),
    )


def only(result, nid):
    found = instances(result, nid)
    assert len(found) == 1, "%s is drawn %d times" % (nid, len(found))
    return found[0]


class SpecimenCallTree(unittest.TestCase):
    """The specimen is a pure tree: nothing is shared, so nothing repeats."""

    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.result = layout.CallTreeLayout().layout(cls.graph)

    def test_every_function_is_drawn_exactly_once(self):
        self.assertEqual(len(self.result.slots), len(self.graph.nodes))

    def test_entry_spans_the_whole_run(self):
        slot = only(self.result, "specimen.main.main")
        self.assertEqual((slot.band, slot.degree, slot.column), ("reached", 0, 0))
        widest = max(s.column + s.span for s in self.result.slots.values())
        self.assertEqual(slot.span, widest)

    def test_placement_matches_the_call_tree(self):
        expected = {
            "specimen.main.main": (0, 0, 10),
            "specimen.ingest.load_transactions": (1, 0, 3),
            "specimen.ingest.read_lines": (2, 0, 1),
            "specimen.ingest.parse_line": (2, 1, 2),
            "specimen.util.clean_text": (3, 1, 1),
            "specimen.util.parse_amount": (3, 2, 1),
            "specimen.categorize.categorize_all": (1, 3, 1),
            "specimen.categorize.assign_category": (2, 3, 1),
            "specimen.util.normalize_merchant": (3, 3, 1),
            "specimen.util.compute_checksum": (1, 4, 1),
            "specimen.summarize.build_summary": (1, 5, 2),
            "specimen.summarize.total_by_category": (2, 5, 1),
            "specimen.summarize.grand_total": (2, 6, 1),
            "specimen.report.render_report": (1, 7, 3),
            "specimen.report.format_header": (2, 7, 1),
            "specimen.report.format_rows": (2, 8, 1),
            "specimen.report.format_footer": (2, 9, 1),
        }
        for nid, want in expected.items():
            slot = only(self.result, nid)
            self.assertEqual((slot.degree, slot.column, slot.span), want, nid)

    def test_every_callee_sits_inside_its_callers_bar(self):
        for edge in self.result.edges:
            if edge.kind != "call":
                continue
            parent = self.result.slots[edge.src]
            child = self.result.slots[edge.dst]
            self.assertLess(parent.degree, child.degree, edge.dst)
            self.assertGreaterEqual(child.column, parent.column, edge.dst)
            self.assertLessEqual(
                child.column + child.span, parent.column + parent.span, edge.dst
            )

    def test_leaves_are_one_column_wide(self):
        callers = {e.caller for e in self.graph.call_edges}
        for slot in self.result.slots.values():
            if slot.node_id not in callers:
                self.assertEqual(slot.span, 1, slot.node_id)


class SharedHelperIsRepeated(unittest.TestCase):
    """A helper reached by two callers is drawn under each of them, so no
    arrow has to travel sideways to find it."""

    def setUp(self):
        self.graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.a", 1),
             node("pkg.m.h", 2), node("pkg.m.b", 3)],
            [("pkg.m.main", "pkg.m.a"), ("pkg.m.main", "pkg.m.b"),
             ("pkg.m.a", "pkg.m.h"), ("pkg.m.b", "pkg.m.h")],
        )
        self.result = layout.CallTreeLayout().layout(self.graph)

    def test_the_helper_is_drawn_once_per_caller(self):
        self.assertEqual(len(instances(self.result, "pkg.m.h")), 2)

    def test_each_copy_sits_inside_the_bar_that_called_it(self):
        first, second = instances(self.result, "pkg.m.h")
        a = only(self.result, "pkg.m.a")
        b = only(self.result, "pkg.m.b")
        for parent, copy in ((a, first), (b, second)):
            self.assertEqual(copy.degree, parent.degree + 1)
            self.assertGreaterEqual(copy.column, parent.column)
            self.assertLessEqual(
                copy.column + copy.span, parent.column + parent.span
            )

    def test_the_callers_own_their_copy_so_the_entry_still_spans_all(self):
        self.assertEqual(only(self.result, "pkg.m.a").span, 1)
        self.assertEqual(only(self.result, "pkg.m.b").span, 1)
        self.assertEqual(only(self.result, "pkg.m.main").span, 2)

    def test_no_edge_leaves_its_parents_bar(self):
        for edge in self.result.edges:
            parent = self.result.slots[edge.src]
            child = self.result.slots[edge.dst]
            self.assertGreaterEqual(child.column, parent.column)


class SharedSubtreeIsDuplicatedWhole(unittest.TestCase):
    def test_a_helpers_own_callees_repeat_with_it(self):
        graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.a", 1), node("pkg.m.h", 2),
             node("pkg.m.deep", 3), node("pkg.m.b", 4)],
            [("pkg.m.main", "pkg.m.a"), ("pkg.m.main", "pkg.m.b"),
             ("pkg.m.a", "pkg.m.h"), ("pkg.m.b", "pkg.m.h"),
             ("pkg.m.h", "pkg.m.deep")],
        )
        result = layout.CallTreeLayout().layout(graph)
        self.assertEqual(len(instances(result, "pkg.m.h")), 2)
        self.assertEqual(len(instances(result, "pkg.m.deep")), 2)
        self.assertEqual(only(result, "pkg.m.main").span, 2)


class UnreachedBand(unittest.TestCase):
    def test_uncalled_subtree_gets_its_own_band(self):
        graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.used", 1),
             node("pkg.m.orphan", 2), node("pkg.m.helper", 3)],
            [("pkg.m.main", "pkg.m.used"), ("pkg.m.orphan", "pkg.m.helper")],
        )
        result = layout.CallTreeLayout().layout(graph)
        for nid, want in (
            ("pkg.m.main", ("reached", 0, 0, 1)),
            ("pkg.m.used", ("reached", 1, 0, 1)),
            ("pkg.m.orphan", ("unreached", 0, 0, 1)),
            ("pkg.m.helper", ("unreached", 1, 0, 1)),
        ):
            slot = only(result, nid)
            self.assertEqual(
                (slot.band, slot.degree, slot.column, slot.span), want, nid
            )


class LayoutErrors(unittest.TestCase):
    def test_pseudo_entry_raises(self):
        graph = graph_of([node("pkg.m.run")], [], entry="pkg.m.__main__")
        with self.assertRaises(CsdError):
            layout.CallTreeLayout().layout(graph)


class Recursion(unittest.TestCase):
    def test_back_edge_is_an_edge_not_another_bar(self):
        # a -> b -> a: the call back into a must not expand a second copy of
        # a underneath b, or the layout would never terminate
        graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.a", 1), node("pkg.m.b", 2)],
            [("pkg.m.main", "pkg.m.a"), ("pkg.m.a", "pkg.m.b"),
             ("pkg.m.b", "pkg.m.a")],
        )
        result = layout.CallTreeLayout().layout(graph)
        self.assertEqual(len(instances(result, "pkg.m.a")), 1)
        self.assertEqual(only(result, "pkg.m.a").degree, 1)
        self.assertEqual(only(result, "pkg.m.b").degree, 2)
        back = [e for e in result.edges if e.kind == "recursion"]
        self.assertEqual(len(back), 1)
        self.assertEqual(result.slots[back[0].dst].node_id, "pkg.m.a")

    def test_self_recursion_points_at_its_own_bar(self):
        graph = graph_of(
            [node("pkg.m.main", 0), node("pkg.m.walk", 1)],
            [("pkg.m.main", "pkg.m.walk"), ("pkg.m.walk", "pkg.m.walk")],
        )
        result = layout.CallTreeLayout().layout(graph)
        self.assertEqual(len(instances(result, "pkg.m.walk")), 1)
        back = [e for e in result.edges if e.kind == "recursion"]
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].src, back[0].dst)


if __name__ == "__main__":
    unittest.main()
