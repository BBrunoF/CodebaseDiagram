import ast
import tempfile
import unittest

from csd import callgraph, symbols
from tests.helpers import make_package

FILES = {
    "util.py": """
        def helper(x):
            return x + 1
    """,
    "main.py": """
        import sys
        from . import util
        from .util import helper

        def local(n):
            return n

        def main():
            a = helper(1)
            b = util.helper(a)
            c = local(b)
            print(c)
            d = sys.stdin.read()
            unknown = getattr(util, "helper")
            unknown(d)
            return c

        if __name__ == "__main__":
            main()
    """,
}


class CallResolution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", FILES)
        self.modules = symbols.discover_modules(pkg)
        self.symtab = symbols.build_symbol_table(self.modules)
        self.sites, self.counters = callgraph.analyze_calls(self.modules, self.symtab)

    def resolved_pairs(self):
        return sorted(
            (s.caller, s.callee) for s in self.sites if s.bucket == "resolved"
        )

    def test_resolved_edges(self):
        self.assertEqual(
            self.resolved_pairs(),
            [
                ("<module>:pkg.main", "pkg.main.main"),   # the __main__ guard call
                ("pkg.main.main", "pkg.main.local"),
                ("pkg.main.main", "pkg.util.helper"),     # from-import call
                ("pkg.main.main", "pkg.util.helper"),     # module-attribute call
            ],
        )

    def test_buckets(self):
        # print, sys.stdin.read, getattr -> external; unknown(d) -> dynamic
        self.assertEqual(self.counters["resolved"], 4)
        self.assertEqual(self.counters["external"], 3)
        self.assertEqual(self.counters["unresolved_dynamic"], 1)

    def test_invariant_counters_sum_to_total_calls(self):
        total = sum(
            isinstance(n, ast.Call)
            for m in self.modules
            for n in ast.walk(m.tree)
        )
        self.assertEqual(sum(self.counters.values()), total)

    def test_every_site_has_exactly_one_bucket(self):
        for site in self.sites:
            self.assertIn(site.bucket, callgraph.BUCKETS)

    def test_dotted_name(self):
        expr = ast.parse("a.b.c", mode="eval").body
        self.assertEqual(callgraph.dotted_name(expr), "a.b.c")
        call = ast.parse("f()()", mode="eval").body
        self.assertIsNone(callgraph.dotted_name(call.func))


class SelfMethodCalls(unittest.TestCase):
    def test_self_method_resolves(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "pkg", {"cls.py": """
            class Greeter:
                def greet(self):
                    return self.name()

                def name(self):
                    return "n"
        """})
        modules = symbols.discover_modules(pkg)
        symtab = symbols.build_symbol_table(modules)
        sites, counters = callgraph.analyze_calls(modules, symtab)
        resolved = [s for s in sites if s.bucket == "resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].caller, "pkg.cls.Greeter.greet")
        self.assertEqual(resolved[0].callee, "pkg.cls.Greeter.name")


class NestedScopeCalls(unittest.TestCase):
    """Bare names resolve through enclosing FUNCTION scopes, innermost
    first — but never through a class body, which is not a lookup scope."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"n.py": """
            def helper(x):
                return x


            def outer(v):
                def inner(y):
                    return helper(y)

                def recur(n):
                    return recur(n - 1)

                z = inner(v)
                return z + recur(3)


            class Thing:
                def first(self):
                    return second()

                def second(self):
                    return 1


            def apply(fn, v):
                return fn(v)
        """})
        modules = symbols.discover_modules(pkg)
        symtab = symbols.build_symbol_table(modules)
        self.sites, self.counters = callgraph.analyze_calls(modules, symtab)

    def pairs(self):
        return sorted(
            (s.caller, s.callee) for s in self.sites if s.bucket == "resolved"
        )

    def test_call_to_a_nested_function_resolves(self):
        self.assertIn(("pkg.n.outer", "pkg.n.outer.inner"), self.pairs())

    def test_nested_function_reaches_module_scope(self):
        self.assertIn(("pkg.n.outer.inner", "pkg.n.helper"), self.pairs())

    def test_nested_self_recursion_resolves(self):
        self.assertIn(("pkg.n.outer.recur", "pkg.n.outer.recur"), self.pairs())
        self.assertIn(("pkg.n.outer", "pkg.n.outer.recur"), self.pairs())

    def test_sibling_method_by_bare_name_stays_unresolved(self):
        # `second()` inside a method is a NameError at runtime, not a call
        # to Thing.second — a class body is not an enclosing scope
        for caller, callee in self.pairs():
            self.assertNotEqual(callee, "pkg.n.Thing.second", caller)

    def test_callable_parameter_stays_unresolved(self):
        for caller, _ in self.pairs():
            self.assertNotEqual(caller, "pkg.n.apply")
        self.assertEqual(self.counters["unresolved_dynamic"], 2)  # second(), fn(v)


class RelativeImportsInInit(unittest.TestCase):
    def test_dot_import_in_package_init_resolves(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "pkg", {
            "__init__.py": """
                from .util import helper

                def boot():
                    return helper(1)
            """,
            "util.py": """
                def helper(x):
                    return x + 1
            """,
        })
        modules = symbols.discover_modules(pkg)
        symtab = symbols.build_symbol_table(modules)
        sites, _ = callgraph.analyze_calls(modules, symtab)
        resolved = [(s.caller, s.callee) for s in sites if s.bucket == "resolved"]
        self.assertIn(("pkg.boot", "pkg.util.helper"), resolved)

    def test_dot_import_in_nested_package_init_resolves(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "pkg", {
            "sub/__init__.py": """
                from . import leaf

                def use():
                    return leaf.leaf_fn()
            """,
            "sub/leaf.py": """
                def leaf_fn():
                    return 1
            """,
        })
        modules = symbols.discover_modules(pkg)
        symtab = symbols.build_symbol_table(modules)
        sites, _ = callgraph.analyze_calls(modules, symtab)
        resolved = [(s.caller, s.callee) for s in sites if s.bucket == "resolved"]
        self.assertIn(("pkg.sub.use", "pkg.sub.leaf.leaf_fn"), resolved)


if __name__ == "__main__":
    unittest.main()
