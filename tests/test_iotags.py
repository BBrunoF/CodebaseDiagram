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


class ReadWriteAttributes(unittest.TestCase):
    """.read/.write means IO when it is CALLED. A field that happens to be
    named `read` is just a field."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"m.py": """
            import sys


            def reads_a_field(record):
                return record.read


            def writes_a_field(record):
                record.write = 1
                return record


            def calls_read(handle):
                return handle.read()


            def calls_write(handle):
                handle.write("x")


            def writes_stdout(msg):
                sys.stdout.write(msg)
        """})
        self.table = symbols.build_symbol_table(symbols.discover_modules(pkg))

    def tagged(self, name):
        return iotags.tag_has_io(self.table["pkg.m." + name])

    def test_attribute_access_is_not_io(self):
        self.assertFalse(self.tagged("reads_a_field"))
        self.assertFalse(self.tagged("writes_a_field"))

    def test_calling_read_or_write_is_io(self):
        self.assertTrue(self.tagged("calls_read"))
        self.assertTrue(self.tagged("calls_write"))
        self.assertTrue(self.tagged("writes_stdout"))


if __name__ == "__main__":
    unittest.main()
