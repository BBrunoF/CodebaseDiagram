import contextlib
import io
import os
import tempfile
import unittest

from csd import cli

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")
GOLDEN = os.path.join(REPO, "tests", "golden", "specimen_graph.json")


class EndToEnd(unittest.TestCase):
    def test_analyze_then_render(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        graph_path = os.path.join(tmp.name, "graph.json")
        svg_path = os.path.join(tmp.name, "diagram.svg")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                cli.main(["analyze", SPECIMEN, "-o", graph_path]), 0
            )
            self.assertEqual(
                cli.main(["render", graph_path, "-o", svg_path]), 0
            )
        self.assertEqual(len(out.getvalue().splitlines()), 3)
        with open(svg_path, encoding="utf-8") as fh:
            svg = fh.read()
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn('class="node dead"', svg)

    def test_golden_graph_json(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        graph_path = os.path.join(tmp.name, "graph.json")
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["analyze", SPECIMEN, "-o", graph_path])
        with open(graph_path, encoding="utf-8") as fh:
            produced = fh.read()
        with open(GOLDEN, encoding="utf-8") as fh:
            golden = fh.read()
        # git on Windows may check the golden out with CRLF; normalize both
        self.assertEqual(
            produced.replace("\r\n", "\n"), golden.replace("\r\n", "\n")
        )

    def test_render_missing_graph_errors_cleanly(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(
                ["render", os.path.join(REPO, "nope.json"), "-o", "x.svg"]
            )
        self.assertEqual(code, 1)
        self.assertIn("csd: error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
