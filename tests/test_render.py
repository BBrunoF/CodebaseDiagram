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

    def test_plumbed_values_route_via_bus(self):
        # transactions passes through main (entry local), so even though
        # load_transactions and categorize_all share the above half, the
        # value lands on the bus and re-emerges: 2 segments, not 1 elbow
        self.assertEqual(self.svg.count('data-var="transactions"'), 2)
        # categorized: shared landing segment (deduped) + re-emerge to
        # compute_checksum (above) + re-emerge to build_summary (below)
        self.assertEqual(self.svg.count('data-var="categorized"'), 3)
        # header is render_report-internal flow, NOT main-plumbed:
        # stays a single direct elbow
        self.assertEqual(self.svg.count('data-var="header"'), 1)

    def test_var_legend_lists_entry_locals_only(self):
        self.assertEqual(self.svg.count('class="legend-var"'), 5)
        for var in ("transactions", "categorized", "integrity", "summary", "text"):
            self.assertIn(">%s<" % var, self.svg)

    def test_module_legend(self):
        for label in ("main.py", "ingest.py", "util.py", "categorize.py",
                      "summarize.py", "report.py"):
            self.assertIn(">%s<" % label, self.svg)

    def test_opposing_flow_verticals_dont_overlap(self):
        # a node that both produces a value (landing on the bus) and
        # consumes one (re-emerging from it) must not draw the two
        # vertical segments on the same x
        verts = re.findall(
            r'class="flow-edge"[^>]*d="M (\d+) (\d+) L (\d+) (\d+)"', self.svg
        )
        spans = {}
        for x1, y1, x2, y2 in verts:
            if x1 == x2:
                lo, hi = sorted((int(y1), int(y2)))
                spans.setdefault(int(x1), []).append((lo, hi))
        for x, ranges in spans.items():
            for i in range(len(ranges)):
                for j in range(i + 1, len(ranges)):
                    a, b = ranges[i], ranges[j]
                    self.assertFalse(
                        a[0] < b[1] and b[0] < a[1],
                        "overlapping flow verticals at x=%d" % x,
                    )

    def test_call_edges_only_where_values_dont_link(self):
        # grey call arrows remain only where no value edge or stub already
        # ties the pair: load->read_lines, load->parse_line,
        # parse_line->clean_text, categorize_all->assign_category,
        # assign_category->normalize_merchant
        self.assertEqual(self.svg.count('class="call-edge"'), 5)


if __name__ == "__main__":
    unittest.main()
