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
        cls.placement = layout.BusLayout().layout(cls.graph)
        cls.svg = render.render_svg(cls.graph, cls.placement)

    def test_well_formed_xml(self):
        ET.fromstring(self.svg)
        self.assertTrue(self.svg.startswith("<svg"))

    def test_deterministic(self):
        again = render.render_svg(self.graph, self.placement)
        self.assertEqual(self.svg, again)

    def test_one_shape_per_non_entry_node(self):
        self.assertEqual(self.svg.count('class="node'), 16)

    def test_loop_nodes_are_ellipses(self):
        self.assertEqual(self.svg.count("<ellipse"), 4)

    def test_dead_node_is_red_and_unique(self):
        self.assertEqual(self.svg.count('class="node dead"'), 1)
        match = re.search(
            r'<ellipse class="node dead"[^>]*data-id="([^"]+)"', self.svg
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "specimen.util.compute_checksum")

    def test_dead_stub_and_terminal_tick(self):
        self.assertEqual(self.svg.count('class="stub"'), 1)
        # text -> main() is the one value ending inside the bus
        self.assertEqual(self.svg.count('class="tick"'), 2)  # stub tick + text tick

    def test_io_badges(self):
        self.assertEqual(self.svg.count('class="io-badge"'), 2)

    def test_bus_and_frames(self):
        self.assertEqual(self.svg.count('class="bus"'), 1)
        self.assertIn(">INPUT<", self.svg)
        self.assertIn(">OUTPUT<", self.svg)
        self.assertIn(">main()<", self.svg)

    def test_crossing_value_lands_and_reemerges(self):
        # categorized: one same-half edge (-> compute_checksum) plus a
        # two-segment bus crossing (-> build_summary) = 3 paths
        self.assertEqual(self.svg.count('data-var="categorized"'), 3)

    def test_var_legend_lists_entry_locals_only(self):
        self.assertEqual(self.svg.count('class="legend-var"'), 5)
        for var in ("transactions", "categorized", "integrity", "summary", "text"):
            self.assertIn(">%s<" % var, self.svg)

    def test_module_legend(self):
        for label in ("main.py", "ingest.py", "util.py", "categorize.py",
                      "summarize.py", "report.py"):
            self.assertIn(">%s<" % label, self.svg)

    def test_call_edges_present(self):
        self.assertEqual(
            self.svg.count('class="call-edge"'), len(self.graph.call_edges)
        )


if __name__ == "__main__":
    unittest.main()
