import tempfile
import unittest

from csd import iotags, symbols
from tests.helpers import make_package

SRC = """
    import sys


    def uses_print(x):
        print(x)


    def uses_open(p):
        return open(p)


    def uses_argv():
        return sys.argv[1]


    def uses_read_attr(h):
        return h.read()


    def pure(a):
        return a + 1


    def outer():
        def inner():
            print("hidden")
        return inner
"""


class IoTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"m.py": SRC})
        modules = symbols.discover_modules(pkg)
        self.table = symbols.build_symbol_table(modules)

    def tagged(self, name):
        return iotags.tag_has_io(self.table["pkg.m." + name])

    def test_direct_markers(self):
        self.assertTrue(self.tagged("uses_print"))
        self.assertTrue(self.tagged("uses_open"))
        self.assertTrue(self.tagged("uses_argv"))
        self.assertTrue(self.tagged("uses_read_attr"))

    def test_pure_function_untagged(self):
        self.assertFalse(self.tagged("pure"))

    def test_no_transitive_and_no_nested_leak(self):
        # outer's body only defines inner; the print belongs to inner
        self.assertFalse(self.tagged("outer"))
        self.assertTrue(self.tagged("outer.inner"))


if __name__ == "__main__":
    unittest.main()
