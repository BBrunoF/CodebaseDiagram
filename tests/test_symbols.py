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


if __name__ == "__main__":
    unittest.main()
