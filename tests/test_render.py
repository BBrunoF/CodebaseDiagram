import os
import re
import unittest
import xml.etree.ElementTree as ET

from csd import cli, layout, render, schema

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")


class RenderSpecimen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.placement = layout.CallTreeLayout().layout(cls.graph)
        cls.svg = render.render_svg(cls.graph, cls.placement)

    def test_well_formed_xml(self):
        ET.fromstring(self.svg)
        self.assertTrue(self.svg.startswith("<svg"))

    def test_deterministic(self):
        again = render.render_svg(self.graph, self.placement)
        self.assertEqual(self.svg, again)

    def test_no_input_output_bars_and_no_bus(self):
        self.assertNotIn(">INPUT<", self.svg)
        self.assertNotIn(">OUTPUT<", self.svg)
        self.assertNotIn('class="bus"', self.svg)

    def test_every_function_is_a_bar(self):
        self.assertEqual(self.svg.count('class="node'), len(self.graph.nodes))
        self.assertIn('data-id="specimen.main.main"', self.svg)

    def test_bar_width_tracks_the_span(self):
        widths = dict(re.findall(
            r'class="node[^"]*" data-id="([^"]+)"[^>]*width="(\d+)"', self.svg
        ))
        entry = int(widths["specimen.main.main"])
        leaf = int(widths["specimen.util.clean_text"])
        self.assertGreater(entry, leaf * 9)

    def test_containment_replaces_call_arrows(self):
        # the specimen is a pure tree: every call is shown by a bar sitting
        # inside its caller's bar, so no grey arrow is needed anywhere
        self.assertEqual(self.svg.count('class="call-edge"'), 0)

    def test_returns_come_back_to_the_caller(self):
        returning = [
            e for e in self.graph.call_edges
            if self._node(e.callee).returns_value
            and not self._node(e.callee).is_dead
        ]
        self.assertEqual(self.svg.count('class="return-edge"'), len(returning))
        self.assertEqual(self.svg.count('class="stub"'), 1)

    def test_dead_node_is_red_and_unique(self):
        self.assertEqual(self.svg.count('class="node dead"'), 1)
        match = re.search(
            r'class="node dead" data-id="([^"]+)"', self.svg
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "specimen.util.compute_checksum")

    def test_loop_functions_are_marked(self):
        self.assertEqual(self.svg.count("&#8635;"), 4)

    def test_io_badges(self):
        self.assertEqual(self.svg.count('class="io-badge"'), 2)

    def test_module_legend(self):
        for label in ("main.py", "ingest.py", "util.py", "categorize.py",
                      "summarize.py", "report.py"):
            self.assertIn(">%s<" % label, self.svg)

    def test_var_legend_lists_entry_locals_only(self):
        self.assertEqual(self.svg.count('class="legend-var"'), 5)
        for var in ("transactions", "categorized", "integrity", "summary", "text"):
            self.assertIn(">%s<" % var, self.svg)

    def _node(self, nid):
        return {n.id: n for n in self.graph.nodes}[nid]


class RenderSharedHelper(unittest.TestCase):
    def test_call_outside_the_bar_keeps_a_grey_arrow(self):
        def node(nid, order, **kw):
            base = dict(
                qualname=nid.rsplit(".", 1)[1], module="pkg.m", file="pkg/m.py",
                lines=[1, 2], params=[], call_order=order, has_io=False,
                has_loop=False, returns_value=True, is_terminal=False,
                is_dead=False,
            )
            base.update(kw)
            return schema.Node(id=nid, **base)

        graph = schema.Graph(
            meta={"entry_point": "pkg.m.main", "entry_locals": [],
                  "resolution": {}, "tool_version": "0.1.0"},
            nodes=[node("pkg.m.main", 0, returns_value=False),
                   node("pkg.m.a", 1), node("pkg.m.h", 2), node("pkg.m.b", 3)],
            call_edges=[
                schema.CallEdge("pkg.m.main", "pkg.m.a", 1),
                schema.CallEdge("pkg.m.main", "pkg.m.b", 2),
                schema.CallEdge("pkg.m.a", "pkg.m.h", 3),
                schema.CallEdge("pkg.m.b", "pkg.m.h", 4),
            ],
            dataflow_edges=[],
        )
        placement = layout.CallTreeLayout().layout(graph)
        svg = render.render_svg(graph, placement)
        # main->a and main->b are contained; a->h and b->h are not
        self.assertEqual(svg.count('class="call-edge"'), 2)


if __name__ == "__main__":
    unittest.main()
