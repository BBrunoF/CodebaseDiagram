import tempfile
import unittest

from csd import symbols
from tests.helpers import make_package

SRC = """
    def free(a, b):
        for _ in range(a):
            b += 1
        return b


    def void():
        print("hi")


    class Thing:
        def method(self):
            def inner():
                while True:
                    break
            return inner
"""


class SymbolTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"mod.py": SRC})
        self.modules = symbols.discover_modules(pkg)
        self.table = symbols.build_symbol_table(self.modules)

    def test_module_discovery(self):
        names = sorted(m.name for m in self.modules)
        self.assertEqual(names, ["pkg", "pkg.mod"])
        mod = [m for m in self.modules if m.name == "pkg.mod"][0]
        self.assertEqual(mod.file, "pkg/mod.py")

    def test_functions_recorded_with_qualnames(self):
        self.assertEqual(
            sorted(self.table),
            ["pkg.mod.Thing.method", "pkg.mod.Thing.method.inner",
             "pkg.mod.free", "pkg.mod.void"],
        )

    def test_flags(self):
        free = self.table["pkg.mod.free"]
        self.assertEqual(free.params, ["a", "b"])
        self.assertTrue(free.returns_value)
        self.assertTrue(free.has_loop)
        void = self.table["pkg.mod.void"]
        self.assertFalse(void.returns_value)
        self.assertFalse(void.has_loop)
        # inner's while-loop must NOT leak into method
        method = self.table["pkg.mod.Thing.method"]
        self.assertFalse(method.has_loop)
        self.assertTrue(method.returns_value)
        inner = self.table["pkg.mod.Thing.method.inner"]
        self.assertTrue(inner.has_loop)

    def test_lines_are_recorded(self):
        free = self.table["pkg.mod.free"]
        self.assertEqual(free.lines[0], 2)
        self.assertGreater(free.lines[1], free.lines[0])


class Generators(unittest.TestCase):
    """A generator produces a value even though it never `return`s one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"g.py": """
            def stream(rows):
                for r in rows:
                    yield r


            def delegate(rows):
                yield from rows


            async def astream(rows):
                yield rows


            def plain():
                pass


            def hides_a_generator():
                def inner():
                    yield 1
                return 0
        """})
        self.table = symbols.build_symbol_table(symbols.discover_modules(pkg))

    def test_yield_counts_as_returning_a_value(self):
        self.assertTrue(self.table["pkg.g.stream"].returns_value)

    def test_yield_from_counts_as_returning_a_value(self):
        self.assertTrue(self.table["pkg.g.delegate"].returns_value)

    def test_async_generator_counts_as_returning_a_value(self):
        self.assertTrue(self.table["pkg.g.astream"].returns_value)

    def test_plain_function_still_returns_nothing(self):
        self.assertFalse(self.table["pkg.g.plain"].returns_value)

    def test_nested_generator_does_not_leak_to_its_parent(self):
        parent = self.table["pkg.g.hides_a_generator"]
        self.assertTrue(parent.returns_value)  # it returns 0
        self.assertTrue(self.table["pkg.g.hides_a_generator.inner"].returns_value)


class ConditionalDefinitions(unittest.TestCase):
    """Two defs of one name must not abort the whole analysis."""

    def build(self, source):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "pkg", {"d.py": source})
        redefined = []
        table = symbols.build_symbol_table(
            symbols.discover_modules(pkg), redefined=redefined
        )
        return table, redefined

    def test_platform_branches_keep_the_first_definition(self):
        table, redefined = self.build("""
            import sys

            if sys.platform == "win32":
                def paths():
                    return "win"
            else:
                def paths():
                    return "posix"
        """)
        self.assertIn("pkg.d.paths", table)
        self.assertEqual(table["pkg.d.paths"].lines[0], 5)  # the if-branch
        self.assertEqual(redefined, ["pkg.d.paths"])

    def test_typing_overload_stubs_are_skipped(self):
        table, redefined = self.build("""
            from typing import overload
            import typing

            @overload
            def widen(x: int) -> int: ...

            @typing.overload
            def widen(x: str) -> str: ...

            def widen(x):
                return x
        """)
        self.assertIn("pkg.d.widen", table)
        # the real implementation, not a stub, is the one kept
        self.assertEqual(table["pkg.d.widen"].lines[0], 11)
        self.assertEqual(redefined, [])

    def test_unique_names_report_nothing(self):
        table, redefined = self.build("""
            def a():
                return 1


            def b():
                return 2
        """)
        self.assertEqual(sorted(table), ["pkg.d.a", "pkg.d.b"])
        self.assertEqual(redefined, [])


if __name__ == "__main__":
    unittest.main()
