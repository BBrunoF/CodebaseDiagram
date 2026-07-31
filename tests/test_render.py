import os
import re
import unittest
import xml.etree.ElementTree as ET

from csd import cli, layout, render

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

    def test_every_function_is_drawn_including_the_entry(self):
        self.assertEqual(self.svg.count('class="node'), len(self.graph.nodes))
        self.assertIn('data-id="specimen.main.main"', self.svg)

    def test_every_call_is_drawn(self):
        self.assertEqual(
            self.svg.count('class="call-edge"'), len(self.graph.call_edges)
        )

    def test_returns_come_back_to_the_caller(self):
        # every call whose callee returns a value gets an up-arrow back,
        # except the dead one, whose return stops in a stub
        returning = [
            e for e in self.graph.call_edges
            if self._node(e.callee).returns_value
            and not self._node(e.callee).is_dead
        ]
        self.assertEqual(
            self.svg.count('class="return-edge"'), len(returning)
        )
        self.assertEqual(self.svg.count('class="stub"'), 1)

    def test_dead_node_is_red_and_unique(self):
        self.assertEqual(self.svg.count('class="node dead"'), 1)
        match = re.search(
            r'<ellipse class="node dead"[^>]*data-id="([^"]+)"', self.svg
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "specimen.util.compute_checksum")

    def test_loop_nodes_are_ellipses(self):
        self.assertEqual(self.svg.count("<ellipse"), 4)

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

    def test_callers_render_above_their_callees(self):
        tops = {}
        for match in re.finditer(
            r'class="node[^"]*" data-id="([^"]+)"[^>]*?'
            r'(?:cy="(\d+)"|y="(\d+)")', self.svg
        ):
            nid, cy, y = match.group(1), match.group(2), match.group(3)
            tops[nid] = int(cy or y)
        for edge in self.graph.call_edges:
            self.assertLess(
                tops[edge.caller], tops[edge.callee],
                "%s -> %s" % (edge.caller, edge.callee),
            )

    def _node(self, nid):
        return {n.id: n for n in self.graph.nodes}[nid]


if __name__ == "__main__":
    unittest.main()
