import ast
import contextlib
import io
import json
import os
import re
import tempfile
import unittest

from csd import cli, schema
from tests.helpers import make_package

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")


class AnalyzePackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.nodes = {n.id: n for n in cls.graph.nodes}

    def test_entry_point(self):
        self.assertEqual(self.graph.meta["entry_point"], "specimen.main.main")

    def test_planted_dead_function(self):
        node = self.nodes["specimen.util.compute_checksum"]
        self.assertTrue(node.is_dead)
        self.assertTrue(node.is_terminal)
        for other_id, other in self.nodes.items():
            if other_id != "specimen.util.compute_checksum":
                self.assertFalse(other.is_dead, other_id)

    def test_io_tags(self):
        tagged = sorted(n.id for n in self.graph.nodes if n.has_io)
        self.assertEqual(
            tagged, ["specimen.ingest.read_lines", "specimen.main.main"]
        )

    def test_loop_tags(self):
        looped = sorted(n.id for n in self.graph.nodes if n.has_loop)
        self.assertEqual(
            looped,
            [
                "specimen.categorize.categorize_all",
                "specimen.ingest.load_transactions",
                "specimen.report.format_rows",
                "specimen.util.compute_checksum",
            ],
        )

    def test_entry_locals(self):
        locals_ = self.graph.meta["entry_locals"]
        self.assertEqual(
            [e["var"] for e in locals_],
            ["transactions", "categorized", "integrity", "summary", "text"],
        )
        by_var = {e["var"]: e for e in locals_}
        self.assertEqual(by_var["integrity"]["status"], "discarded")
        for var in ("transactions", "categorized", "summary", "text"):
            self.assertEqual(by_var[var]["status"], "consumed")

    def test_key_dataflow_edges(self):
        tuples = {
            (e.producer, e.consumer, e.var, e.consumed_by)
            for e in self.graph.dataflow_edges
        }
        expected = {
            ("specimen.ingest.load_transactions",
             "specimen.categorize.categorize_all", "transactions", "call"),
            ("specimen.categorize.categorize_all",
             "specimen.util.compute_checksum", "categorized", "call"),
            ("specimen.categorize.categorize_all",
             "specimen.summarize.build_summary", "categorized", "call"),
            ("specimen.summarize.build_summary",
             "specimen.report.render_report", "summary", "call"),
            ("specimen.report.render_report",
             "specimen.main.main", "text", "external_call"),
            ("specimen.summarize.total_by_category",
             "specimen.summarize.grand_total", "totals", "call"),
            ("specimen.report.format_rows",
             "specimen.report.render_report", "body", "return"),
        }
        self.assertTrue(expected.issubset(tuples), expected - tuples)

    def test_counters_invariant(self):
        total = 0
        for root, dirs, files in os.walk(SPECIMEN):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname.endswith(".py"):
                    with open(os.path.join(root, fname), encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                    total += sum(
                        isinstance(n, ast.Call) for n in ast.walk(tree)
                    )
        self.assertEqual(sum(self.graph.meta["resolution"].values()), total)

    def test_no_module_level_call_edges(self):
        for edge in self.graph.call_edges:
            self.assertFalse(edge.caller.startswith("<module>:"), edge)

    def test_call_orders_are_unique_and_start_at_entry(self):
        orders = sorted(n.call_order for n in self.graph.nodes)
        self.assertEqual(orders, list(range(len(self.graph.nodes))))
        self.assertEqual(self.nodes["specimen.main.main"].call_order, 0)


class AnalyzeCli(unittest.TestCase):
    def test_stdout_is_exactly_three_counter_lines(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out_path = os.path.join(tmp.name, "graph.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["analyze", SPECIMEN, "-o", out_path])
        self.assertEqual(code, 0)
        lines = buf.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertRegex(lines[0], r"^resolved \d+$")
        self.assertRegex(lines[1], r"^unresolved_dynamic \d+$")
        self.assertRegex(lines[2], r"^external \d+$")
        with open(out_path, encoding="utf-8") as fh:
            loaded = schema.Graph.from_json(fh.read())
        self.assertEqual(loaded.meta["entry_point"], "specimen.main.main")

    def test_exclude_skips_an_unparseable_vendored_tree(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "app", {
            "main.py": """
                def helper(x):
                    return x


                def main():
                    return helper(1)
            """,
            "vendor/legacy.py": 'print "python 2 syntax"\n',
        })
        out_path = os.path.join(tmp.name, "graph.json")

        # without --exclude, one vendored file kills the whole run
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["analyze", pkg, "-o", out_path])
        self.assertEqual(code, 1)
        self.assertIn("csd: error:", err.getvalue())

        # with it, the package analyzes and the skip is reported on stderr
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(
                ["analyze", pkg, "-o", out_path, "--exclude", "vendor"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(out.getvalue().splitlines()), 3)
        self.assertIn("vendor", err.getvalue())
        with open(out_path, encoding="utf-8") as fh:
            loaded = schema.Graph.from_json(fh.read())
        self.assertEqual(
            sorted(n.id for n in loaded.nodes), ["app.main.helper", "app.main.main"]
        )

    def test_exclude_accepts_a_file_glob(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "app", {
            "main.py": "def main():\n    return 1\n",
            "wire_pb2.py": "def generated():\n    return 2\n",
        })
        out_path = os.path.join(tmp.name, "graph.json")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(
                ["analyze", pkg, "-o", out_path, "--exclude", "*_pb2.py"]
            )
        self.assertEqual(code, 0)
        with open(out_path, encoding="utf-8") as fh:
            loaded = schema.Graph.from_json(fh.read())
        self.assertEqual([n.id for n in loaded.nodes], ["app.main.main"])

    def test_redefinition_is_reported_on_stderr(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "app", {"main.py": """
            import sys

            if sys.platform == "win32":
                def paths():
                    return "win"
            else:
                def paths():
                    return "posix"


            def main():
                return paths()
        """})
        out_path = os.path.join(tmp.name, "graph.json")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["analyze", pkg, "-o", out_path])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.getvalue().splitlines()), 3)
        self.assertIn("app.main.paths", err.getvalue())

    def test_error_exits_nonzero(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["analyze", os.path.join(REPO, "nope"), "-o", "x.json"])
        self.assertEqual(code, 1)
        self.assertIn("csd: error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
