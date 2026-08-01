"""The showcase package must actually showcase every capability.

`showcase/` exists to demonstrate the whole tool in one picture. That claim
is only worth anything if it is enforced, so each assertion below pins one
feature: if a change stops drawing recursion, or stops flagging deadness,
or stops putting unreached code in its own band, a test here fails.
"""
import os
import re
import unittest

from csd import cli, layout, render

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOWCASE = os.path.join(REPO, "showcase")
EXCLUDES = ("vendor",)


class ShowcaseCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.warnings = []
        cls.graph = cli.analyze_package(
            SHOWCASE, excludes=EXCLUDES, warnings=cls.warnings
        )
        cls.nodes = {n.id: n for n in cls.graph.nodes}
        cls.placement = layout.CallTreeLayout().layout(cls.graph)
        cls.svg = render.render_svg(cls.graph, cls.placement)
        cls.pairs = {(e.caller, e.callee) for e in cls.graph.call_edges}

    # --- the analysis side -------------------------------------------------

    def test_entry_point_is_main(self):
        self.assertEqual(self.graph.meta["entry_point"], "showcase.main.main")

    def test_all_three_resolution_buckets_are_exercised(self):
        counters = self.graph.meta["resolution"]
        for bucket in ("resolved", "unresolved_dynamic", "external"):
            self.assertGreater(counters[bucket], 0, bucket)

    def test_one_genuinely_dead_function_and_two_documented_false_positives(self):
        self.assertEqual(
            sorted(n.id for n in self.graph.nodes if n.is_dead),
            [
                "showcase.audit.compute_checksum",    # genuinely discarded
                "showcase.audit.normalize_headings",  # mutates in place
                "showcase.audit.validate_pages",      # raise-as-gate
            ],
        )

    def test_a_discarded_entry_local_drives_the_red_legend(self):
        by_var = {e["var"]: e["status"] for e in self.graph.meta["entry_locals"]}
        self.assertEqual(by_var["integrity"], "discarded")
        self.assertIn("consumed", by_var.values())

    def test_generator_counts_as_returning_a_value(self):
        self.assertTrue(self.nodes["showcase.discover.stream_pages"].returns_value)

    def test_io_badge_tracks_real_io_only(self):
        self.assertTrue(self.nodes["showcase.config.load_config"].has_io)
        self.assertTrue(self.nodes["showcase.publish.write_page"].has_io)
        # stats.read / stats.write are counters, not file methods
        self.assertFalse(self.nodes["showcase.audit.record_size"].has_io)

    def test_nested_function_resolves_through_its_enclosing_scope(self):
        self.assertIn(
            ("showcase.render.render_page", "showcase.render.render_page.heading"),
            self.pairs,
        )

    def test_self_method_call_resolves_but_instance_dispatch_does_not(self):
        self.assertIn(
            ("showcase.render.Template.render", "showcase.render.Template.slot"),
            self.pairs,
        )
        for _, callee in self.pairs:
            self.assertNotEqual(callee, "showcase.render.Template.render")

    def test_platform_redefinition_is_reported_not_fatal(self):
        self.assertIn("showcase.compat.default_encoding", self.nodes)
        self.assertTrue(
            any("default_encoding" in w for w in self.warnings), self.warnings
        )

    def test_overload_stubs_are_skipped(self):
        node = self.nodes["showcase.compat.coerce_text"]
        self.assertTrue(node.returns_value)  # the implementation, not a stub

    def test_vendored_python2_file_is_excluded(self):
        self.assertTrue(any("vendor" in w for w in self.warnings), self.warnings)
        for node in self.graph.nodes:
            self.assertNotIn("vendor", node.id)

    def test_every_dataflow_kind_appears(self):
        self.assertEqual(
            sorted({e.consumed_by for e in self.graph.dataflow_edges}),
            ["call", "external_call", "return"],
        )

    def test_a_helper_shared_by_several_callers(self):
        callers = {c for c, callee in self.pairs if callee == "showcase.text.slugify"}
        self.assertGreaterEqual(len(callers), 2)

    # --- the picture -------------------------------------------------------

    def test_self_recursion_is_drawn(self):
        self.assertIn(
            ("showcase.discover.walk_tree", "showcase.discover.walk_tree"),
            self.pairs,
        )
        self.assertIn('class="recursion-edge"', self.svg)

    def test_mutual_recursion_is_drawn(self):
        self.assertIn(
            ("showcase.parse.parse_block", "showcase.parse.parse_inline"), self.pairs
        )
        self.assertIn(
            ("showcase.parse.parse_inline", "showcase.parse.parse_block"), self.pairs
        )

    def test_unreached_band_has_structure_not_just_orphans(self):
        band = [s for s in self.placement.slots.values() if s.band == "unreached"]
        names = {s.node_id for s in band}
        self.assertIn("showcase.legacy.export_rss", names)
        self.assertIn("showcase.render.Template.render", names)
        # the band is laid out from its own roots, so it has depth
        self.assertGreater(max(s.degree for s in band), 0)
        self.assertIn('class="band-rule"', self.svg)

    def test_every_visual_element_appears_in_the_svg(self):
        for marker in (
            'class="node dead"',    # red outline
            'class="stub"',         # the return that never gets home
            'class="io-badge"',     # IO
            'class="call-edge"',
            'class="return-edge"',
            'class="recursion-edge"',
            'class="band-rule"',
            'class="legend-module"',
            'class="legend-var"',
        ):
            self.assertIn(marker, self.svg, marker)

    def test_loop_marker_is_used(self):
        self.assertIn("&#8635; ", self.svg)

    def test_several_modules_get_their_own_legend_colour(self):
        modules = {n.module for n in self.graph.nodes}
        self.assertGreaterEqual(len(modules), 8)
        self.assertIn("showcase.theme.loader", modules)  # a subpackage

    def test_call_tree_is_deep_enough_to_show_nesting(self):
        reached = [s for s in self.placement.slots.values() if s.band == "reached"]
        self.assertGreaterEqual(max(s.degree for s in reached), 3)

    def test_shared_helper_is_repeated_instead_of_arrowed(self):
        copies = [
            s for s in self.placement.slots.values()
            if s.node_id == "showcase.text.slugify"
        ]
        self.assertGreaterEqual(len(copies), 2)
        # every copy sits inside the bar that called it
        for copy in copies:
            parent = self.placement.slots[copy.parent]
            self.assertGreaterEqual(copy.column, parent.column)
            self.assertLessEqual(
                copy.column + copy.span, parent.column + parent.span
            )

    def test_no_call_or_return_arrow_travels_sideways(self):
        for cls in ("call-edge", "return-edge"):
            for d in re.findall(r'class="%s"[^>]*? d="([^"]+)"' % cls, self.svg):
                self.assertNotIn("H", d, cls)


class ShowcaseArtifactsAreCurrent(unittest.TestCase):
    """The committed diagram must match the committed source."""

    def test_committed_graph_json_is_up_to_date(self):
        produced = cli.analyze_package(SHOWCASE, excludes=EXCLUDES).to_json() + "\n"
        path = os.path.join(REPO, "docs", "showcase", "graph.json")
        with open(path, encoding="utf-8") as fh:
            committed = fh.read()
        self.assertEqual(
            produced.replace("\r\n", "\n"),
            committed.replace("\r\n", "\n"),
            "docs/showcase/graph.json is stale — regenerate it",
        )


if __name__ == "__main__":
    unittest.main()
