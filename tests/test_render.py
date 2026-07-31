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

    def test_every_call_is_drawn(self):
        self.assertEqual(
            self.svg.count('class="call-edge"'), len(self.graph.call_edges)
        )

    def test_call_arrows_carry_the_argument_they_pass(self):
        # a call whose argument is a tracked value is drawn in that value's
        # colour; a call whose argument cannot be named stays grey
        passed = {
            (e.consumer, e.line) for e in self.graph.dataflow_edges
            if e.consumed_by == "call"
        }
        self.assertEqual(
            self.svg.count('class="call-edge" data-var='), len(passed)
        )
        self.assertIn('class="call-edge" data-var="transactions"', self.svg)

    def test_contained_calls_drop_straight_down(self):
        # the specimen is a pure tree, so every callee sits inside its
        # caller's bar and both arrows are plain verticals - no detours
        for d in re.findall(r'class="call-edge"[^>]*? d="([^"]+)"', self.svg):
            self.assertNotIn("H", d)
        for d in re.findall(r'class="return-edge"[^>]*? d="([^"]+)"', self.svg):
            self.assertNotIn("H", d)

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


class RenderLegend(unittest.TestCase):
    """A big package must not push its legend outside the canvas."""

    def setUp(self):
        nodes = [schema.Node(
            id="pkg.main.main", qualname="main", module="pkg.main",
            file="pkg/main.py", lines=[1, 2], params=[], call_order=0,
            has_io=False, has_loop=False, returns_value=False,
            is_terminal=False, is_dead=False,
        )]
        edges = []
        for i in range(40):
            nid = "pkg.m%02d.fn" % i
            nodes.append(schema.Node(
                id=nid, qualname="fn", module="pkg.m%02d" % i,
                file="pkg/m%02d.py" % i, lines=[1, 2], params=[],
                call_order=i + 1, has_io=False, has_loop=False,
                returns_value=False, is_terminal=False, is_dead=False,
            ))
            edges.append(schema.CallEdge("pkg.main.main", nid, i + 1))
        self.graph = schema.Graph(
            meta={"entry_point": "pkg.main.main", "entry_locals": [],
                  "resolution": {}, "tool_version": "0.1.0"},
            nodes=nodes, call_edges=edges, dataflow_edges=[],
        )
        placement = layout.CallTreeLayout().layout(self.graph)
        self.svg = render.render_svg(self.graph, placement)
        self.height = int(
            re.search(r'viewBox="0 0 (\d+) (\d+)"', self.svg).group(2)
        )
        self.width = int(
            re.search(r'viewBox="0 0 (\d+) (\d+)"', self.svg).group(1)
        )

    def test_every_module_has_a_legend_row(self):
        self.assertEqual(self.svg.count('class="legend-module"'), 41)

    def test_legend_fits_inside_the_canvas(self):
        for match in re.finditer(
            r'class="legend-\w+"><(?:rect|line) [^>]*?y1?="(\d+)"', self.svg
        ):
            self.assertLess(int(match.group(1)), self.height)
        for match in re.finditer(r'<text x="(\d+)"', self.svg):
            self.assertLess(int(match.group(1)), self.width)

    def test_module_colors_do_not_repeat(self):
        fills = re.findall(
            r'class="legend-module"><rect [^>]*fill="([^"]+)"', self.svg
        )
        self.assertEqual(len(fills), len(set(fills)))


class RenderLanes(unittest.TestCase):
    def test_call_enters_at_the_start_and_return_leaves_at_the_end(self):
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
                  "resolution": {}, "tool_version": schema.TOOL_VERSION},
            nodes=[node("pkg.m.main", 0, returns_value=False),
                   node("pkg.m.f", 1)],
            call_edges=[schema.CallEdge("pkg.m.main", "pkg.m.f", 2)],
            dataflow_edges=[],
        )
        svg = render.render_svg(
            graph, layout.CallTreeLayout().layout(graph)
        )
        call_x = int(re.search(
            r'class="call-edge"[^>]*? d="M (\d+)', svg
        ).group(1))
        return_x = int(re.search(
            r'class="return-edge"[^>]*? d="M (\d+)', svg
        ).group(1))
        # not merely to the right of the call: past the middle of the bar,
        # because the return happens at the end of the function
        bar_w = render.COL_W - render.BAR_GAP
        self.assertGreater(return_x - call_x, bar_w / 2)


class RenderRecursion(unittest.TestCase):
    def test_recursive_calls_are_drawn_as_recursion_edges(self):
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
                  "resolution": {}, "tool_version": schema.TOOL_VERSION},
            nodes=[node("pkg.m.main", 0, returns_value=False),
                   node("pkg.m.a", 1), node("pkg.m.b", 2)],
            call_edges=[
                schema.CallEdge("pkg.m.main", "pkg.m.a", 1),
                schema.CallEdge("pkg.m.a", "pkg.m.b", 2),
                schema.CallEdge("pkg.m.b", "pkg.m.a", 3),   # back edge
                schema.CallEdge("pkg.m.b", "pkg.m.b", 4),   # self call
            ],
            dataflow_edges=[],
        )
        svg = render.render_svg(
            graph, layout.CallTreeLayout().layout(graph)
        )
        # the two forward calls stay ordinary; the two recursive ones don't
        self.assertEqual(svg.count('class="call-edge"'), 2)
        self.assertEqual(svg.count('class="recursion-edge"'), 2)
        self.assertIn("stroke-dasharray", svg)


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
        paths = re.findall(r'class="call-edge"[^>]*? d="([^"]+)"', svg)
        self.assertEqual(len(paths), 4)
        # main->a and main->b drop straight into bars they contain;
        # a->h and b->h must reach outside the bar, so they turn
        self.assertEqual(len([d for d in paths if "H" in d]), 2)


if __name__ == "__main__":
    unittest.main()
