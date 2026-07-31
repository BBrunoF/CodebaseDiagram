import tempfile
import unittest

from csd import callgraph, dataflow, symbols
from tests.helpers import make_package


def run(src):
    tmp = tempfile.TemporaryDirectory()
    pkg = make_package(tmp.name, "pkg", {"m.py": src})
    modules = symbols.discover_modules(pkg)
    symtab = symbols.build_symbol_table(modules)
    sites, _ = callgraph.analyze_calls(modules, symtab)
    edges, consumed, terminal, journal = dataflow.analyze_dataflow(symtab, sites)
    tmp.cleanup()
    return edges, consumed, terminal, journal


def edge_tuples(edges):
    return sorted((e.producer, e.consumer, e.var, e.consumed_by) for e in edges)


BASE = """
def f():
    return 1

def g(v):
    return v

def h(v):
    return v
"""


class Dataflow(unittest.TestCase):
    def test_bound_then_passed_emits_call_edge(self):
        edges, consumed, terminal, _ = run(BASE + """
def main():
    x = f()
    return g(x)
""")
        self.assertIn(("pkg.m.f", "pkg.m.g", "x", "call"), edge_tuples(edges))
        self.assertIn("pkg.m.f", consumed)
        self.assertEqual([s.callee for s in terminal], [])

    def test_direct_nesting_emits_anonymous_edge(self):
        edges, _, _, _ = run(BASE + """
def main():
    return g(f())
""")
        self.assertIn(("pkg.m.f", "pkg.m.g", "", "call"), edge_tuples(edges))

    def test_discarded_binding_is_terminal(self):
        edges, consumed, terminal, _ = run(BASE + """
def main():
    x = f()
    return 0
""")
        self.assertEqual(edges, [])
        self.assertNotIn("pkg.m.f", consumed)
        self.assertEqual([s.callee for s in terminal], ["pkg.m.f"])

    def test_bare_call_is_terminal(self):
        _, _, terminal, _ = run(BASE + """
def main():
    f()
    return 0
""")
        self.assertEqual([s.callee for s in terminal], ["pkg.m.f"])

    def test_external_read_emits_external_call_edge(self):
        edges, consumed, _, _ = run(BASE + """
def main():
    x = f()
    print(x)
""")
        self.assertIn(
            ("pkg.m.f", "pkg.m.main", "x", "external_call"), edge_tuples(edges)
        )
        self.assertIn("pkg.m.f", consumed)

    def test_return_name_emits_return_edge(self):
        edges, _, _, _ = run(BASE + """
def main():
    x = f()
    return x
""")
        self.assertIn(("pkg.m.f", "pkg.m.main", "x", "return"), edge_tuples(edges))

    def test_return_composite_propagates(self):
        edges, _, _, _ = run(BASE + """
def main():
    a = f()
    return a + 1
""")
        self.assertIn(("pkg.m.f", "pkg.m.main", "a", "return"), edge_tuples(edges))

    def test_conditional_read_consumes_without_edge(self):
        edges, consumed, terminal, _ = run(BASE + """
def main():
    x = f()
    if x:
        return 1
    return 0
""")
        self.assertEqual(edges, [])
        self.assertIn("pkg.m.f", consumed)
        self.assertEqual(terminal, [])

    def test_rebind_makes_first_site_terminal(self):
        edges, consumed, terminal, _ = run(BASE + """
def main():
    x = f()
    x = g(1)
    return h(x)
""")
        self.assertEqual([s.callee for s in terminal], ["pkg.m.f"])
        self.assertIn(("pkg.m.g", "pkg.m.h", "x", "call"), edge_tuples(edges))
        self.assertNotIn("pkg.m.f", consumed)

    def test_two_reads_emit_two_edges(self):
        edges, _, _, _ = run(BASE + """
def main():
    c = f()
    g(c)
    h(c)
""")
        tuples = edge_tuples(edges)
        self.assertIn(("pkg.m.f", "pkg.m.g", "c", "call"), tuples)
        self.assertIn(("pkg.m.f", "pkg.m.h", "c", "call"), tuples)

    def test_method_read_consumes(self):
        edges, consumed, terminal, _ = run(BASE + """
def main():
    x = f()
    return x.bit_length()
""")
        self.assertIn("pkg.m.f", consumed)
        self.assertEqual(terminal, [])

    def test_journal_records_bind_order_and_status(self):
        _, _, _, journal = run(BASE + """
def main():
    a = f()
    b = g(a)
    dead = h(1)
    print(b)
""")
        entry = journal["pkg.m.main"]
        self.assertEqual([b.var for b in entry], ["a", "b", "dead"])
        self.assertEqual(
            [b.consumed for b in entry], [True, True, False]
        )
        self.assertEqual(entry[2].site.callee, "pkg.m.h")


if __name__ == "__main__":
    unittest.main()
